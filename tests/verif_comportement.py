#!/usr/bin/env python3
"""Non-régression comportementale : ce que le modèle a fait du rapport.

    python3 tests/verif_comportement.py <transcript-hermes> [--pdf FACTURE]
                                        [--date-ref AAAA-MM-JJ]

La suite `test_facturx_extract.py` garde le script : à entrées données, elle
prouve que la sortie est exacte. Elle ne peut rien dire du modèle. Or la skill
ne vaut que par ce que l'utilisateur lit à la fin, et ça, seul un run réel le
montre.

Ce contrôle referme l'écart. Il prend la réponse d'un run hermes, la compare au
champ `rapport` que le script a produit pour la même facture, et signale toute
ligne surnuméraire ou manquante. Une altération devient ainsi détectable
mécaniquement, au lieu de se relire à l'œil.

Trois critères, tous binaires :

  1. le rapport est affiché sans altération — aucune ligne perdue, ajoutée ou
     déplacée à l'intérieur du texte ;
  2. rien n'est ajouté autour — c'est le mode de défaillance qui a résisté le
     plus longtemps : le préambule de compte rendu (« Script executed
     successfully », « Le script a été exécuté avec succès (code 0) ») ;
  3. le compte à rebours figure bien, tant que la bascule n'est pas passée.

Code de sortie 0 si les trois passent, 1 sinon — utilisable en CI dès qu'un
transcript est produit.

Historique de ce que ce contrôle a mesuré :

  V2  préambule « Le script a été exécuté avec succès (code 0) »   → critère 2
  W1  rapport recopié seul, rien autour                            → 3 sur 3
  W2  préambule « Script executed successfully. Here is the report:» → critère 2
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "finance", "facturx-reception", "scripts",
                      "facturx_extract.py")
FIXTURE_DEFAUT = os.path.join(ROOT, "tests", "fixtures", "Facture_FR_BASICWL.pdf")

ANSI = re.compile(r"\x1b\[[0-9;]*m")
CADRE_HERMES = re.compile(r"╭─.*?Hermes.*?─+╮")
BORDURE = re.compile(r"^[╰─╯╭╮\s]*$")

# Tournures qui trahissent la mécanique à quelqu'un qui n'a demandé que l'état
# de sa facture. Cherchées uniquement dans les lignes ajoutées au rapport.
BAVARDAGE = [
    ("mention du script", r"\bscripts?\b|facturx_extract"),
    ("compte rendu d'exécution", r"execut|succès|successfully|code de sortie|exit code"),
    ("mention du JSON", r"\bJSON\b"),
    ("nom de champ", r"summary\.|totals\.|conforme_reforme_fr|checks\[|\brapport\b"),
    ("phrase d'accueil", r"^\s*(voici|here is|résultat|bien sûr|j'ai )"),
    ("formule de politesse", r"j'espère|n'hésitez pas|si vous avez besoin"),
]


def reponse_finale(chemin: str) -> str:
    """Dernier bloc de réponse d'un transcript hermes, sans le cadre ANSI."""
    texte = ANSI.sub("", open(chemin, encoding="utf-8", errors="replace").read())
    final = CADRE_HERMES.split(texte)[-1].split("Resume this session")[0]
    lignes = [re.sub(r"^\s*[│┊]\s?", "", l).rstrip("│ ").rstrip()
              for l in final.splitlines()]
    return "\n".join(l for l in lignes if not BORDURE.match(l)).strip()


def rapport_attendu(pdf: str, date_ref: str | None) -> dict:
    commande = [sys.executable, SCRIPT, pdf, "--json-only"]
    if date_ref:
        commande += ["--date-ref", date_ref]
    proc = subprocess.run(commande, capture_output=True, text=True, cwd=ROOT)
    return json.loads(proc.stdout)


def lignes_utiles(texte: str) -> list[str]:
    """Le cadre du terminal supprime les lignes vides : on les ignore des deux
    côtés plutôt que de compter une différence qui n'en est pas une."""
    return [l for l in texte.splitlines() if l.strip()]


def controler(reponse: str, rapport: str, summary: dict) -> tuple[bool, list[str]]:
    attendues = lignes_utiles(rapport)
    rendues = lignes_utiles(reponse)
    verdicts: list[str] = []
    succes = True

    # ── 1. le rapport, sans altération ───────────────────────────────────
    manquantes = [l for l in attendues if l not in rendues]
    corps = [l for l in rendues if l in attendues]
    ordre_ok = corps == attendues
    puces_att = [l for l in attendues if l.startswith("- ")]
    puces_ren = [l for l in rendues if l.startswith("- ")]
    critere1 = not manquantes and ordre_ok and puces_att == puces_ren \
        and "…" not in reponse
    succes &= critere1
    verdicts.append("1. rapport sans altération       : %s" % ok(critere1))
    verdicts.append("     lignes attendues %d, rendues %d, manquantes %d"
                    % (len(attendues), len(rendues), len(manquantes)))
    for ligne in manquantes:
        verdicts.append("     MANQUANTE : %s" % ligne[:100])
    if not ordre_ok:
        verdicts.append("     ORDRE MODIFIÉ à l'intérieur du rapport")
    if "…" in reponse:
        verdicts.append("     ELLIPSE présente")
    verdicts.append("     puces : %d attendues, %d rendues"
                    % (len(puces_att), len(puces_ren)))

    # ── 2. rien autour ───────────────────────────────────────────────────
    ajoutees = [l for l in rendues if l not in attendues]
    critere2 = not ajoutees
    succes &= critere2
    verdicts.append("2. rien ajouté autour            : %s" % ok(critere2))
    for ligne in ajoutees:
        motifs = [nom for nom, motif in BAVARDAGE
                  if re.search(motif, ligne, re.I)]
        verdicts.append("     AJOUTÉE : %s" % ligne[:100])
        if motifs:
            verdicts.append("       → %s" % ", ".join(motifs))
    if rendues:
        debut = rendues[0] == attendues[0] if attendues else False
        fin = rendues[-1] == attendues[-1] if attendues else False
        verdicts.append("     commence par le rapport : %s | finit par le rapport : %s"
                        % (ok(debut), ok(fin)))

    # ── 3. compte à rebours ──────────────────────────────────────────────
    reforme = (summary or {}).get("reforme_fr") or {}
    attendu_rebours = (reforme.get("regime") == "avertissement"
                       and reforme.get("jours_avant_bascule"))
    if attendu_rebours:
        critere3 = "Il reste %d jour" % reforme["jours_avant_bascule"] in reponse
        verdicts.append("3. compte à rebours              : %s" % ok(critere3))
        succes &= critere3
    else:
        verdicts.append("3. compte à rebours              : sans objet "
                        "(bascule passée)")

    return succes, verdicts


def ok(valeur: bool) -> str:
    return "OUI" if valeur else "NON"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare la réponse d'un run hermes au rapport du script.")
    parser.add_argument("transcript", help="fichier de sortie d'un `hermes chat`")
    parser.add_argument("--pdf", default=FIXTURE_DEFAUT,
                        help="facture sur laquelle le run a porté")
    parser.add_argument("--date-ref", default=None,
                        help="date d'appréciation utilisée par le run")
    args = parser.parse_args(argv)

    resultat = rapport_attendu(args.pdf, args.date_ref)
    reponse = reponse_finale(args.transcript)
    if not reponse:
        print("Aucune réponse finale trouvée dans %s" % args.transcript)
        return 1

    succes, verdicts = controler(reponse, resultat["rapport"],
                                 resultat.get("summary", {}))
    print("Transcript : %s" % os.path.basename(args.transcript))
    print("Facture    : %s\n" % os.path.basename(args.pdf))
    for ligne in verdicts:
        print("  " + ligne)
    print("\n>>> %s" % ("CONFORME" if succes else "NON CONFORME"))
    return 0 if succes else 1


if __name__ == "__main__":
    sys.exit(main())

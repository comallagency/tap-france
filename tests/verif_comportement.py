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

Trois verdicts, trois codes de sortie :

  0  CONFORME          le modèle a affiché le rapport, et rien d'autre
  1  NON CONFORME      il l'a altéré, tronqué, ou y a ajouté quelque chose
  3  RUN INEXPLOITABLE le modèle n'a pas répondu — quota du fournisseur,
                       erreur serveur, réponse vide

Le troisième existe parce qu'un run avorté n'est pas un échec du modèle et ne
doit pas être compté comme tel dans une campagne. Sans lui, une coupure chez le
fournisseur d'inférence se lit comme une désobéissance, et on durcit une
consigne que personne n'a enfreinte. Observé pour de vrai : trois HTTP 429
d'affilée, et le détecteur comparait le rapport attendu à un journal d'erreurs.

Le code 3 plutôt que 2 : argparse réserve déjà le 2 aux erreurs d'invocation,
et une campagne doit pouvoir distinguer « mal appelé » de « run avorté ».

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


# Signes qu'aucune réponse n'a été produite. Cherchés dans la réponse finale,
# là où le modèle aurait dû écrire — pas dans le journal, où une erreur
# transitoire rattrapée par une nouvelle tentative n'a rien d'anormal.
PANNE_FOURNISSEUR = [
    ("quota du fournisseur épuisé", r"RateLimitError|HTTP 429|Rate limited after"),
    ("erreur du fournisseur", r"HTTP 5\d\d|Provider returned error|API call failed"),
    ("appel interrompu", r"Final error|Connection error|Timeout|timed out"),
]


def run_inexploitable(reponse: str, attendues: list[str]) -> str | None:
    """Raison pour laquelle le run n'a rien produit d'analysable, ou None.

    Le seul signe d'erreur ne suffit pas : un 429 rattrapé à la deuxième
    tentative laisse sa trace alors que la réponse est parfaite. On exige donc
    que le rapport soit **absent**, c'est-à-dire qu'aucune de ses lignes ne
    figure dans ce que le modèle a rendu.
    """
    if not reponse.strip():
        return "réponse vide"
    rendues = set(lignes_utiles(reponse))
    if attendues and rendues & set(attendues):
        return None
    for raison, motif in PANNE_FOURNISSEUR:
        if re.search(motif, reponse, re.I):
            return raison
    return None


def reponse_finale(chemin: str) -> str:
    """Dernier bloc de réponse d'un transcript hermes, sans le cadre ANSI."""
    with open(chemin, encoding="utf-8", errors="replace") as entree:
        return reponse_finale_texte(entree.read())


def reponse_finale_texte(brut: str) -> str:
    """Même chose, à partir du texte — pour tester le pelage du cadre."""
    texte = ANSI.sub("", brut)
    final = CADRE_HERMES.split(texte)[-1].split("Resume this session")[0]
    lignes = [re.sub(r"^\s*[│┊]\s?", "", l).rstrip("│ ").rstrip()
              for l in final.splitlines()]
    return "\n".join(l for l in lignes if not BORDURE.match(l)).strip()


SANS_SAXONCHE = os.path.join(ROOT, "tests", "fixtures", "sans_saxonche")


def executer(pdf: str, date_ref: str | None, saxon: bool) -> dict:
    commande = [sys.executable, SCRIPT, pdf, "--json-only"]
    if date_ref:
        commande += ["--date-ref", date_ref]
    env = dict(os.environ)
    if not saxon:
        env["PYTHONPATH"] = SANS_SAXONCHE + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(commande, capture_output=True, text=True, cwd=ROOT,
                          env=env)
    return json.loads(proc.stdout)


def rapport_attendu(pdf: str, date_ref: str | None, reponse: str) -> tuple[dict, str]:
    """Le rapport auquel comparer, et l'environnement supposé du run.

    Le bac à sable de l'agent n'a pas forcément `saxonche` : la validation y
    tombe alors au niveau 1, et le rapport est légitimement plus court. Comparer
    à celui de la machine locale accuserait le modèle d'avoir amputé un texte
    qu'il a fidèlement recopié — un détecteur qui accuse à tort ne vaut pas
    mieux qu'un détecteur qui laisse passer.

    On produit donc les deux rapports possibles et on retient celui qui colle,
    en disant lequel.
    """
    candidats = [(executer(pdf, date_ref, True), "saxonche installé (niveau 2)"),
                 (executer(pdf, date_ref, False), "saxonche absent (niveau 1)")]
    rendues = set(lignes_utiles(reponse))

    def recouvrement(candidat) -> float:
        """Mesure symétrique : compter les lignes communes ne suffit pas.

        Un rapport de niveau 2 en partage deux avec une réponse de niveau 1
        — l'en-tête et l'échéance — autant que le rapport de niveau 1 lui-même.
        Rapporter les communes à l'union départage : le candidat le plus court
        qui explique toute la réponse l'emporte sur le plus long qui n'en
        explique qu'un morceau.
        """
        attendues = set(lignes_utiles(candidat[0]["rapport"]))
        union = rendues | attendues
        return len(rendues & attendues) / len(union) if union else 0.0

    meilleur = max(candidats, key=recouvrement)
    return meilleur[0], meilleur[1]


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
        proche = plus_proche(ligne, manquantes)
        if proche:
            # Une ligne ajoutée qui ressemble à une ligne perdue n'est pas un
            # ajout : c'est une réécriture. Le dire, sinon le motif désigne
            # le mauvais problème.
            verdicts.append("     REFORMULÉE : %s" % ligne[:90])
            verdicts.append("       à la place de : %s" % proche[:90])
            continue
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

    # ── 3. échéance de la réforme ────────────────────────────────────────
    # Le rapport ne porte un compte à rebours que si la passe française a
    # tourné et trouvé quelque chose. Le détecteur suit la même règle : il
    # exige la phrase d'échéance que le rapport attendu contient, pas une
    # phrase décidée d'après la seule date.
    echeance = [l for l in attendues
                if l.startswith("Il reste ") or l.startswith("La conformité aux "
                                                             "règles françaises")]
    if echeance:
        critere3 = all(l in rendues for l in echeance)
        verdicts.append("3. échéance de la réforme        : %s" % ok(critere3))
        verdicts.append("     attendue : %s" % echeance[0][:90])
        succes &= critere3
    else:
        verdicts.append("3. échéance de la réforme        : sans objet "
                        "(le rapport n'en porte pas)")

    return succes, verdicts


def ok(valeur: bool) -> str:
    return "OUI" if valeur else "NON"


def plus_proche(ligne: str, candidates: list[str], seuil: float = 0.45) -> str | None:
    """Ligne perdue dont `ligne` est visiblement la réécriture, s'il y en a une.

    Sans ça, une puce reformulée serait comptée comme une ligne manquante *et*
    une ligne ajoutée, et le motif affiché désignerait le mauvais problème.
    """
    meilleure, score = None, seuil
    for candidate in candidates:
        ratio = ressemblance(ligne, candidate)
        if ratio > score:
            meilleure, score = candidate, ratio
    return meilleure


def mots(ligne: str) -> set[str]:
    return {m for m in re.findall(r"[\w’']+", ligne.lower()) if len(m) > 1}


def ressemblance(a: str, b: str) -> float:
    """Part des mots de la ligne la plus courte qu'on retrouve dans l'autre.

    Un ratio de caractères pénaliserait une puce raccourcie de moitié — or
    c'est précisément la forme que prend une reformulation.
    """
    ma, mb = mots(a), mots(b)
    if not ma or not mb:
        return 0.0
    return len(ma & mb) / min(len(ma), len(mb))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare la réponse d'un run hermes au rapport du script.")
    parser.add_argument("transcript", help="fichier de sortie d'un `hermes chat`")
    parser.add_argument("--pdf", default=FIXTURE_DEFAUT,
                        help="facture sur laquelle le run a porté")
    parser.add_argument("--date-ref", default=None,
                        help="date d'appréciation utilisée par le run")
    args = parser.parse_args(argv)

    reponse = reponse_finale(args.transcript)
    if not reponse:
        print("Aucune réponse finale trouvée dans %s" % args.transcript)
        return 1
    resultat, environnement = rapport_attendu(args.pdf, args.date_ref, reponse)
    attendues = lignes_utiles(resultat["rapport"])

    print("Transcript : %s" % os.path.basename(args.transcript))
    print("Facture    : %s" % os.path.basename(args.pdf))

    panne = run_inexploitable(reponse, attendues)
    if panne:
        print("\n  Le modèle n'a pas répondu : %s." % panne)
        print("  Rien à contrôler — ce run ne compte ni pour ni contre la skill.")
        print("\n>>> RUN INEXPLOITABLE")
        return 3

    print("Run mené avec : %s\n" % environnement)
    succes, verdicts = controler(reponse, resultat["rapport"],
                                 resultat.get("summary", {}))
    for ligne in verdicts:
        print("  " + ligne)
    print("\n>>> %s" % ("CONFORME" if succes else "NON CONFORME"))
    return 0 if succes else 1


if __name__ == "__main__":
    sys.exit(main())

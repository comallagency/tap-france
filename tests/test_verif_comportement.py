#!/usr/bin/env python3
"""Le détecteur de non-régression comportementale, mis à l'épreuve.

    python3 -m unittest tests.test_verif_comportement -v

Un détecteur non testé rassure sans garantir, ce qui vaut moins que pas de
détecteur du tout : on cesse de relire à l'œil en croyant être couvert.

Chaque cas ci-dessous part d'une réponse **conforme** et l'abîme d'une seule
manière — une puce retirée, une puce reformulée, deux puces interverties, une
phrase ajoutée en fin. Le détecteur doit refuser chacune, et pour le bon motif.

Les transcripts abîmés sont fabriqués à l'exécution à partir du rapport que le
script produit *aujourd'hui* : ils ne peuvent donc pas se périmer quand le
rapport évolue. Deux transcripts réels sont versionnés à côté, dans
`fixtures/transcripts/`, pour vérifier que le détecteur sait encore lire le
cadre d'un vrai `hermes chat` — c'est la partie qui, elle, dépend d'un format
extérieur.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import verif_comportement as vc  # noqa: E402

BASICWL = os.path.join(ROOT, "tests", "fixtures", "Facture_FR_BASICWL.pdf")
TRANSCRIPTS = os.path.join(ROOT, "tests", "fixtures", "transcripts")
DATE_AVANT = "2026-08-21"

# Cadre minimal d'un `hermes chat`, tel que le détecteur doit savoir le peler.
CADRE = """Query: Utilise la skill facturx-reception
Initializing agent...
────────────────────────────────────────

  ┊ 📚 skill     facturx-reception  0.0s
  ┊ 💻 $         python3 scripts/facturx_extract.py …  0.4s

╭─ ⚕ Hermes ───────────────────────────────────────────────────────────────────╮
%s
╰──────────────────────────────────────────────────────────────────────────────╯

Resume this session with:
  hermes --resume 20260821_000000_000000
"""


def transcript(reponse: str) -> str:
    return CADRE % reponse


class DetecteurCase(unittest.TestCase):
    """Socle : le rapport du jour, et de quoi l'abîmer."""

    @classmethod
    def setUpClass(cls):
        proc = subprocess.run(
            [sys.executable,
             os.path.join(ROOT, "skills", "finance", "facturx-reception",
                          "scripts", "facturx_extract.py"),
             BASICWL, "--json-only", "--date-ref", DATE_AVANT],
            capture_output=True, text=True, cwd=ROOT)
        cls.resultat = json.loads(proc.stdout)
        cls.rapport = cls.resultat["rapport"]
        cls.lignes = [l for l in cls.rapport.splitlines() if l.strip()]
        cls.puces = [i for i, l in enumerate(cls.lignes) if l.startswith("- ")]

    def controler(self, reponse: str):
        return vc.controler(reponse, self.rapport, self.resultat["summary"])

    def assertRefuse(self, reponse: str, motif: str):
        succes, verdicts = self.controler(reponse)
        rendu = "\n".join(verdicts)
        self.assertFalse(succes, "le détecteur a laissé passer :\n" + rendu)
        self.assertIn(motif, rendu, "motif attendu absent :\n" + rendu)
        return rendu


class TestReponseConforme(DetecteurCase):

    def test_le_rapport_seul_est_accepte(self):
        succes, verdicts = self.controler(self.rapport)
        self.assertTrue(succes, "\n".join(verdicts))

    def test_les_lignes_vides_ne_comptent_pas(self):
        """Le cadre du terminal les supprime : les compter produirait un faux
        positif à chaque run."""
        succes, _ = self.controler(self.rapport.replace("\n\n", "\n"))
        self.assertTrue(succes)


class TestTranscriptsAbimes(DetecteurCase):
    """Quatre façons d'abîmer une réponse conforme. Aucune ne doit passer."""

    def test_une_puce_retiree(self):
        lignes = list(self.lignes)
        perdue = lignes.pop(self.puces[4])
        rendu = self.assertRefuse("\n".join(lignes), "MANQUANTE")
        self.assertIn(perdue[:60], rendu)
        self.assertIn("1. rapport sans altération       : NON", rendu)

    def test_une_puce_reformulee(self):
        lignes = list(self.lignes)
        origine = lignes[self.puces[4]]
        lignes[self.puces[4]] = ("- Le SIREN du vendeur fait 14 chiffres au lieu "
                                 "de 9, à corriger.")
        rendu = self.assertRefuse("\n".join(lignes), "REFORMULÉE")
        self.assertIn("à la place de", rendu)
        self.assertIn(origine[:40], rendu)

    def test_deux_puces_interverties(self):
        """Aucune ligne perdue ni ajoutée : seul l'ordre change."""
        lignes = list(self.lignes)
        a, b = self.puces[0], self.puces[1]
        lignes[a], lignes[b] = lignes[b], lignes[a]
        rendu = self.assertRefuse("\n".join(lignes), "ORDRE MODIFIÉ")
        self.assertIn("manquantes 0", rendu)

    def test_une_phrase_ajoutee_en_fin(self):
        reponse = self.rapport + "\n\nJ'espère que cela répond à votre question."
        rendu = self.assertRefuse(reponse, "AJOUTÉE")
        self.assertIn("formule de politesse", rendu)
        self.assertIn("finit par le rapport : NON", rendu)

    def test_une_phrase_ajoutee_en_tete(self):
        """Le cas réellement observé sur deux runs."""
        reponse = "Script executed successfully. Here is the report:\n\n" + self.rapport
        rendu = self.assertRefuse(reponse, "AJOUTÉE")
        self.assertIn("compte rendu d'exécution", rendu)
        self.assertIn("commence par le rapport : NON", rendu)


class TestAutresAlterations(DetecteurCase):
    """Ce que le détecteur doit attraper au-delà des quatre cas demandés."""

    def test_puce_dupliquee(self):
        lignes = list(self.lignes)
        lignes.insert(self.puces[2], lignes[self.puces[2]])
        self.assertRefuse("\n".join(lignes), "ORDRE MODIFIÉ")

    def test_reformatage_markdown(self):
        reponse = self.rapport.replace("- ", "* ")
        self.assertRefuse(reponse, "MANQUANTE")

    def test_titre_ajoute(self):
        self.assertRefuse("## Analyse de la facture\n\n" + self.rapport, "AJOUTÉE")

    def test_ellipse_au_lieu_des_dernieres_puces(self):
        lignes = self.lignes[:self.puces[3]] + ["- …"]
        self.assertRefuse("\n".join(lignes), "ELLIPSE")

    def test_montant_arrondi_dans_l_entete(self):
        reponse = self.rapport.replace("671,15 €", "environ 671 €", 1)
        self.assertRefuse(reponse, "REFORMULÉE")

    def test_echeance_supprimee(self):
        lignes = [l for l in self.lignes if not l.startswith("Il reste ")]
        rendu = self.assertRefuse("\n".join(lignes), "MANQUANTE")
        self.assertIn("3. échéance de la réforme        : NON", rendu)


class TestEnvironnementDuRun(DetecteurCase):
    """Le bac à sable de l'agent n'a pas forcément saxonche.

    Le rapport y tombe alors au niveau 1, légitimement plus court. Comparer au
    rapport de la machine locale accuserait le modèle d'avoir amputé un texte
    qu'il a fidèlement recopié — c'est arrivé, sur le run X2."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.niveau1 = vc.executer(BASICWL, DATE_AVANT, saxon=False)["rapport"]

    def test_les_deux_rapports_different_bien(self):
        """Sans quoi le test suivant ne prouverait rien."""
        self.assertNotEqual(self.niveau1, self.rapport)
        self.assertIn("saxonche", self.niveau1)
        self.assertNotIn("- ", self.niveau1)

    def test_un_run_de_niveau_1_est_reconnu_conforme(self):
        resultat, environnement = vc.rapport_attendu(BASICWL, DATE_AVANT,
                                                     self.niveau1)
        self.assertIn("niveau 1", environnement)
        succes, verdicts = vc.controler(self.niveau1, resultat["rapport"],
                                        resultat["summary"])
        self.assertTrue(succes, "\n".join(verdicts))

    def test_un_run_de_niveau_2_reste_reconnu(self):
        resultat, environnement = vc.rapport_attendu(BASICWL, DATE_AVANT,
                                                     self.rapport)
        self.assertIn("niveau 2", environnement)
        succes, _ = vc.controler(self.rapport, resultat["rapport"],
                                 resultat["summary"])
        self.assertTrue(succes)

    def test_une_alteration_reste_detectee_au_niveau_1(self):
        """Le repli d'environnement ne doit pas devenir une porte de sortie."""
        abime = self.niveau1 + "\n\nVoici le résultat de l'analyse."
        resultat, _ = vc.rapport_attendu(BASICWL, DATE_AVANT, abime)
        succes, verdicts = vc.controler(abime, resultat["rapport"],
                                        resultat["summary"])
        self.assertFalse(succes)
        self.assertIn("AJOUTÉE", "\n".join(verdicts))


class TestLectureDunVraiTranscript(DetecteurCase):
    """Le détecteur doit savoir peler le cadre d'un vrai `hermes chat`.

    C'est la seule partie qui dépend d'un format extérieur, donc la seule qui
    puisse casser sans que le dépôt ait bougé."""

    def test_cadre_synthetique(self):
        """Le rapport enveloppé du cadre doit ressortir intact."""
        reponse = vc.reponse_finale_texte(transcript(self.rapport))
        succes, verdicts = self.controler(reponse)
        self.assertTrue(succes, "\n".join(verdicts))

    def test_cadre_synthetique_avec_preambule(self):
        reponse = vc.reponse_finale_texte(
            transcript("Voici le résultat :\n\n" + self.rapport))
        self.assertRefuse(reponse, "phrase d'accueil")

    def test_transcript_reel_conforme(self):
        """W1 — le rapport recopié seul."""
        reponse = vc.reponse_finale(os.path.join(TRANSCRIPTS, "w1_conforme.txt"))
        self.assertTrue(reponse.startswith("Facture n° FA-2017-0010"))
        self.assertTrue(reponse.rstrip().endswith("qu'il a émise."))

    def test_transcript_reel_de_niveau_1(self):
        """X2 — le bac à sable n'avait pas saxonche.

        Ce transcript est antérieur à l'évolution du rapport de niveau 1 : son
        verdict complet ne vaut plus, et c'est normal. Ce qu'on en garde, c'est
        ce qui ne se périme pas — le détecteur doit reconnaître l'environnement
        du run, sans quoi il accuserait le modèle d'avoir amputé le texte."""
        reponse = vc.reponse_finale(os.path.join(TRANSCRIPTS, "x2_niveau1.txt"))
        _, environnement = vc.rapport_attendu(BASICWL, DATE_AVANT, reponse)
        self.assertIn("niveau 1", environnement)
        self.assertIn("saxonche n'est pas installé", reponse)

    def test_transcript_reel_avec_preambule(self):
        """W2 — le préambule de compte rendu, tel qu'observé."""
        reponse = vc.reponse_finale(os.path.join(TRANSCRIPTS, "w2_preambule.txt"))
        premiere = reponse.splitlines()[0]
        self.assertEqual(premiere,
                         "Script executed successfully. Here is the report:")
        succes, verdicts = self.controler(reponse)
        self.assertFalse(succes)
        self.assertIn("compte rendu d'exécution", "\n".join(verdicts))


if __name__ == "__main__":
    unittest.main(verbosity=2)

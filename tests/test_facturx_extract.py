#!/usr/bin/env python3
"""Suite de tests du §11 de CONTRAT-facturx-reception.md.

    python3 -m unittest discover -s tests -v

Chaque test cite la ligne du contrat qu'il garde. Toute divergence entre le
code et le contrat est un bug du code, pas du test.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "skills", "finance", "facturx-reception", "scripts"))
import facturx_extract as fx  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "finance", "facturx-reception", "scripts",
                      "facturx_extract.py")
SKILL_DIR = os.path.dirname(os.path.dirname(SCRIPT))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

MINIMUM = os.path.join(FIXTURES, "Facture_FR_MINIMUM.pdf")
BASICWL = os.path.join(FIXTURES, "Facture_FR_BASICWL.pdf")
EN16931 = os.path.join(FIXTURES, "pdf_zf_en16931_1.pdf")
SANS_XML = os.path.join(FIXTURES, "sans_xml.pdf")
PAS_UN_PDF = os.path.join(FIXTURES, "pas_un_pdf.txt")
REPLI = os.path.join(FIXTURES, "facturx_repli.pdf")
XML_CASSE = os.path.join(FIXTURES, "facturx_xml_casse.pdf")
TOTAUX_FAUX = os.path.join(FIXTURES, "facturx_totaux_faux.pdf")
ISO8859 = os.path.join(FIXTURES, "facturx_iso8859.pdf")
SANS_PYPDF = os.path.join(FIXTURES, "sans_pypdf")
SANS_SOCLE = os.path.join(FIXTURES, "sans_socle")
SANS_SAXONCHE = os.path.join(FIXTURES, "sans_saxonche")

PASS_IDS = ("xsd", "profil_fnfe", "regles_fr_ctc", "alertes_fr", "coherence")

# Les règles françaises sont des avertissements avant la bascule, des points
# bloquants à partir de celle-ci. La suite épingle les deux régimes plutôt que
# de dépendre du jour où elle tourne — sans quoi elle changerait de résultat
# toute seule le 1er septembre 2026.
DATE_AVANT = "2026-08-21"
DATE_BASCULE = "2026-09-01"
DATE_APRES = "2027-01-15"


def run(*args, env=None):
    """Invoque le script comme le ferait le modèle : stdout, stderr, code.

    Épingle --date-ref si l'appelant ne l'a pas fait : aucun test ne doit
    dépendre de l'horloge.
    """
    args = list(args)
    if not any(a.startswith("--date-ref") for a in args):
        args += ["--date-ref", DATE_AVANT]
    proc = subprocess.run([sys.executable, SCRIPT, *args],
                          capture_output=True, text=True, cwd=ROOT, env=env)
    return proc


def sans(blocker):
    """Environnement où un module est rendu introuvable.

    PYTHONDONTWRITEBYTECODE évite que l'import du faux module ne dépose un
    __pycache__ dans les fixtures — ce que le test « aucune écriture disque »
    compterait à tort comme une écriture du script.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = blocker + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def payload(proc):
    """§2 — stdout contient un seul objet JSON, rien d'autre."""
    return json.loads(proc.stdout)


def passes(result):
    return {entry["id"]: entry for entry in result["validation"]["passes"]}


def not_applied(result):
    return {entry["pass"]: entry["reason"]
            for entry in result["validation"]["not_applied"]}


# Une fin de phrase, c'est un point suivi d'une espace ou de la fin du texte.
# Compter les points bruts casserait sur une valeur fautive citée telle quelle
# dans le message — « 19.00 », voire « 19.0.0 » pour une saisie aberrante.
FIN_DE_PHRASE = re.compile(r"[.!?](?=\s|$)")


def phrases(message):
    return len(FIN_DE_PHRASE.findall(message))


def by_severity(result, severity):
    return [c for c in result["checks"] if c["severity"] == severity]


def walk_amounts(node, path="", out=None):
    """Chemins de toutes les valeurs numériques natives rencontrées (§3)."""
    if out is None:
        out = []
    if isinstance(node, dict):
        for key, value in node.items():
            walk_amounts(value, "%s.%s" % (path, key), out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            walk_amounts(value, "%s[%d]" % (path, index), out)
    elif isinstance(node, float):
        out.append(path)
    return out


class ContractCase(unittest.TestCase):
    """Cas commun : le script s'exécute et rend un JSON unique."""

    @classmethod
    def result_for(cls, *args, env=None):
        proc = run(*args, env=env)
        return payload(proc), proc


# --------------------------------------------------------------------------
# §11 — les six cas du jeu de tests minimal
# --------------------------------------------------------------------------

class TestMinimum(ContractCase):
    """`Facture_FR_MINIMUM.pdf` : status ok, profil MINIMUM, lines [],
    profil_fnfe et regles_fr_ctc en not_applied, zéro erreur BR-CO-*."""

    @classmethod
    def setUpClass(cls):
        cls.result, cls.proc = cls.result_for(MINIMUM)

    def test_code_de_sortie_zero(self):
        self.assertEqual(self.proc.returncode, 0)

    def test_status_ok(self):
        self.assertEqual(self.result["status"], "ok")

    def test_profil_minimum(self):
        self.assertEqual(self.result["profile"]["label"], "MINIMUM")
        self.assertEqual(self.result["profile"]["id"], "urn:factur-x.eu:1p0:minimum")
        self.assertEqual(self.result["profile"]["source"], "xml")

    def test_lines_vide_pas_manquant(self):
        self.assertIn("lines", self.result["invoice"])
        self.assertEqual(self.result["invoice"]["lines"], [])

    def test_profil_fnfe_et_regles_fr_ctc_non_appliquees(self):
        declared = not_applied(self.result)
        self.assertIn("profil_fnfe", declared)
        self.assertIn("regles_fr_ctc", declared)
        for pass_id in ("profil_fnfe", "regles_fr_ctc"):
            self.assertFalse(passes(self.result)[pass_id]["applied"])
            self.assertTrue(declared[pass_id].strip(),
                            "§6 — toute passe non exécutée est déclarée avec sa raison")

    def test_xsd_et_coherence_appliquees(self):
        """§6 — ces deux passes de niveau 1 s'appliquent à tous les profils."""
        for pass_id in ("xsd", "coherence"):
            entry = passes(self.result)[pass_id]
            self.assertTrue(entry["applied"])
            self.assertEqual(entry["status"], "pass")
            self.assertEqual(entry["errors"], 0)

    def test_non_regression_1_aucune_erreur_br_co(self):
        """Test de non-régression n°1 du §11 : le garde-fou contre la régression
        la plus grave possible — déclarer non conforme une facture officiellement
        valide. La facture MINIMUM ne porte pas de montant déjà payé ; le
        supposer nul ferait échouer BR-CO-16 à tort."""
        offenders = [c for c in self.result["checks"]
                     if (c["id"] or "").startswith("BR-CO-")]
        self.assertEqual(offenders, [], "erreurs BR-CO-* sur une facture MINIMUM "
                                        "officielle FNFE parfaitement légale")

    def test_aucun_bloquant(self):
        self.assertEqual(self.result["summary"]["bloquants"], 0)

    def test_conformites_non_verifiees_restent_null(self):
        """§8 — null ne devient jamais false."""
        self.assertIsNone(self.result["summary"]["conforme_profil"])
        self.assertIsNone(self.result["summary"]["conforme_reforme_fr"])


class TestBasicWL(ContractCase):
    """`Facture_FR_BASICWL.pdf` : profil BASIC WL, profil_fnfe → 0 erreur,
    regles_fr_ctc → 9 bloquants, IBAN renseigné."""

    @classmethod
    def setUpClass(cls):
        cls.result, cls.proc = cls.result_for(BASICWL)

    def test_code_de_sortie_zero_malgre_non_conformite(self):
        """§2 — une facture non conforme est un résultat, pas une erreur."""
        self.assertEqual(self.proc.returncode, 0)
        self.assertEqual(self.result["status"], "ok")

    def test_profil_basic_wl(self):
        self.assertEqual(self.result["profile"]["label"], "BASIC WL")

    def test_profil_fnfe_zero_erreur(self):
        entry = passes(self.result)["profil_fnfe"]
        self.assertTrue(entry["applied"])
        self.assertEqual(entry["errors"], 0)
        self.assertEqual(entry["status"], "pass")

    def test_regles_fr_ctc_neuf_constatations(self):
        """Neuf règles françaises échouent. Leur sévérité dépend de la date,
        leur nombre non."""
        entry = passes(self.result)["regles_fr_ctc"]
        self.assertTrue(entry["applied"])
        self.assertEqual(entry["errors"], 9)
        self.assertEqual(entry["status"], "warn")  # avant la bascule
        found = [c for c in self.result["checks"] if c["layer"] == "regles_fr_ctc"]
        self.assertEqual(len(found), 9)

    def test_alertes_fr_non_executee_car_doublon(self):
        """§6 — le schematron _WARNING porte le même jeu de règles : l'exécuter
        compterait deux fois les mêmes constatations."""
        entry = passes(self.result)["alertes_fr"]
        self.assertFalse(entry["applied"])
        raison = not_applied(self.result)["alertes_fr"]
        self.assertIn("doublon mesuré", raison)
        self.assertIn("recouvrement", raison)
        self.assertIn("2026-09-01", raison)
        self.assertEqual([c for c in self.result["checks"]
                          if c["layer"] == "alertes_fr"], [])

    def test_iban_renseigne(self):
        self.assertEqual(self.result["invoice"]["payment"]["iban"],
                         "FR2012421242124212421242124")

    def test_lines_vide_en_basic_wl(self):
        """§4 — BASIC WL ne porte pas de lignes par construction."""
        self.assertEqual(self.result["invoice"]["lines"], [])

    def test_coherence_passe(self):
        self.assertEqual(passes(self.result)["coherence"]["errors"], 0)

    def test_summary_conforme_profil_mais_pas_reforme(self):
        summary = self.result["summary"]
        self.assertTrue(summary["conforme_profil"])
        self.assertFalse(summary["conforme_reforme_fr"])
        # Avant la bascule : les neuf constatations sont des avertissements.
        self.assertEqual(summary["bloquants"], 0)
        self.assertEqual(summary["alertes"], 9)

    def test_verdict_est_une_phrase_francaise_prete_a_afficher(self):
        self.assertEqual(
            self.result["summary"]["verdict"],
            "Facture valide au format Factur-X BASIC WL, mais non conforme aux "
            "règles françaises de la réforme (9 points : avertissements "
            "aujourd'hui, bloquants à partir du 1er septembre 2026).")

    def test_messages_en_francais_raw_conserve_l_original(self):
        """§7 — message reformulé, raw conservé pour traçabilité."""
        for check in self.result["checks"]:
            if check["layer"] == "regles_fr_ctc":
                self.assertTrue(check["message"])
                self.assertTrue(check["raw"])
                self.assertTrue(check["id"])


class TestEn16931(ContractCase):
    """`pdf_zf_en16931_1.pdf` : profil EN 16931, af_relationship /Alternative,
    method standard, profil_fnfe → 0 erreur, IBAN null."""

    @classmethod
    def setUpClass(cls):
        cls.result, cls.proc = cls.result_for(EN16931)

    def test_code_de_sortie_zero(self):
        self.assertEqual(self.proc.returncode, 0)
        self.assertEqual(self.result["status"], "ok")

    def test_profil_en16931(self):
        self.assertEqual(self.result["profile"]["label"], "EN 16931")

    def test_alternative_accepte_comme_data(self):
        """§5 — un filtre strict sur /Data rejetterait des factures valides."""
        self.assertEqual(self.result["detection"]["af_relationship"], "/Alternative")
        self.assertEqual(self.result["detection"]["method"], "standard")
        self.assertEqual(self.result["detection"]["notes"], [])

    def test_profil_fnfe_zero_erreur(self):
        entry = passes(self.result)["profil_fnfe"]
        self.assertTrue(entry["applied"])
        self.assertEqual(entry["errors"], 0)

    def test_iban_null(self):
        """§4 — l'IBAN n'est jamais présupposé, même en EN 16931."""
        self.assertIsNone(self.result["invoice"]["payment"]["iban"])

    def test_lignes_extraites(self):
        lines = self.result["invoice"]["lines"]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["net"], "198.00")

    def test_coherence_passe(self):
        self.assertEqual(passes(self.result)["coherence"]["errors"], 0)


class TestSansXml(ContractCase):
    """PDF sans XML embarqué : status unstructured, pas de champ invoice, code 0."""

    @classmethod
    def setUpClass(cls):
        cls.result, cls.proc = cls.result_for(SANS_XML)

    def test_status_unstructured_code_zero(self):
        self.assertEqual(self.result["status"], "unstructured")
        self.assertEqual(self.proc.returncode, 0)

    def test_champ_invoice_absent_pas_rempli_de_null(self):
        """§9 — la skill ne prétend pas avoir lu ce qu'elle n'a pas lu."""
        self.assertNotIn("invoice", self.result)

    def test_detection_vide(self):
        self.assertIsNone(self.result["detection"]["method"])
        self.assertIsNone(self.result["detection"]["attachment_name"])

    def test_conformites_null(self):
        self.assertIsNone(self.result["summary"]["conforme_profil"])
        self.assertIsNone(self.result["summary"]["conforme_reforme_fr"])


class TestFichierNonPdf(ContractCase):
    """Fichier non-PDF : status unreadable, code 1."""

    @classmethod
    def setUpClass(cls):
        cls.result, cls.proc = cls.result_for(PAS_UN_PDF, "--json-only")

    def test_status_unreadable_code_un(self):
        self.assertEqual(self.result["status"], "unreadable")
        self.assertEqual(self.proc.returncode, 1)

    def test_stdout_reste_un_json_unique(self):
        """§2 — stdout : un seul objet JSON, toujours."""
        self.assertIsInstance(self.result, dict)

    def test_json_only_tait_stderr(self):
        self.assertEqual(self.proc.stderr, "")

    def test_fichier_absent(self):
        result, proc = self.result_for(os.path.join(FIXTURES, "inexistant.pdf"))
        self.assertEqual(result["status"], "unreadable")
        self.assertEqual(proc.returncode, 1)


class TestSansSaxonche(ContractCase):
    """`saxonche` désinstallé : level 1, 3 passes en not_applied,
    conforme_reforme_fr null, code 0."""

    @classmethod
    def setUpClass(cls):
        # Un faux module saxonche prioritaire dans sys.path simule l'absence du
        # paquet sans toucher à l'environnement de l'utilisateur.
        cls.result, cls.proc = cls.result_for(BASICWL, "--json-only",
                                              env=sans(SANS_SAXONCHE))

    def test_absence_de_saxonche_n_est_jamais_une_erreur(self):
        self.assertEqual(self.proc.returncode, 0)
        self.assertEqual(self.result["status"], "ok")

    def test_niveau_1(self):
        self.assertEqual(self.result["validation"]["level"], 1)
        self.assertFalse(self.result["validation"]["engine"]["available"])
        self.assertIsNone(self.result["validation"]["engine"]["saxon"])

    def test_passes_saxon_non_appliquees(self):
        declared = not_applied(self.result)
        self.assertEqual(set(declared), {"profil_fnfe", "regles_fr_ctc", "alertes_fr"})
        for pass_id in ("profil_fnfe", "regles_fr_ctc"):
            self.assertIn("saxonche", declared[pass_id])
        # alertes_fr n'est pas exécutée même avec Saxon : c'est un doublon.
        self.assertIn("doublon mesuré", declared["alertes_fr"])

    def test_passes_de_niveau_1_toujours_disponibles(self):
        for pass_id in ("xsd", "coherence"):
            entry = passes(self.result)[pass_id]
            self.assertTrue(entry["applied"])
            self.assertEqual(entry["status"], "pass")

    def test_conforme_reforme_fr_null(self):
        """§8 — « non vérifié » n'est pas « non conforme »."""
        self.assertIsNone(self.result["summary"]["conforme_reforme_fr"])
        self.assertIsNone(self.result["summary"]["conforme_profil"])

    def test_message_d_invitation_en_info(self):
        """§6 — un message d'invitation dans checks, sévérité info."""
        infos = [c for c in by_severity(self.result, "info")
                 if "saxonche" in (c["message"] or "")]
        self.assertTrue(infos)
        self.assertEqual(len(by_severity(self.result, "bloquant")), 0)


# --------------------------------------------------------------------------
# §5 — les deux autres branches de la cascade de détection, et §9
# --------------------------------------------------------------------------

class TestDetectionEnRepli(ContractCase):
    """§5 cascade 2 : pièce jointe sans AFRelationship conforme ni MIME XML,
    mais dont la racine est rsm:CrossIndustryInvoice."""

    @classmethod
    def setUpClass(cls):
        cls.result, cls.proc = cls.result_for(REPLI, "--json-only")

    def test_method_fallback_et_note(self):
        self.assertEqual(self.result["status"], "ok")
        self.assertEqual(self.result["detection"]["method"], "fallback")
        self.assertEqual(self.result["detection"]["af_relationship"], "/Unspecified")
        self.assertTrue(self.result["detection"]["notes"])

    def test_repli_signale_en_info(self):
        """§7 — information opérationnelle : sévérité info."""
        infos = [c for c in by_severity(self.result, "info")
                 if c["layer"] == "detection"]
        self.assertEqual(len(infos), 1)

    def test_extraction_faite_malgre_le_repli(self):
        self.assertEqual(self.result["profile"]["label"], "BASIC WL")
        self.assertEqual(self.result["invoice"]["totals"]["gross"], "671.15")

    def test_nom_de_piece_jointe_non_conforme_sans_effet(self):
        """§5 — le nom du fichier n'est jamais un critère de détection."""
        self.assertEqual(self.result["detection"]["attachment_name"], "annexe.dat")


class TestXmlNonAnalysable(ContractCase):
    """§9 — invalid_xml : XML présent mais non parsable, code de sortie 0."""

    @classmethod
    def setUpClass(cls):
        cls.result, cls.proc = cls.result_for(XML_CASSE, "--json-only")

    def test_status_invalid_xml_code_zero(self):
        self.assertEqual(self.result["status"], "invalid_xml")
        self.assertEqual(self.proc.returncode, 0)

    def test_pas_de_champ_invoice(self):
        self.assertNotIn("invoice", self.result)

    def test_detection_reussie_avant_l_echec_de_parsing(self):
        self.assertEqual(self.result["detection"]["method"], "standard")

    def test_conformites_null(self):
        self.assertIsNone(self.result["summary"]["conforme_profil"])
        self.assertIsNone(self.result["summary"]["conforme_reforme_fr"])


class TestDependanceManquante(ContractCase):
    """Socle absent : un JSON normal, jamais un ImportError ni un traceback.

    C'est le cas où le modèle n'a rien à interpréter : stdout vide et une pile
    d'appels sur stderr le laisseraient inventer une explication."""

    @classmethod
    def setUpClass(cls):
        cls.pypdf, cls.proc = cls.result_for(BASICWL, "--json-only",
                                             env=sans(SANS_PYPDF))
        cls.socle, cls.proc_socle = cls.result_for(BASICWL, "--json-only",
                                                   env=sans(SANS_SOCLE))

    def test_status_et_code_de_sortie(self):
        self.assertEqual(self.pypdf["status"], "missing_dependency")
        self.assertEqual(self.proc.returncode, 1)

    def test_aucun_traceback_sur_stderr(self):
        self.assertEqual(self.proc.stderr, "")
        proc = run(BASICWL, env=sans(SANS_PYPDF))
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotIn("ImportError", proc.stderr)

    def test_stdout_reste_un_json_unique(self):
        """§2 — stdout : un seul objet JSON, toujours."""
        self.assertIsInstance(self.pypdf, dict)
        self.assertEqual(self.pypdf["schema_version"], "1.0")

    def test_manquant_liste_les_modules_absents(self):
        self.assertEqual(self.pypdf["manquant"], ["pypdf"])
        self.assertEqual(self.socle["manquant"], ["pypdf", "lxml"])

    def test_remede_cite_l_interpreteur_reel(self):
        """Un « pip install » générique installerait ailleurs."""
        for result in (self.pypdf, self.socle):
            remede = result["remede"]
            self.assertTrue(remede.startswith(sys.executable + " -m pip install "),
                            remede)
            for module in result["manquant"]:
                self.assertIn(module, remede.split("install", 1)[1])

    def test_pas_de_champ_invoice(self):
        """§9 — la skill ne prétend pas avoir lu ce qu'elle n'a pas lu."""
        self.assertNotIn("invoice", self.pypdf)

    def test_conformites_null(self):
        self.assertIsNone(self.pypdf["summary"]["conforme_profil"])
        self.assertIsNone(self.pypdf["summary"]["conforme_reforme_fr"])

    def test_les_cinq_passes_sont_declarees_non_appliquees(self):
        self.assertEqual(set(not_applied(self.pypdf)), set(PASS_IDS))

    def test_saxonche_absent_n_est_pas_une_dependance_manquante(self):
        """L'absence de saxonche est un mode normal, pas une panne."""
        result, proc = self.result_for(BASICWL, "--json-only",
                                       env=sans(SANS_SAXONCHE))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("manquant", result)
        self.assertEqual(result["validation"]["level"], 1)


class TestFichierHorsMontage(ContractCase):
    """`file_not_visible` : le fichier existe, mais pas de ce côté du montage.

    Un utilisateur tiers ne doit jamais tomber sur un échec muet à sa première
    facture — ni sur un diagnostic qui l'envoie corriger une faute de frappe
    inexistante."""

    CONTENEUR_SANS_WORKSPACE = {"conteneur": True, "skills_montees": True,
                                "workspace_monte": False}

    def test_les_trois_indices_sont_necessaires(self):
        """Il en manque un ⇒ chemin simplement absent."""
        self.assertTrue(fx.fichier_hors_montage(self.CONTENEUR_SANS_WORKSPACE))
        for absent in ("conteneur", "skills_montees"):
            indices = dict(self.CONTENEUR_SANS_WORKSPACE, **{absent: False})
            self.assertFalse(fx.fichier_hors_montage(indices), absent)
        monte = dict(self.CONTENEUR_SANS_WORKSPACE, workspace_monte=True)
        self.assertFalse(fx.fichier_hors_montage(monte))

    def test_indices_vides_ne_declenchent_rien(self):
        self.assertFalse(fx.fichier_hors_montage({}))

    def test_skills_montees_detecte_le_chemin_hermes(self):
        hermes = os.path.join(os.sep, "root", ".hermes", "skills", "finance",
                              "facturx-reception", "scripts", "facturx_extract.py")
        self.assertTrue(fx.indices_bac_a_sable(hermes)["skills_montees"])
        depot = os.path.join(os.sep, "home", "x", "depot", "skills", "finance",
                             "facturx-reception", "scripts", "facturx_extract.py")
        indices = fx.indices_bac_a_sable(depot)
        # Hors conteneur, la seule présence du chemin ne suffit jamais.
        self.assertFalse(fx.fichier_hors_montage(indices))

    def test_forme_du_json(self):
        manifest = fx.load_manifest()
        result = fx.file_not_visible_result("tests/fixtures/facture.pdf",
                                            self.CONTENEUR_SANS_WORKSPACE, manifest)
        self.assertEqual(result["status"], "file_not_visible")
        self.assertEqual(result["schema_version"], "1.0")
        self.assertNotIn("invoice", result)
        self.assertEqual(result["indices"], self.CONTENEUR_SANS_WORKSPACE)
        self.assertEqual(set(not_applied(result)), set(PASS_IDS))
        self.assertIsNone(result["summary"]["conforme_profil"])
        self.assertIsNone(result["summary"]["conforme_reforme_fr"])
        json.dumps(result)  # sérialisable

    def test_remede_donne_la_manipulation_exacte(self):
        manifest = fx.load_manifest()
        remede = fx.file_not_visible_result("f.pdf", self.CONTENEUR_SANS_WORKSPACE,
                                            manifest)["remede"]
        self.assertIn("docker_mount_cwd_to_workspace", remede)
        self.assertIn("true", remede)
        self.assertIn("container_persistent", remede)
        self.assertIn("docker rm -f", remede)
        self.assertIn("hermes-", remede)

    def test_check_bloquant_et_couche_environnement(self):
        manifest = fx.load_manifest()
        check = fx.file_not_visible_result("f.pdf", self.CONTENEUR_SANS_WORKSPACE,
                                           manifest)["checks"][0]
        self.assertEqual(check["severity"], "bloquant")
        self.assertEqual(check["layer"], "environnement")
        self.assertIn("remede", check["message"])

    def test_chemin_reellement_faux_reste_unreadable(self):
        """La régression à éviter : diagnostiquer un montage là où il n'y a
        qu'un chemin erroné."""
        result, proc = self.result_for(os.path.join(FIXTURES, "aucune_facture.pdf"),
                                       "--json-only")
        self.assertEqual(result["status"], "unreadable")
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("remede", result)

    def test_fichier_non_pdf_reste_unreadable(self):
        result, _ = self.result_for(PAS_UN_PDF, "--json-only")
        self.assertEqual(result["status"], "unreadable")


class TestRegimeDate(ContractCase):
    """§7 — la sévérité des règles françaises vient de la date d'application
    inscrite dans les en-têtes des deux schematrons jumeaux, pas de nous.

    Avant le 1er septembre 2026 elles sont des avertissements, à partir de ce
    jour-là des points bloquants. Le fait, lui, ne bouge pas."""

    @classmethod
    def setUpClass(cls):
        cls.avant, cls.proc_avant = cls.result_for(BASICWL, "--json-only",
                                                   "--date-ref", DATE_AVANT)
        cls.bascule, _ = cls.result_for(BASICWL, "--json-only",
                                        "--date-ref", DATE_BASCULE)
        cls.apres, _ = cls.result_for(BASICWL, "--json-only",
                                      "--date-ref", DATE_APRES)

    def test_avant_la_bascule_ce_sont_des_avertissements(self):
        self.assertEqual(self.avant["summary"]["reforme_fr"]["regime"],
                         "avertissement")
        self.assertEqual(self.avant["summary"]["bloquants"], 0)
        self.assertEqual(self.avant["summary"]["alertes"], 9)
        self.assertEqual({c["severity"] for c in self.avant["checks"]
                          if c["layer"] == "regles_fr_ctc"}, {"alerte"})
        self.assertEqual(passes(self.avant)["regles_fr_ctc"]["status"], "warn")

    def test_le_jour_de_la_bascule_ils_deviennent_bloquants(self):
        """La bascule est inclusive : le 1er septembre, le mode FATAL
        s'applique."""
        self.assertEqual(self.bascule["summary"]["reforme_fr"]["regime"],
                         "bloquant")
        self.assertEqual(self.bascule["summary"]["bloquants"], 9)
        self.assertEqual(self.bascule["summary"]["alertes"], 0)
        self.assertEqual({c["severity"] for c in self.bascule["checks"]
                          if c["layer"] == "regles_fr_ctc"}, {"bloquant"})
        self.assertEqual(passes(self.bascule)["regles_fr_ctc"]["status"], "fail")

    def test_apres_la_bascule_aussi(self):
        self.assertEqual(self.apres["summary"]["reforme_fr"]["regime"], "bloquant")
        self.assertEqual(self.apres["summary"]["bloquants"], 9)

    def test_le_fait_ne_bouge_pas_avec_la_date(self):
        """§8 — la question est « cette facture satisfait-elle les règles ? »,
        pas « suis-je sanctionnable aujourd'hui ». Le nombre de règles en échec
        et le verdict de conformité sont les mêmes des deux côtés."""
        for result in (self.avant, self.bascule, self.apres):
            self.assertFalse(result["summary"]["conforme_reforme_fr"])
            self.assertEqual(passes(result)["regles_fr_ctc"]["errors"], 9)
            self.assertTrue(result["summary"]["conforme_profil"])

    def test_le_compte_a_rebours_est_publie(self):
        reforme = self.avant["summary"]["reforme_fr"]
        self.assertEqual(reforme["bascule"], "2026-09-01")
        self.assertEqual(reforme["date_reference"], DATE_AVANT)
        self.assertEqual(reforme["jours_avant_bascule"], 11)
        self.assertIsNone(self.bascule["summary"]["reforme_fr"]["jours_avant_bascule"])

    def test_le_verdict_annonce_l_echeance(self):
        self.assertIn("avertissements aujourd'hui", self.avant["summary"]["verdict"])
        self.assertIn("1er septembre 2026", self.avant["summary"]["verdict"])
        self.assertIn("9 points bloquants", self.apres["summary"]["verdict"])
        self.assertNotIn("aujourd'hui", self.apres["summary"]["verdict"])

    def test_une_seule_passe_fr_ctc_dans_les_deux_regimes(self):
        for result in (self.avant, self.apres):
            self.assertTrue(passes(result)["regles_fr_ctc"]["applied"])
            self.assertFalse(passes(result)["alertes_fr"]["applied"])
            self.assertIn("doublon mesuré", not_applied(result)["alertes_fr"])

    def test_date_par_defaut_est_aujourd_hui(self):
        """L'horloge n'est lue qu'à cet endroit."""
        from datetime import date
        proc = subprocess.run([sys.executable, SCRIPT, BASICWL, "--json-only"],
                              capture_output=True, text=True, cwd=ROOT)
        result = json.loads(proc.stdout)
        self.assertEqual(result["summary"]["reforme_fr"]["date_reference"],
                         date.today().isoformat())

    def test_date_malformee_refusee(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT, BASICWL, "--json-only", "--date-ref", "1er septembre"],
            capture_output=True, text=True, cwd=ROOT)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("AAAA-MM-JJ", proc.stderr)


class TestMessagesReforme(ContractCase):
    """§7 — le message d'une règle BR-FR-* doit parler au destinataire de la
    facture, pas à l'intégrateur qui a écrit le schematron. Le texte officiel
    reste intégralement dans `raw`."""

    # Les seules règles françaises que déclenchent les fixtures officielles.
    ATTENDUES = {
        "BR-FR-05_BT-22_PMT", "BR-FR-05_BT-22_PMD", "BR-FR-05_BT-22_AAB",
        "BR-FR-08_BT-23", "BR-FR-10_BT-30", "BR-FR-12_BT-49", "BR-FR-13_BT-34",
        "BR-FR-16_BT-119", "BR-FR-16_BT-152", "BR-FR-32-LEGALID",
    }

    @classmethod
    def setUpClass(cls):
        cls.checks = []
        for fixture in (BASICWL, EN16931):
            result, _ = cls.result_for(fixture, "--json-only")
            cls.checks += [c for c in result["checks"]
                           if c["layer"] == "regles_fr_ctc"]

    def test_toutes_les_regles_declenchees_sont_reformulees(self):
        """Si une nouvelle règle se déclenche, elle doit être reformulée aussi."""
        self.assertEqual({c["id"] for c in self.checks}, self.ATTENDUES)

    def test_aucun_code_bt_nu_dans_le_message(self):
        """Un « BT-49 » nu ne dit rien à un artisan."""
        for check in self.checks:
            self.assertNotRegex(check["message"], r"\bB[TG]-\d+",
                                "%s : code sémantique nu" % check["id"])

    def test_aucun_nom_d_element_xml_dans_le_message(self):
        for check in self.checks:
            self.assertNotIn("ram:", check["message"], check["id"])
            self.assertNotIn("rsm:", check["message"], check["id"])

    def test_message_actionnable_et_court(self):
        for check in self.checks:
            message = check["message"]
            self.assertGreater(len(message), 80, check["id"])
            self.assertLessEqual(phrases(message), 4, check["id"])

    def test_raw_reste_le_texte_officiel_intact(self):
        for check in self.checks:
            self.assertTrue(check["raw"].startswith("BR-FR-"), check["id"])
            self.assertNotEqual(check["raw"], check["message"], check["id"])

    def test_meme_reformulation_quelle_que_soit_la_date(self):
        """La date change la sévérité, jamais le texte de la constatation."""
        avant, _ = self.result_for(BASICWL, "--json-only", "--date-ref", DATE_AVANT)
        apres, _ = self.result_for(BASICWL, "--json-only", "--date-ref", DATE_APRES)
        def par_id(r):
            return {c["id"]: c["message"] for c in r["checks"]
                    if c["layer"] == "regles_fr_ctc"}
        self.assertEqual(par_id(avant), par_id(apres))


class TestCoherenceDetecteVraimentUnEcart(ContractCase):
    """Contrepartie du test de non-régression n°1 : la prudence de la passe
    `coherence` ne doit pas la rendre aveugle. Fixture dérivée de la facture
    BASIC WL officielle, dont le seul total TTC a été faussé de 1,00 €."""

    @classmethod
    def setUpClass(cls):
        cls.result, cls.proc = cls.result_for(TOTAUX_FAUX, "--json-only")

    def test_ecart_arithmetique_bloquant(self):
        """§7 — un écart arithmétique est bloquant."""
        entry = passes(self.result)["coherence"]
        self.assertEqual(entry["status"], "fail")
        ids = [c["id"] for c in self.result["checks"] if c["layer"] == "coherence"]
        self.assertIn("BR-CO-15", ids)
        for check in self.result["checks"]:
            if check["layer"] == "coherence":
                self.assertEqual(check["severity"], "bloquant")

    def test_montants_cites_tels_quels_dans_le_message(self):
        """§3 — les montants restent des chaînes reprises du XML."""
        check = next(c for c in self.result["checks"]
                     if c["layer"] == "coherence" and c["id"] == "BR-CO-15")
        self.assertIn("670.15", check["message"])
        self.assertIn("671.15", check["message"])
        self.assertTrue(check["raw"].startswith("[BR-CO-15]"))

    def test_le_validateur_officiel_confirme_independamment(self):
        """La passe coherence et le validateur FNFE concluent séparément."""
        self.assertEqual(passes(self.result)["profil_fnfe"]["status"], "fail")
        self.assertFalse(self.result["summary"]["conforme_profil"])

    def test_verdict_sans_opposition_fautive(self):
        """Deux non-conformités s'additionnent, elles ne s'opposent pas."""
        verdict = self.result["summary"]["verdict"]
        self.assertNotIn("mais", verdict)
        self.assertTrue(verdict.startswith("Facture non conforme au profil"))

    def test_traduction_francaise_d_une_assertion_anglaise(self):
        """§7 — message en français, raw en anglais d'origine."""
        check = next(c for c in self.result["checks"]
                     if c["layer"] == "profil_fnfe" and c["id"] == "BR-CO-15")
        self.assertIn("total TTC", check["message"])
        self.assertIn("Invoice total amount with VAT", check["raw"])


class TestEncodageNonUtf8(ContractCase):
    """Un XML déclaré en ISO-8859-1 doit donner exactement le même résultat
    qu'en UTF-8 : c'est la même facture BASIC WL, réencodée. Le type MIME y est
    écrit sous sa forme échappée « /application#2Fxml », comme le veut la
    syntaxe des noms PDF."""

    @classmethod
    def setUpClass(cls):
        cls.result, cls.proc = cls.result_for(ISO8859, "--json-only")
        cls.reference, _ = cls.result_for(BASICWL, "--json-only")

    def test_detection_malgre_le_mime_echappe(self):
        self.assertEqual(self.result["status"], "ok")
        self.assertEqual(self.result["detection"]["method"], "standard")

    def test_accents_correctement_decodes(self):
        self.assertEqual(self.result["invoice"]["seller"]["name"], "Au bon moulin")
        self.assertNotIn("\ufffd", json.dumps(self.result))

    def test_memes_resultats_de_validation_qu_en_utf8(self):
        self.assertEqual(
            {p["id"]: (p["status"], p["errors"]) for p in
             self.result["validation"]["passes"]},
            {p["id"]: (p["status"], p["errors"]) for p in
             self.reference["validation"]["passes"]})

    def test_memes_totaux_qu_en_utf8(self):
        self.assertEqual(self.result["invoice"]["totals"],
                         self.reference["invoice"]["totals"])


# --------------------------------------------------------------------------
# Invariants transverses du contrat
# --------------------------------------------------------------------------

class TestInvariants(ContractCase):

    def test_montants_toujours_en_chaines(self):
        """§3 — jamais de float : la virgule flottante fausse les centimes."""
        for fixture in (MINIMUM, BASICWL, EN16931):
            result, _ = self.result_for(fixture)
            floats = walk_amounts(result)
            self.assertEqual(floats, [], "%s : valeurs flottantes en %s"
                             % (os.path.basename(fixture), floats))

    def test_structure_de_sortie_complete(self):
        """§4 — les clés du contrat sont toutes présentes."""
        result, _ = self.result_for(BASICWL)
        for key in ("schema_version", "status", "source", "detection", "profile",
                    "invoice", "validation", "checks", "summary"):
            self.assertIn(key, result)
        self.assertEqual(result["schema_version"], "1.0")
        for key in ("file", "sha256", "size_bytes"):
            self.assertIn(key, result["source"])
        for key in ("number", "type_code", "type_label", "issue_date", "due_date",
                    "currency", "buyer_reference", "order_reference", "billing_period",
                    "seller", "buyer", "totals", "vat_breakdown", "lines", "payment"):
            self.assertIn(key, result["invoice"])
        for key in ("name", "siren", "siret", "vat_id", "legal_id", "country",
                    "electronic_address"):
            self.assertIn(key, result["invoice"]["seller"])
        for key in ("line_net", "allowances", "charges", "net", "vat", "gross",
                    "prepaid", "due"):
            self.assertIn(key, result["invoice"]["totals"])
        for key in ("means_code", "means_label", "iban", "terms"):
            self.assertIn(key, result["invoice"]["payment"])
        for key in ("level", "engine", "schemas", "passes", "not_applied"):
            self.assertIn(key, result["validation"])
        for key in ("bloquants", "alertes", "conforme_profil", "conforme_reforme_fr",
                    "verdict"):
            self.assertIn(key, result["summary"])

    def test_les_cinq_passes_sont_toujours_declarees(self):
        """§6 — chaque passe non exécutée est déclarée dans not_applied."""
        for fixture in (MINIMUM, BASICWL, EN16931):
            result, _ = self.result_for(fixture)
            declared = passes(result)
            self.assertEqual(tuple(declared), PASS_IDS)
            skipped = {entry["id"] for entry in result["validation"]["passes"]
                       if not entry["applied"]}
            self.assertEqual(skipped, set(not_applied(result)),
                             "toute passe non appliquée doit porter sa raison")

    def test_severites_dans_le_vocabulaire_du_contrat(self):
        """§7 — bloquant | alerte | info, et rien d'autre."""
        for fixture in (MINIMUM, BASICWL, EN16931, SANS_XML):
            result, _ = self.result_for(fixture)
            for check in result["checks"]:
                self.assertIn(check["severity"], ("bloquant", "alerte", "info"))
                for key in ("id", "severity", "layer", "message", "location", "raw"):
                    self.assertIn(key, check)

    def test_compteurs_du_summary_derives_des_checks(self):
        """§8 — verdict et compteurs générés mécaniquement."""
        for fixture in (MINIMUM, BASICWL, EN16931):
            result, _ = self.result_for(fixture)
            self.assertEqual(result["summary"]["bloquants"],
                             len(by_severity(result, "bloquant")))
            self.assertEqual(result["summary"]["alertes"],
                             len(by_severity(result, "alerte")))

    def test_no_validate_declare_tout_en_non_applique(self):
        result, proc = self.result_for(BASICWL, "--no-validate")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(set(not_applied(result)), set(PASS_IDS))
        self.assertIsNone(result["summary"]["conforme_profil"])
        self.assertIsNone(result["summary"]["conforme_reforme_fr"])
        # L'extraction, elle, reste faite.
        self.assertEqual(result["invoice"]["totals"]["gross"], "671.15")

    def test_json_only_tait_stderr_sur_tous_les_cas(self):
        """§2 — stderr : diagnostics techniques uniquement, et rien du tout
        sous --json-only."""
        for fixture in (MINIMUM, BASICWL, EN16931, SANS_XML, PAS_UN_PDF, REPLI,
                        XML_CASSE, TOTAUX_FAUX, ISO8859):
            proc = run(fixture, "--json-only")
            self.assertEqual(proc.stderr, "", os.path.basename(fixture))
            json.loads(proc.stdout)

    def test_aucune_ecriture_disque(self):
        """§10 — aucune écriture disque : c'est ce qui rend la skill auditable."""
        def snapshot(directory):
            state = {}
            for root, _, files in os.walk(directory):
                for name in files:
                    path = os.path.join(root, name)
                    info = os.stat(path)
                    state[path] = (info.st_size, info.st_mtime_ns)
            return state

        before = {d: snapshot(d) for d in (SKILL_DIR, FIXTURES)}
        for fixture in (MINIMUM, BASICWL, EN16931, SANS_XML, PAS_UN_PDF, REPLI,
                        XML_CASSE, TOTAUX_FAUX, ISO8859):
            run(fixture, "--json-only")
        after = {d: snapshot(d) for d in (SKILL_DIR, FIXTURES)}
        self.assertEqual(before, after)

    def test_le_nom_du_fichier_n_est_pas_un_critere(self):
        """§5 — le nom du fichier est reporté, jamais utilisé pour décider."""
        result, _ = self.result_for(EN16931)
        self.assertEqual(result["detection"]["attachment_name"], "factur-x.xml")
        # Le PDF EN 16931 porte /Alternative : s'il avait fallu le nom pour le
        # retenir, la méthode serait « fallback ».
        self.assertEqual(result["detection"]["method"], "standard")


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Option d'installation : télécharge les schémas au lieu de les embarquer.

    python3 scripts/fetch_schemas.py [--check] [--dest DOSSIER]

**Non nécessaire par défaut.** Les schémas sont vendorisés dans le dépôt, sur la
base de la mention Apache 2.0 du document officiel du pack FNFE — voir
`skills/facturx-reception/schemas/NOTICE.md`, qui porte l'attribution et
cite aussi la mention EUPL divergente de l'en-tête des fichiers sources.

Ce script sert à qui préfère ne rien embarquer : distribution interne soumise à
sa propre politique, ou volonté de repartir des fichiers amont. La promesse
« aucun appel réseau » reste tenue — le téléchargement est une étape
d'installation explicite, lancée à la main une fois, jamais un appel au moment
où l'on traite une facture.

    --check   vérifie que les schémas attendus sont présents et n'écrit rien
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST_DEFAUT = os.path.join(REPO, "skills", "facturx-reception", "schemas")

PACK_FNFE = {
    "nom": "2026_08_04_FNFE_SCHEMATRONS_FR_CTC_V1.4.0.03",
    "url": "https://fnfe-mpe.org/wp-content/uploads/2026/08/"
           "2026_08_04_FNFE_SCHEMATRONS_FR_CTC_V1.4.0.03.zip",
    "licence": "Apache 2.0 (déclarée page 8 du PDF du pack ; voir NOTICE.md)",
}

# Profil → (dossier du pack, fichiers à extraire vers schemas/fnfe/<profil>/)
FNFE_PROFILS = {
    "BASICWL": "FACTUR-X_BASIC-WL",
    "EN16931": "FACTUR-X_EN16931",
    "EXTENDED": "FACTUR-X_EXTENDED",
}

XSLT_COMMUNS = ("BR-FR-Flux2-Schematron-CII.xslt",
                "BR-FR-Flux2-Schematron-CII_WARNING.xslt")

# Les XSD viennent d'Akretion (BSD-3-Clause), pas du pack FNFE : provenance
# unique et licence redistribuable sans réserve.
AKRETION_RAW = ("https://raw.githubusercontent.com/akretion/factur-x/master/"
                "src/facturx/xsd_and_schematron")
AKRETION_PROFILS = {
    "MINIMUM": ("facturx-minimum", "1.09"),
    "BASIC": ("facturx-basic", "1.09"),
    "BASICWL": ("facturx-basicwl", "1.09"),
    "EN16931": ("facturx-en16931", "1.09"),
    "EXTENDED": ("facturx-extended", "1.09"),
}
MODULES_XSD = ("QualifiedDataType_100",
               "ReusableAggregateBusinessInformationEntity_100",
               "UnqualifiedDataType_100")


def attendus(dest: str) -> list[str]:
    """Chemins que le script d'extraction exige pour fonctionner."""
    chemins = []
    for profil in AKRETION_PROFILS:
        chemins.append(os.path.join(dest, "factur-x", profil,
                                    "Factur-X_%s.xsd" % profil))
    for profil, entree in FNFE_PROFILS.items():
        for nom in XSLT_COMMUNS + ("%s.xslt" % entree, "%s_codedb.xml" % entree):
            chemins.append(os.path.join(dest, "fnfe", profil, nom))
    chemins.append(os.path.join(dest, "manifest.json"))
    return chemins


def verifier(dest: str) -> int:
    manquants = [c for c in attendus(dest) if not os.path.isfile(c)]
    for c in manquants:
        print("  manquant : %s" % os.path.relpath(c, REPO))
    if manquants:
        print("\n%d fichier(s) manquant(s). Relancer sans --check pour les "
              "télécharger." % len(manquants))
        return 1
    print("Tous les schémas attendus sont présents (%d fichiers)."
          % len(attendus(dest)))
    return 0


def telecharger(url: str) -> bytes:
    # Import local : le script d'extraction, lui, n'importe jamais le réseau.
    from urllib.request import urlopen
    with urlopen(url, timeout=300) as reponse:  # noqa: S310 — URL en dur
        return reponse.read()


def poser(chemin: str, donnees: bytes) -> None:
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "wb") as sortie:
        sortie.write(donnees)
    print("  %-58s %s" % (os.path.relpath(chemin, REPO),
                          hashlib.sha256(donnees).hexdigest()[:12]))


def recuperer_fnfe(dest: str) -> None:
    print("Pack FNFE — %s" % PACK_FNFE["url"])
    print("Licence : %s\n" % PACK_FNFE["licence"])
    archive = zipfile.ZipFile(io.BytesIO(telecharger(PACK_FNFE["url"])))
    racine = "%s/Factur-X_1.09.2" % PACK_FNFE["nom"]
    for profil, entree in FNFE_PROFILS.items():
        for nom in XSLT_COMMUNS + ("%s.xslt" % entree, "%s_codedb.xml" % entree):
            membre = "%s/%s/2xslt/%s" % (racine, profil, nom)
            poser(os.path.join(dest, "fnfe", profil, nom), archive.read(membre))


def recuperer_xsd(dest: str) -> None:
    print("\nXSD Factur-X — akretion/factur-x, BSD-3-Clause\n")
    from urllib.parse import quote
    for profil, (dossier, version) in AKRETION_PROFILS.items():
        fichiers = ["Factur-X_%s.xsd" % profil]
        for module in MODULES_XSD:
            # EXTENDED : un module est livré en 1.09.2 par la source amont.
            v = "1.09.2" if (profil == "EXTENDED" and module.startswith("Reusable")) \
                else version
            fichiers.append("Factur-X_%s_%s_urn_un_unece_uncefact_data_standard_%s.xsd"
                            % (v, profil, module))
        for nom in fichiers:
            url = "%s/%s/%s" % (AKRETION_RAW, dossier, quote(nom))
            poser(os.path.join(dest, "factur-x", profil, nom), telecharger(url))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Télécharge les schémas Factur-X et FNFE au lieu de les "
                    "embarquer (option d'installation ; non nécessaire par défaut).")
    parser.add_argument("--check", action="store_true",
                        help="vérifie la présence des schémas, n'écrit rien")
    parser.add_argument("--dest", default=DEST_DEFAUT,
                        help="dossier de destination (défaut : schemas/ de la skill)")
    args = parser.parse_args(argv)

    if args.check:
        return verifier(args.dest)

    print("Ce script n'est pas nécessaire dans l'état actuel du dépôt : les "
          "schémas y sont vendorisés.\nIl sert à qui préfère ne rien embarquer. "
          "Voir schemas/NOTICE.md.\n")
    recuperer_fnfe(args.dest)
    recuperer_xsd(args.dest)

    manifeste = os.path.join(args.dest, "manifest.json")
    if os.path.isfile(manifeste):
        with open(manifeste, encoding="utf-8") as entree:
            json.load(entree)  # simple contrôle de lisibilité
        print("\nmanifest.json conservé tel quel : il décrit la correspondance "
              "profil → schémas, que ce script ne modifie pas.")
    else:
        print("\nATTENTION : manifest.json absent. Le script d'extraction ne "
              "peut pas fonctionner sans lui.", file=sys.stderr)
        return 1

    print("\nTerminé. Vérifier avec : python3 scripts/fetch_schemas.py --check")
    return 0


if __name__ == "__main__":
    sys.exit(main())

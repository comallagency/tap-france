#!/usr/bin/env python3
"""Extraction et validation d'une facture Factur-X (PDF/A-3 + XML CII embarqué).

Usage :
    python3 scripts/facturx_extract.py <chemin.pdf> [--no-validate] [--json-only]

    --no-validate   n'exécute aucune passe de validation (extraction seule)
    --json-only     n'écrit rien sur stderr (stdout reste inchangé)

Sortie : un unique objet JSON sur stdout, toujours.
Code 0 : le script a fait son travail, y compris si la facture est non conforme.
Code 1 : le script n'a pas pu faire son travail (fichier absent, illisible, non-PDF).

Le script produit des faits. Il ne lit jamais la couche texte du PDF, ne fait
jamais d'OCR, ne devine jamais une valeur absente. Aucun appel réseau, aucune
écriture disque, aucune variable d'environnement requise.

Référence normative : CONTRAT-facturx-reception.md
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

SCHEMA_VERSION = "1.0"

# Calendrier officiel de la réforme française, lu dans les en-têtes des deux
# schematrons jumeaux du pack FNFE FR CTC :
#
#   BR-FR-Flux2-Schematron-CII.sch
#     Mode "FATAL"   — APPLICABLE EN RECEPTION LE 1ER SEPTEMBRE 2026
#   BR-FR-Flux2-Schematron-CII_WARNING.sch
#     Mode "WARNING" — APPLICABLE EN RECEPTION DES LA PUBLICATION
#                      ET JUSQU'AU SEPTEMBRE 2026 AU PLUS TARD
#
# Les deux fichiers portent exactement le même jeu de règles ; seule la date
# d'application les distingue. La sévérité des constatations BR-FR en découle,
# et reste donc lue dans la source — pas décidée par nous.
BASCULE_REFORME_FR = "2026-09-01"

_SKILL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
# Les schémas sont téléchargés à l'installation ; le manifeste, lui, fait partie
# de la skill. Il vit sous assets/ parce qu'Hermes n'embarque que les dossiers
# references/, templates/, scripts/, assets/ et examples/ — un manifeste rangé
# ailleurs ne serait jamais installé.
SCHEMAS_DIR = os.path.join(_SKILL, "schemas")
MANIFEST = os.path.join(_SKILL, "assets", "manifest.json")

# --------------------------------------------------------------------------
# Espaces de noms CII
# --------------------------------------------------------------------------

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:"
           "ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
    "svrl": "http://purl.oclc.org/dsdl/svrl",
}
URI_TO_PREFIX = {v: k for k, v in NS.items() if k != "svrl"}

CII_ROOT = "{%s}CrossIndustryInvoice" % NS["rsm"]

# --------------------------------------------------------------------------
# Tables de correspondance (§5 du contrat, et listes de codes officielles)
# --------------------------------------------------------------------------

PROFILE_LABELS = {
    "urn:factur-x.eu:1p0:minimum": "MINIMUM",
    "urn:factur-x.eu:1p0:basicwl": "BASIC WL",
    "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic": "BASIC",
    "urn:cen.eu:en16931:2017": "EN 16931",
    "urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended": "EXTENDED",
}

# UNTDID 1001 — sous-ensemble autorisé par Factur-X / la réforme française.
DOCUMENT_TYPE_LABELS = {
    "71": "Demande de paiement",
    "80": "Facture de débit sur consignation",
    "82": "Facture de régularisation métrée",
    "84": "Facture de solde de consignation",
    "102": "Facture d'affacturage",
    "130": "Facture pro forma",
    "202": "Facture de situation (BTP)",
    "203": "Facture de situation provisoire (BTP)",
    "204": "Facture de situation définitive (BTP)",
    "211": "Facture intermédiaire",
    "218": "Facture de solde final",
    "219": "Facture de retenue de garantie",
    "261": "Avoir d'autofacturation",
    "262": "Avoir d'affacturage",
    "295": "Facture de retenue",
    "296": "Avoir de retenue",
    "308": "Avoir de remise différée",
    "325": "Facture proforma partielle",
    "326": "Facture partielle",
    "331": "Facture commerciale incluant un décompte de retour d'emballages",
    "380": "Facture commerciale",
    "381": "Avoir",
    "382": "Facture de commission",
    "383": "Facture de débit",
    "384": "Facture rectificative",
    "385": "Facture consolidée",
    "386": "Facture d'acompte",
    "387": "Facture de location",
    "388": "Facture fiscale",
    "389": "Autofacturation",
    "390": "Facture de recouvrement",
    "393": "Facture d'affacturage",
    "394": "Facture de crédit-bail",
    "395": "Facture de consignation",
    "396": "Avoir d'affacturage",
    "420": "Avoir de surestarie",
    "456": "Avis de débit",
    "457": "Avis de crédit",
    "527": "Avis de débit d'autofacturation",
    "532": "Facture de sous-traitance",
    "553": "Facture d'ajustement de contrat",
    "575": "Facture d'assureur",
    "623": "Facture de transitaire",
    "633": "Facture portuaire",
    "751": "Information de facture pour comptabilisation",
    "780": "Facture de fret",
    "817": "Facture de redevance",
    "870": "Facture consulaire",
    "875": "Facture partielle de construction",
    "876": "Facture partielle définitive de construction",
    "877": "Facture définitive de construction",
}

# UNTDID 4461 — moyens de paiement.
PAYMENT_MEANS_LABELS = {
    "1": "Instrument non défini",
    "10": "Espèces",
    "20": "Chèque",
    "30": "Virement",
    "31": "Virement de débit",
    "42": "Paiement sur compte bancaire",
    "48": "Carte bancaire",
    "49": "Prélèvement",
    "54": "Carte de crédit",
    "55": "Carte de débit",
    "57": "Ordre permanent",
    "58": "Virement SEPA",
    "59": "Prélèvement SEPA",
    "68": "Compensation en ligne",
    "97": "Compensation interne",
    "ZZZ": "Convention hors nomenclature",
}

# Libellés français des termes sémantiques EN 16931 les plus fréquemment
# cités par les assertions officielles. Sert uniquement à formuler en français
# un message dont le texte officiel est en anglais ; `raw` conserve l'original.
SEMANTIC_LABELS = {
    "BG-1": "note de facture",
    "BG-2": "informations de processus",
    "BG-3": "facture précédente référencée",
    "BG-4": "vendeur",
    "BG-5": "adresse postale du vendeur",
    "BG-6": "contact du vendeur",
    "BG-7": "acheteur",
    "BG-8": "adresse postale de l'acheteur",
    "BG-9": "contact de l'acheteur",
    "BG-10": "bénéficiaire du paiement",
    "BG-11": "représentant fiscal du vendeur",
    "BG-12": "adresse du représentant fiscal",
    "BG-13": "informations de livraison",
    "BG-14": "période de facturation",
    "BG-15": "adresse de livraison",
    "BG-16": "instructions de paiement",
    "BG-17": "virement",
    "BG-18": "carte de paiement",
    "BG-19": "prélèvement",
    "BG-20": "remise au niveau du document",
    "BG-21": "charge au niveau du document",
    "BG-22": "totaux du document",
    "BG-23": "ventilation de TVA",
    "BG-24": "pièce jointe",
    "BG-25": "ligne de facture",
    "BG-26": "période de facturation de la ligne",
    "BG-27": "remise au niveau de la ligne",
    "BG-28": "charge au niveau de la ligne",
    "BG-29": "détail du prix",
    "BG-30": "informations de TVA de la ligne",
    "BG-31": "informations sur l'article",
    "BT-1": "numéro de facture",
    "BT-2": "date d'émission",
    "BT-3": "code type de facture",
    "BT-5": "devise de la facture",
    "BT-6": "devise de comptabilisation de la TVA",
    "BT-7": "date d'exigibilité de la TVA",
    "BT-8": "code de date d'exigibilité de la TVA",
    "BT-9": "date d'échéance",
    "BT-10": "référence acheteur",
    "BT-11": "référence du projet",
    "BT-12": "référence du contrat",
    "BT-13": "référence de la commande",
    "BT-14": "référence du bon de commande du vendeur",
    "BT-15": "référence de l'avis de réception",
    "BT-16": "référence du bon de livraison",
    "BT-17": "référence de l'appel d'offres",
    "BT-18": "identifiant de l'objet facturé",
    "BT-19": "référence de comptabilisation de l'acheteur",
    "BT-20": "conditions de paiement",
    "BT-21": "code du sujet de la note",
    "BT-22": "note de facture",
    "BT-23": "identifiant du mode de facturation",
    "BT-24": "identifiant de la spécification (profil)",
    "BT-25": "numéro de la facture précédente",
    "BT-26": "date de la facture précédente",
    "BT-27": "nom du vendeur",
    "BT-28": "nom commercial du vendeur",
    "BT-29": "identifiant du vendeur",
    "BT-30": "identifiant légal du vendeur",
    "BT-31": "numéro de TVA du vendeur",
    "BT-32": "identifiant fiscal local du vendeur",
    "BT-33": "informations légales complémentaires du vendeur",
    "BT-34": "adresse électronique du vendeur",
    "BT-35": "adresse du vendeur (ligne 1)",
    "BT-37": "commune du vendeur",
    "BT-38": "code postal du vendeur",
    "BT-40": "pays du vendeur",
    "BT-44": "nom de l'acheteur",
    "BT-45": "nom commercial de l'acheteur",
    "BT-46": "identifiant de l'acheteur",
    "BT-47": "identifiant légal de l'acheteur",
    "BT-48": "numéro de TVA de l'acheteur",
    "BT-49": "adresse électronique de l'acheteur",
    "BT-50": "adresse de l'acheteur (ligne 1)",
    "BT-52": "commune de l'acheteur",
    "BT-53": "code postal de l'acheteur",
    "BT-55": "pays de l'acheteur",
    "BT-59": "nom du bénéficiaire du paiement",
    "BT-60": "identifiant du bénéficiaire du paiement",
    "BT-61": "identifiant légal du bénéficiaire du paiement",
    "BT-63": "numéro de TVA du représentant fiscal",
    "BT-70": "nom du lieu de livraison",
    "BT-72": "date de livraison effective",
    "BT-73": "début de la période de facturation",
    "BT-74": "fin de la période de facturation",
    "BT-81": "code du moyen de paiement",
    "BT-82": "libellé du moyen de paiement",
    "BT-83": "référence de paiement",
    "BT-84": "identifiant du compte de paiement (IBAN)",
    "BT-85": "nom du titulaire du compte de paiement",
    "BT-86": "identifiant du prestataire de services de paiement (BIC)",
    "BT-89": "identifiant du mandat de prélèvement",
    "BT-90": "identifiant créancier du vendeur",
    "BT-91": "compte débité",
    "BT-92": "montant de la remise au niveau du document",
    "BT-93": "base de la remise au niveau du document",
    "BT-94": "pourcentage de la remise au niveau du document",
    "BT-95": "code de catégorie de TVA de la remise",
    "BT-96": "taux de TVA de la remise",
    "BT-97": "motif de la remise",
    "BT-98": "code du motif de la remise",
    "BT-99": "montant de la charge au niveau du document",
    "BT-100": "base de la charge au niveau du document",
    "BT-101": "pourcentage de la charge au niveau du document",
    "BT-102": "code de catégorie de TVA de la charge",
    "BT-103": "taux de TVA de la charge",
    "BT-104": "motif de la charge",
    "BT-105": "code du motif de la charge",
    "BT-106": "total HT des lignes",
    "BT-107": "total des remises au niveau du document",
    "BT-108": "total des charges au niveau du document",
    "BT-109": "total HT de la facture",
    "BT-110": "total de la TVA",
    "BT-111": "total de la TVA en devise de comptabilisation",
    "BT-112": "total TTC de la facture",
    "BT-113": "montant déjà payé",
    "BT-114": "arrondi",
    "BT-115": "net à payer",
    "BT-116": "base soumise à TVA de la catégorie",
    "BT-117": "montant de TVA de la catégorie",
    "BT-118": "code de catégorie de TVA",
    "BT-119": "taux de TVA de la catégorie",
    "BT-120": "motif d'exonération de TVA",
    "BT-121": "code du motif d'exonération de TVA",
    "BT-122": "référence de la pièce jointe",
    "BT-126": "identifiant de la ligne de facture",
    "BT-127": "note de la ligne de facture",
    "BT-128": "identifiant de l'objet de la ligne",
    "BT-129": "quantité facturée",
    "BT-130": "unité de la quantité facturée",
    "BT-131": "montant net de la ligne",
    "BT-132": "référence de ligne de commande de l'acheteur",
    "BT-133": "référence de comptabilisation de la ligne",
    "BT-134": "début de la période de facturation de la ligne",
    "BT-135": "fin de la période de facturation de la ligne",
    "BT-136": "montant de la remise de ligne",
    "BT-141": "montant de la charge de ligne",
    "BT-146": "prix unitaire net",
    "BT-147": "remise sur le prix unitaire",
    "BT-148": "prix unitaire brut",
    "BT-149": "quantité de base du prix",
    "BT-151": "code de catégorie de TVA de la ligne",
    "BT-152": "taux de TVA de la ligne",
    "BT-153": "désignation de l'article",
    "BT-154": "description de l'article",
    "BT-155": "référence article du vendeur",
    "BT-156": "référence article de l'acheteur",
    "BT-157": "identifiant standard de l'article",
    "BT-158": "identifiant de classification de l'article",
    "BT-159": "pays d'origine de l'article",
}

# Texte officiel EN 16931 des règles d'arithmétique vérifiées par la passe
# `coherence`. Conservé en anglais dans `raw`, pour traçabilité.
COHERENCE_RULES = {
    "BR-CO-10": "[BR-CO-10]-Sum of Invoice line net amount (BT-106) = "
                "Σ Invoice line net amount (BT-131).",
    "BR-CO-13": "[BR-CO-13]-Invoice total amount without VAT (BT-109) = "
                "Σ Invoice line net amount (BT-131) - Sum of allowances on document level "
                "(BT-107) + Sum of charges on document level (BT-108).",
    "BR-CO-14": "[BR-CO-14]-Invoice total VAT amount (BT-110) = "
                "Σ VAT category tax amount (BT-117).",
    "BR-CO-15": "[BR-CO-15]-Invoice total amount with VAT (BT-112) = "
                "Invoice total amount without VAT (BT-109) + Invoice total VAT amount (BT-110).",
    "BR-CO-16": "[BR-CO-16]-Amount due for payment (BT-115) = "
                "Invoice total amount with VAT (BT-112) - Paid amount (BT-113) + "
                "Rounding amount (BT-114).",
    "BR-CO-17": "[BR-CO-17]-VAT category tax amount (BT-117) = "
                "VAT category taxable amount (BT-116) x (VAT category rate (BT-119) / 100), "
                "rounded to two decimals.",
}

# Traductions françaises curatées des assertions anglaises les plus courantes du
# validateur officiel de profil. Toute règle absente de cette table reçoit un
# message français construit mécaniquement à partir de SEMANTIC_LABELS.
CURATED_FR = {
    "BR-01": "La facture doit porter un identifiant de spécification (BT-24) "
             "indiquant le profil Factur-X utilisé.",
    "BR-02": "La facture doit porter un numéro de facture (BT-1).",
    "BR-03": "La facture doit porter une date d'émission (BT-2).",
    "BR-04": "La facture doit porter un code de type de facture (BT-3).",
    "BR-05": "La facture doit indiquer sa devise (BT-5).",
    "BR-06": "Le nom du vendeur (BT-27) est obligatoire.",
    "BR-07": "Le nom de l'acheteur (BT-44) est obligatoire.",
    "BR-08": "L'adresse postale du vendeur (BG-5) est obligatoire.",
    "BR-09": "Le pays du vendeur (BT-40) est obligatoire.",
    "BR-10": "L'adresse postale de l'acheteur (BG-8) est obligatoire.",
    "BR-11": "Le pays de l'acheteur (BT-55) est obligatoire.",
    "BR-12": "Le total HT des lignes (BT-106) est obligatoire.",
    "BR-13": "Le total HT de la facture (BT-109) est obligatoire.",
    "BR-14": "Le total TTC de la facture (BT-112) est obligatoire.",
    "BR-15": "Le net à payer (BT-115) est obligatoire.",
    "BR-16": "La facture doit comporter au moins une ligne (BG-25).",
    "BR-21": "Chaque ligne de facture doit porter un identifiant (BT-126).",
    "BR-22": "Chaque ligne de facture doit indiquer une quantité facturée (BT-129).",
    "BR-23": "Chaque ligne de facture doit indiquer l'unité de la quantité facturée (BT-130).",
    "BR-24": "Chaque ligne de facture doit indiquer son montant net (BT-131).",
    "BR-25": "Chaque ligne de facture doit désigner l'article facturé (BT-153).",
    "BR-26": "Chaque ligne de facture doit indiquer un prix unitaire net (BT-146).",
    "BR-27": "Le prix unitaire net (BT-146) ne peut pas être négatif.",
    "BR-28": "Le prix unitaire brut (BT-148) ne peut pas être négatif.",
    "BR-45": "Chaque ventilation de TVA (BG-23) doit indiquer la base soumise à TVA (BT-116).",
    "BR-46": "Chaque ventilation de TVA (BG-23) doit indiquer le montant de TVA (BT-117).",
    "BR-47": "Chaque ventilation de TVA (BG-23) doit indiquer un code de catégorie de TVA (BT-118).",
    "BR-48": "Chaque ventilation de TVA (BG-23) doit indiquer un taux de TVA (BT-119), "
             "sauf si la facture n'est pas soumise à la TVA.",
    "BR-52": "Chaque pièce jointe (BG-24) doit porter une référence (BT-122).",
    "BR-53": "Si une devise de comptabilisation de la TVA (BT-6) est indiquée, "
             "le total de TVA dans cette devise (BT-111) doit être fourni.",
    "BR-61": "Si le moyen de paiement est un virement, l'identifiant du compte "
             "de paiement (BT-84) est obligatoire.",
    "BR-62": "Le vendeur doit porter une adresse électronique (BT-34) assortie "
             "de son schéma d'identification.",
    "BR-63": "L'acheteur doit porter une adresse électronique (BT-49) assortie "
             "de son schéma d'identification.",
    "BR-64": "L'identifiant standard de l'article (BT-157) doit être assorti "
             "de son schéma d'identification.",
    "BR-65": "L'identifiant de classification de l'article (BT-158) doit être "
             "assorti de son schéma d'identification.",
    "BR-CO-03": "La date d'exigibilité de la TVA (BT-7) et son code (BT-8) "
                "s'excluent mutuellement.",
    "BR-CO-04": "Chaque ligne de facture doit porter un code de catégorie de TVA (BT-151).",
    "BR-CO-05": "Le code du motif de remise (BT-98) et le motif de remise (BT-97) "
                "doivent indiquer la même chose.",
    "BR-CO-06": "Le code du motif de charge (BT-105) et le motif de charge (BT-104) "
                "doivent indiquer la même chose.",
    "BR-CO-09": "Un numéro de TVA doit être précédé du code pays de l'État membre "
                "qui l'a attribué.",
    "BR-CO-10": "Le total HT des lignes (BT-106) doit être égal à la somme des "
                "montants nets de ligne (BT-131).",
    "BR-CO-11": "Le total des remises au niveau du document (BT-107) doit être égal "
                "à la somme des remises document (BT-92).",
    "BR-CO-12": "Le total des charges au niveau du document (BT-108) doit être égal "
                "à la somme des charges document (BT-99).",
    "BR-CO-13": "Le total HT de la facture (BT-109) doit être égal au total HT des "
                "lignes (BT-106), diminué des remises document (BT-107) et augmenté "
                "des charges document (BT-108).",
    "BR-CO-14": "Le total de la TVA (BT-110) doit être égal à la somme des montants "
                "de TVA par catégorie (BT-117).",
    "BR-CO-15": "Le total TTC de la facture (BT-112) doit être égal au total HT "
                "(BT-109) augmenté du total de la TVA (BT-110).",
    "BR-CO-16": "Le net à payer (BT-115) doit être égal au total TTC (BT-112), "
                "diminué du montant déjà payé (BT-113) et augmenté de l'arrondi (BT-114).",
    "BR-CO-17": "Le montant de TVA d'une catégorie (BT-117) doit être égal à la base "
                "soumise à TVA (BT-116) multipliée par le taux (BT-119), arrondi "
                "à deux décimales.",
    "BR-CO-18": "La facture doit comporter au moins une ventilation de TVA (BG-23).",
    "BR-CO-19": "Une période de facturation (BG-14) doit porter une date de début "
                "(BT-73) ou une date de fin (BT-74).",
    "BR-CO-20": "Une période de facturation de ligne (BG-26) doit porter une date de "
                "début (BT-134) ou une date de fin (BT-135).",
    "BR-CO-21": "Une remise au niveau du document (BG-20) doit porter un motif (BT-97) "
                "ou un code de motif (BT-98).",
    "BR-CO-22": "Une charge au niveau du document (BG-21) doit porter un motif (BT-104) "
                "ou un code de motif (BT-105).",
    "BR-CO-23": "Une remise de ligne (BG-27) doit porter un motif ou un code de motif.",
    "BR-CO-24": "Une charge de ligne (BG-28) doit porter un motif ou un code de motif.",
    "BR-CO-25": "Si le net à payer est positif, la date d'échéance (BT-9) ou les "
                "conditions de paiement (BT-20) doivent être renseignées.",
    "BR-CO-26": "Le vendeur doit être identifiable : identifiant (BT-29), identifiant "
                "légal (BT-30) ou numéro de TVA (BT-31).",
    "BR-DEC-09": "Le total HT des lignes (BT-106) ne doit pas comporter plus de "
                 "deux décimales.",
    "BR-DEC-11": "Le total des remises au niveau du document (BT-107) ne doit pas "
                 "comporter plus de deux décimales.",
    "BR-DEC-12": "Le total des charges au niveau du document (BT-108) ne doit pas "
                 "comporter plus de deux décimales.",
    "BR-DEC-13": "Le total HT de la facture (BT-109) ne doit pas comporter plus de "
                 "deux décimales.",
    "BR-DEC-14": "Le total de la TVA (BT-110) ne doit pas comporter plus de "
                 "deux décimales.",
    "BR-DEC-15": "Le total TTC de la facture (BT-112) ne doit pas comporter plus de "
                 "deux décimales.",
    "BR-DEC-16": "Le montant déjà payé (BT-113) ne doit pas comporter plus de "
                 "deux décimales.",
    "BR-DEC-17": "L'arrondi (BT-114) ne doit pas comporter plus de deux décimales.",
    "BR-DEC-18": "Le net à payer (BT-115) ne doit pas comporter plus de deux décimales.",
    "BR-DEC-19": "La base soumise à TVA d'une catégorie (BT-116) ne doit pas comporter "
                 "plus de deux décimales.",
    "BR-DEC-20": "Le montant de TVA d'une catégorie (BT-117) ne doit pas comporter "
                 "plus de deux décimales.",
    "BR-DEC-23": "Le montant net d'une ligne (BT-131) ne doit pas comporter plus de "
                 "deux décimales.",
    "CII-SR-470": "Le compte de paiement doit être identifié par un IBAN ou par un "
                  "identifiant propriétaire (BT-84).",
    "PEPPOL-EN16931-R008": "La facture ne doit pas contenir d'élément vide.",
}

# Règles françaises de la réforme (BR-FR-*). Leur texte officiel est déjà en
# français, mais écrit pour un intégrateur : il cite des codes BT nus et des
# noms d'éléments XML. Ces reformulations disent au destinataire de la facture
# ce qui manque, où, et quoi demander à son fournisseur. `raw` conserve
# l'assertion officielle intacte.
CURATED_FR_REFORME = {
    "BR-FR-05_BT-22_PMT": (
        "La facture ne porte pas la mention obligatoire sur l'indemnité "
        "forfaitaire de 40 € pour frais de recouvrement, due entre "
        "professionnels en cas de retard de paiement. Elle doit figurer parmi "
        "les notes de la facture : à faire ajouter par votre fournisseur."),
    "BR-FR-05_BT-22_PMD": (
        "La facture ne porte pas la mention obligatoire sur les pénalités de "
        "retard de paiement (leur taux, ou le renvoi aux conditions générales "
        "de vente). Elle doit figurer parmi les notes de la facture : à faire "
        "ajouter par votre fournisseur."),
    "BR-FR-05_BT-22_AAB": (
        "La facture n'indique pas les conditions d'escompte en cas de paiement "
        "anticipé — ni, à défaut, qu'aucun escompte n'est accordé. L'une ou "
        "l'autre mention est obligatoire parmi les notes de la facture."),
    "BR-FR-08_BT-23": (
        "La facture ne précise pas son cas d'usage : le code qui dit s'il "
        "s'agit d'un dépôt direct, d'un mandat de facturation, d'une facture "
        "de solde, etc. La réforme française le rend obligatoire ; c'est le "
        "logiciel de facturation de votre fournisseur qui doit le renseigner."),
    "BR-FR-10_BT-30": (
        "Le numéro SIREN du vendeur est absent ou mal formé : la réforme "
        "française en exige un, composé d'exactement 9 chiffres. L'erreur la "
        "plus courante est d'avoir saisi le SIRET, qui en compte 14. À faire "
        "corriger par votre fournisseur."),
    "BR-FR-12_BT-49": (
        "L'adresse électronique de l'acheteur est absente. C'est l'identifiant "
        "auquel vous recevez vos factures électroniques — souvent votre SIREN, "
        "parfois une adresse dédiée — et la réforme l'exige pour acheminer la "
        "facture jusqu'à vous. Communiquez-le à votre fournisseur."),
    "BR-FR-13_BT-34": (
        "L'adresse électronique du vendeur est absente. C'est l'identifiant "
        "qui permet de reconnaître l'émetteur de la facture sur la plateforme, "
        "et la réforme l'exige. À faire renseigner par votre fournisseur dans "
        "son logiciel de facturation."),
    # Les quinze taux ci-dessous sont exactement ceux de la fonction
    # custom:is-valid-vat-rate du schematron officiel, Corse et DOM compris.
    # Les énumérer au complet évite de faire passer pour une anomalie une
    # facture corse ou ultramarine parfaitement régulière.
    "BR-FR-16_BT-119": (
        "Un taux de TVA du récapitulatif ne fait pas partie des taux que la "
        "réforme française autorise. Un taux hors liste vient le plus souvent "
        "d'une facture étrangère ; si l'émetteur est français, il est à faire "
        "corriger."),
    "BR-FR-16_BT-152": (
        "Le taux de TVA d'une ligne de facture ne fait pas partie des taux que "
        "la réforme française autorise. Un taux hors liste vient le plus "
        "souvent d'une facture étrangère ; si l'émetteur est français, il est "
        "à faire corriger."),
    "BR-FR-16_BT-96_BT-103": (
        "Le taux de TVA appliqué à une remise ou à une charge de la facture ne "
        "fait pas partie des taux que la réforme française autorise. Ce taux "
        "doit être l'un de ceux déjà employés par la facture ; à faire "
        "corriger par votre fournisseur."),
    "BR-FR-32-LEGALID": (
        "Un identifiant légal — celui du vendeur ou celui de l'acheteur, voir "
        "l'emplacement indiqué — est annoncé comme un SIREN mais ne comporte "
        "pas 9 chiffres. C'est presque toujours un SIRET de 14 chiffres saisi "
        "à sa place. À faire corriger par l'émetteur de la facture."),
}

# Énumération complète des taux acceptés par custom:is-valid-vat-rate. Placée
# en fin de message : le lecteur veut d'abord savoir quel taux a été refusé.
TAUX_TVA_AUTORISES = (
    "Taux admis : métropole 20 %, 10 %, 5,5 %, 2,1 %, 0 % ; Corse 13 %, 10 %, "
    "2,1 %, 0,9 % ; DOM 8,5 %, 2,1 %, 1,75 %, 1,05 % ; plus cinq taux plus "
    "anciens, 20,6 %, 19,6 %, 9,6 %, 9,2 % et 7 %.")


def _msg_taux(ou: str):
    """Message d'un taux de TVA refusé, la valeur d'abord, la liste ensuite."""
    def build(value, node):
        return ("Le taux de TVA « %s » %s ne fait pas partie des taux que la "
                "réforme française autorise. Un taux hors liste vient le plus "
                "souvent d'une facture étrangère ; si l'émetteur est français, "
                "il est à faire corriger. %s" % (value, ou, TAUX_TVA_AUTORISES))
    return build


def _compte(value: str) -> str:
    return "%d %s" % (len(value), "chiffres" if value.isdigit() else "caractères")


def _msg_siren(value, node):
    return ("Le SIREN du vendeur doit comporter exactement 9 chiffres ; celui "
            "de cette facture en compte %s : « %s ». C'est presque toujours le "
            "SIRET, long de 14 chiffres, saisi à la place du SIREN. À faire "
            "corriger par votre fournisseur." % (_compte(value), value))


def _msg_legalid(value, node):
    partie = "Un identifiant légal"
    ancestor = node.getparent() if node is not None else None
    while ancestor is not None:
        tag = ancestor.tag
        if tag == "{%s}SellerTradeParty" % NS["ram"]:
            partie = "L'identifiant légal du vendeur"
            break
        if tag == "{%s}BuyerTradeParty" % NS["ram"]:
            partie = "L'identifiant légal de l'acheteur"
            break
        ancestor = ancestor.getparent()
    return ("%s est annoncé comme un SIREN mais en compte %s au lieu de 9 : "
            "« %s ». C'est presque toujours un SIRET, long de 14 chiffres, "
            "saisi à la place du SIREN. À faire corriger par l'émetteur de la "
            "facture." % (partie, _compte(value), value))


# Règles dont le message gagne à citer la valeur fautive. Le chemin relatif est
# repris à l'identique du `<let>` de la règle officielle, évalué depuis le nœud
# que le rapport SVRL désigne — jamais depuis une supposition. `None` désigne
# le nœud lui-même. Valeur non résolue ⇒ on retombe sur le message générique.
REFORME_AVEC_VALEUR = {
    "BR-FR-16_BT-119": ("ram:RateApplicablePercent",
                        _msg_taux("indiqué dans le récapitulatif de TVA")),
    "BR-FR-16_BT-152": ("ram:RateApplicablePercent",
                        _msg_taux("indiqué sur une ligne de facture")),
    "BR-FR-16_BT-96_BT-103": ("ram:RateApplicablePercent",
                              _msg_taux("appliqué à une remise ou à une charge")),
    "BR-FR-10_BT-30": ("rsm:SupplyChainTradeTransaction/"
                       "ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/"
                       "ram:SpecifiedLegalOrganization/ram:ID[@schemeID='0002']",
                       _msg_siren),
    "BR-FR-32-LEGALID": (None, _msg_legalid),
}

# Motifs mécaniques du validateur de profil Factur-X (famille FX-SCH-*),
# qui suit une formulation entièrement stéréotypée.
FX_CARDINALITY_PATTERNS = [
    (re.compile(r"^Element '([^']+)' must occur exactly (\d+) times?\.?$"),
     "L'élément « {0} » doit apparaître exactement {1} fois."),
    (re.compile(r"^Element '([^']+)' must occur at least (\d+) times?\.?$"),
     "L'élément « {0} » doit apparaître au moins {1} fois."),
    (re.compile(r"^Element '([^']+)' must occur at most (\d+) times?\.?$"),
     "L'élément « {0} » doit apparaître au plus {1} fois."),
    (re.compile(r"^Element '([^']+)' must not occur\.?$"),
     "L'élément « {0} » ne doit pas être présent."),
    (re.compile(r"^Attribute '?@?([^'\s]+)'? marked as not used in the given context\.?$"),
     "L'attribut « {0} » n'est pas utilisé dans ce contexte."),
]


# --------------------------------------------------------------------------
# Utilitaires
# --------------------------------------------------------------------------

class Unreadable(Exception):
    """Le script ne peut pas faire son travail : fichier absent ou illisible."""


def warn(msg: str) -> None:
    if not _QUIET:
        print(msg, file=sys.stderr)


_QUIET = False


def text_of(node) -> str | None:
    """Texte normalisé d'un nœud, ou None. Une chaîne vide vaut None."""
    if node is None:
        return None
    t = node.text
    if t is None:
        return None
    t = t.strip()
    return t or None


def first(root, path: str):
    found = root.findall(path, NS)
    return found[0] if found else None


def first_text(root, path: str) -> str | None:
    return text_of(first(root, path))


def to_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def iso_date(node) -> str | None:
    """Convertit un udt:DateTimeString en date ISO. Jamais de devinette."""
    if node is None:
        return None
    raw = text_of(node)
    if raw is None:
        return None
    fmt = (node.get("format") or "").strip()
    if fmt == "102" and re.fullmatch(r"\d{8}", raw):
        return "%s-%s-%s" % (raw[0:4], raw[4:6], raw[6:8])
    if fmt == "610" and re.fullmatch(r"\d{6}", raw):
        return "%s-%s" % (raw[0:4], raw[4:6])
    if fmt == "616" and re.fullmatch(r"\d{6}", raw):
        return None  # semaine ISO : pas une date, on ne l'invente pas
    if not fmt and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    return None


def simplify_location(loc: str | None) -> str | None:
    """Transforme un chemin SVRL verbeux en XPath préfixé lisible.

    /*:CrossIndustryInvoice[namespace-uri()='urn:…:100'][1]/… devient
    /rsm:CrossIndustryInvoice/…
    """
    if not loc:
        return None
    out = []
    for step in loc.split("/"):
        if not step:
            continue
        m = re.match(r"^\*:([\w.-]+)\[namespace-uri\(\)='([^']+)'\](.*)$", step)
        if m:
            name, uri, rest = m.groups()
            prefix = URI_TO_PREFIX.get(uri)
            step = "%s:%s" % (prefix, name) if prefix else name
            idx = re.match(r"^\[(\d+)\]$", rest.strip())
            if idx and idx.group(1) != "1":
                step += "[%s]" % idx.group(1)
        out.append(step)
    return "/" + "/".join(out) if out else None


SVRL_STEP = re.compile(
    r"^\*:([\w.-]+)\[namespace-uri\(\)='([^']+)'\](?:\[(\d+)\])?$")


def resolve_location(root, loc: str | None):
    """Élément désigné par un chemin SVRL, ou None.

    Aucune approximation : si un pas ne se résout pas exactement, on renonce
    plutôt que de retourner un nœud voisin. Un message qui citerait la mauvaise
    valeur serait pire qu'un message générique.
    """
    if not loc or root is None:
        return None
    node = None
    for step in loc.split("/"):
        if not step:
            continue
        match = SVRL_STEP.match(step)
        if not match:
            return None
        name, uri, index = match.groups()
        tag = "{%s}%s" % (uri, name)
        position = int(index) if index else 1
        if node is None:
            if root.tag != tag or position != 1:
                return None
            node = root
            continue
        siblings = [child for child in node if child.tag == tag]
        if len(siblings) < position:
            return None
        node = siblings[position - 1]
    return node


def faulty_value(rule_id: str | None, node):
    """Valeur mise en cause par la règle, telle qu'écrite dans le XML, ou None."""
    if rule_id is None or node is None:
        return None, None
    entry = REFORME_AVEC_VALEUR.get(rule_id)
    if entry is None:
        return None, None
    path, build = entry
    target = node if path is None else first(node, path)
    return text_of(target), build


def strip_rule_prefix(text: str) -> str:
    """Retire le préfixe redondant d'identifiant de règle d'un message."""
    text = re.sub(r"^\s*\[[^\]]+\]\s*-?\s*", "", text)
    text = re.sub(r"^\s*(BR|CII|FX|PEPPOL)[A-Z0-9_.-]*(\s*/\s*B[TG]-[\w-]+)?\s*:\s*", "",
                  text)
    return text.strip()


def semantic_terms(text: str) -> list[str]:
    """Codes BT-/BG- cités par une assertion, dans l'ordre d'apparition."""
    seen = []
    for code in re.findall(r"\b(B[TG]-\d+(?:-\d+)?)\b", text):
        if code not in seen:
            seen.append(code)
    return seen


# --------------------------------------------------------------------------
# Détection de la pièce jointe (§5)
# --------------------------------------------------------------------------

XML_MIMES = ("xml",)
ACCEPTED_RELATIONSHIPS = ("/Data", "/Alternative")


def _norm_relationship(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s if s.startswith("/") else "/" + s


def _norm_mime(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lstrip("/")
    # Un nom PDF échappe les caractères réservés : « application/xml » s'écrit
    # « /application#2Fxml ». On rétablit la forme lisible.
    s = re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), s)
    return s.lower() or None


def _is_xml_mime(mime: str | None) -> bool:
    return bool(mime) and any(mime.endswith(suffix) for suffix in XML_MIMES)


def collect_attachments(reader) -> list[dict]:
    """Toutes les pièces jointes du PDF, via /Root/AF puis /Names/EmbeddedFiles.

    Le nom du fichier n'est jamais un critère de détection, seulement une
    information reportée.
    """
    found = []
    seen = set()

    def add(name, relationship, mime, data):
        if data is None:
            return
        key = (name, len(data), hashlib.sha256(data).hexdigest())
        if key in seen:
            return
        seen.add(key)
        found.append({
            "name": name,
            "af_relationship": _norm_relationship(relationship),
            "mime": _norm_mime(mime),
            "data": data,
        })

    def read_filespec(spec, relationship=None):
        try:
            spec = spec.get_object()
        except Exception:
            return
        name = spec.get("/UF") or spec.get("/F")
        name = str(name) if name is not None else None
        rel = relationship if relationship is not None else spec.get("/AFRelationship")
        ef = spec.get("/EF")
        if ef is None:
            return
        try:
            ef = ef.get_object()
        except Exception:
            return
        for key in ("/UF", "/F"):
            stream = ef.get(key)
            if stream is None:
                continue
            try:
                stream = stream.get_object()
                data = stream.get_data()
            except Exception:
                continue
            add(name, rel, stream.get("/Subtype"), data)
            return

    root = reader.trailer.get("/Root")
    if root is None:
        return found
    try:
        root = root.get_object()
    except Exception:
        return found

    af = root.get("/AF")
    if af is not None:
        try:
            for spec in af.get_object():
                read_filespec(spec)
        except Exception as exc:
            warn("avertissement : /AF illisible (%s)" % exc)

    names = root.get("/Names")
    if names is not None:
        try:
            embedded = names.get_object().get("/EmbeddedFiles")
        except Exception:
            embedded = None
        if embedded is not None:
            def walk(node, depth=0):
                if depth > 32:
                    return
                try:
                    node = node.get_object()
                except Exception:
                    return
                kids = node.get("/Kids")
                if kids is not None:
                    for kid in kids:
                        walk(kid, depth + 1)
                entries = node.get("/Names")
                if entries is not None:
                    entries = list(entries)
                    for i in range(1, len(entries), 2):
                        read_filespec(entries[i])
            try:
                walk(embedded)
            except Exception as exc:
                warn("avertissement : /Names/EmbeddedFiles illisible (%s)" % exc)
    return found


def looks_like_cii(data: bytes) -> bool:
    from lxml import etree
    try:
        root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False,
                                                            no_network=True))
    except Exception:
        return False
    return root.tag == CII_ROOT


def detect(attachments: list[dict]) -> tuple[dict | None, dict]:
    """Cascade de détection du §5. Retourne (pièce jointe retenue, bloc detection)."""
    notes: list[str] = []

    standard = [a for a in attachments
                if a["af_relationship"] in ACCEPTED_RELATIONSHIPS
                and _is_xml_mime(a["mime"])]
    if standard:
        cii = [a for a in standard if looks_like_cii(a["data"])]
        chosen = cii[0] if cii else standard[0]
        if len(standard) > 1:
            notes.append(
                "%d pièces jointes XML candidates ; celle nommée « %s » a été retenue."
                % (len(standard), chosen["name"]))
        return chosen, {
            "method": "standard",
            "attachment_name": chosen["name"],
            "af_relationship": chosen["af_relationship"],
            "notes": notes,
        }

    fallback = [a for a in attachments if looks_like_cii(a["data"])]
    if fallback:
        chosen = fallback[0]
        notes.append(
            "Pièce jointe détectée en repli : AFRelationship=%s et type MIME=%s ne "
            "respectent pas la convention Factur-X, mais la racine du XML est bien "
            "rsm:CrossIndustryInvoice."
            % (chosen["af_relationship"] or "absent", chosen["mime"] or "absent"))
        return chosen, {
            "method": "fallback",
            "attachment_name": chosen["name"],
            "af_relationship": chosen["af_relationship"],
            "notes": notes,
        }

    return None, {
        "method": None,
        "attachment_name": None,
        "af_relationship": None,
        "notes": notes,
    }


# --------------------------------------------------------------------------
# Extraction des données de facture (§4)
# --------------------------------------------------------------------------

def party(node) -> dict:
    """Vendeur ou acheteur. siren/siret/vat_id/legal_id extraits séparément."""
    out = {
        "name": None, "siren": None, "siret": None, "vat_id": None,
        "legal_id": None, "country": None, "electronic_address": None,
    }
    if node is None:
        return out

    out["name"] = first_text(node, "ram:Name")
    out["country"] = first_text(node, "ram:PostalTradeAddress/ram:CountryID")
    out["legal_id"] = first_text(node, "ram:SpecifiedLegalOrganization/ram:ID")
    out["electronic_address"] = first_text(
        node, "ram:URIUniversalCommunication/ram:URIID")

    for id_node in (node.findall("ram:SpecifiedLegalOrganization/ram:ID", NS)
                    + node.findall("ram:ID", NS)
                    + node.findall("ram:GlobalID", NS)):
        scheme = (id_node.get("schemeID") or "").strip()
        value = text_of(id_node)
        if value is None:
            continue
        if scheme == "0002" and out["siren"] is None and re.fullmatch(r"\d{9}", value):
            out["siren"] = value
        elif scheme == "0009" and out["siret"] is None and re.fullmatch(r"\d{14}", value):
            out["siret"] = value

    for tax in node.findall("ram:SpecifiedTaxRegistration/ram:ID", NS):
        if (tax.get("schemeID") or "").strip().upper() == "VA":
            out["vat_id"] = text_of(tax)
            break
    return out


def extract_lines(transaction) -> list[dict]:
    lines = []
    for item in transaction.findall("ram:IncludedSupplyChainTradeLineItem", NS):
        settlement = first(item, "ram:SpecifiedLineTradeSettlement")
        agreement = first(item, "ram:SpecifiedLineTradeAgreement")
        delivery = first(item, "ram:SpecifiedLineTradeDelivery")
        quantity_node = (first(delivery, "ram:BilledQuantity")
                         if delivery is not None else None)
        tax = (first(settlement, "ram:ApplicableTradeTax")
               if settlement is not None else None)
        period = (first(settlement, "ram:BillingSpecifiedPeriod")
                  if settlement is not None else None)
        lines.append({
            "id": first_text(item, "ram:AssociatedDocumentLineDocument/ram:LineID"),
            "note": first_text(
                item, "ram:AssociatedDocumentLineDocument/ram:IncludedNote/ram:Content"),
            "name": first_text(item, "ram:SpecifiedTradeProduct/ram:Name"),
            "description": first_text(
                item, "ram:SpecifiedTradeProduct/ram:Description"),
            "seller_id": first_text(
                item, "ram:SpecifiedTradeProduct/ram:SellerAssignedID"),
            "buyer_id": first_text(
                item, "ram:SpecifiedTradeProduct/ram:BuyerAssignedID"),
            "global_id": first_text(item, "ram:SpecifiedTradeProduct/ram:GlobalID"),
            "quantity": text_of(quantity_node),
            "unit": quantity_node.get("unitCode") if quantity_node is not None else None,
            "unit_price": (first_text(
                agreement,
                "ram:NetPriceProductTradePrice/ram:ChargeAmount")
                if agreement is not None else None),
            "gross_unit_price": (first_text(
                agreement,
                "ram:GrossPriceProductTradePrice/ram:ChargeAmount")
                if agreement is not None else None),
            "net": (first_text(
                settlement,
                "ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount")
                if settlement is not None else None),
            "vat_category": (first_text(tax, "ram:CategoryCode")
                             if tax is not None else None),
            "vat_rate": (first_text(tax, "ram:RateApplicablePercent")
                         if tax is not None else None),
            "billing_period": {
                "start": iso_date(first(period, "ram:StartDateDateTime/udt:DateTimeString"))
                if period is not None else None,
                "end": iso_date(first(period, "ram:EndDateDateTime/udt:DateTimeString"))
                if period is not None else None,
            },
        })
    return lines


def extract_invoice(root) -> dict:
    document = first(root, "rsm:ExchangedDocument")
    transaction = first(root, "rsm:SupplyChainTradeTransaction")
    agreement = first(transaction, "ram:ApplicableHeaderTradeAgreement") \
        if transaction is not None else None
    settlement = first(transaction, "ram:ApplicableHeaderTradeSettlement") \
        if transaction is not None else None

    type_code = first_text(document, "ram:TypeCode") if document is not None else None
    issue = first(document, "ram:IssueDateTime/udt:DateTimeString") \
        if document is not None else None

    totals_node = first(settlement,
                        "ram:SpecifiedTradeSettlementHeaderMonetarySummation") \
        if settlement is not None else None
    period = first(settlement, "ram:BillingSpecifiedPeriod") \
        if settlement is not None else None
    terms = first(settlement, "ram:SpecifiedTradePaymentTerms") \
        if settlement is not None else None
    means = first(settlement, "ram:SpecifiedTradeSettlementPaymentMeans") \
        if settlement is not None else None

    means_code = first_text(means, "ram:TypeCode") if means is not None else None

    currency = first_text(settlement, "ram:InvoiceCurrencyCode") \
        if settlement is not None else None

    def total(name):
        if totals_node is None:
            return None
        nodes = totals_node.findall("ram:" + name, NS)
        if not nodes:
            return None
        # BT-110 et BT-111 partagent le nom TaxTotalAmount et ne se distinguent
        # que par @currencyID : on retient celui libellé dans la devise de la
        # facture, sans jamais convertir un montant.
        if len(nodes) > 1 and currency:
            for node in nodes:
                if (node.get("currencyID") or "").strip() == currency:
                    return text_of(node)
        return text_of(nodes[0])

    vat_breakdown = []
    if settlement is not None:
        for tax in settlement.findall("ram:ApplicableTradeTax", NS):
            vat_breakdown.append({
                "category": first_text(tax, "ram:CategoryCode"),
                "rate": first_text(tax, "ram:RateApplicablePercent"),
                "basis": first_text(tax, "ram:BasisAmount"),
                "amount": first_text(tax, "ram:CalculatedAmount"),
                "exemption_reason": first_text(tax, "ram:ExemptionReason"),
            })

    return {
        "number": first_text(document, "ram:ID") if document is not None else None,
        "type_code": type_code,
        "type_label": DOCUMENT_TYPE_LABELS.get(type_code) if type_code else None,
        "issue_date": iso_date(issue),
        "due_date": iso_date(first(terms, "ram:DueDateDateTime/udt:DateTimeString"))
        if terms is not None else None,
        "currency": first_text(settlement, "ram:InvoiceCurrencyCode")
        if settlement is not None else None,
        "buyer_reference": first_text(agreement, "ram:BuyerReference")
        if agreement is not None else None,
        "order_reference": first_text(
            agreement, "ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID")
        if agreement is not None else None,
        "billing_period": {
            "start": iso_date(first(period, "ram:StartDateDateTime/udt:DateTimeString"))
            if period is not None else None,
            "end": iso_date(first(period, "ram:EndDateDateTime/udt:DateTimeString"))
            if period is not None else None,
        },
        "seller": party(first(agreement, "ram:SellerTradeParty")
                        if agreement is not None else None),
        "buyer": party(first(agreement, "ram:BuyerTradeParty")
                       if agreement is not None else None),
        "totals": {
            "line_net": total("LineTotalAmount"),
            "allowances": total("AllowanceTotalAmount"),
            "charges": total("ChargeTotalAmount"),
            "net": total("TaxBasisTotalAmount"),
            "vat": total("TaxTotalAmount"),
            "gross": total("GrandTotalAmount"),
            "prepaid": total("TotalPrepaidAmount"),
            "due": total("DuePayableAmount"),
        },
        "vat_breakdown": vat_breakdown,
        "lines": extract_lines(transaction) if transaction is not None else [],
        "payment": {
            "means_code": means_code,
            "means_label": PAYMENT_MEANS_LABELS.get(means_code) if means_code else None,
            "iban": first_text(
                means, "ram:PayeePartyCreditorFinancialAccount/ram:IBANID")
            if means is not None else None,
            "terms": first_text(terms, "ram:Description") if terms is not None else None,
        },
    }


# --------------------------------------------------------------------------
# Validation (§6)
# --------------------------------------------------------------------------

SETTLEMENT_PATH = ("/rsm:CrossIndustryInvoice/rsm:SupplyChainTradeTransaction"
                   "/ram:ApplicableHeaderTradeSettlement")
TOTALS_PATH = SETTLEMENT_PATH + "/ram:SpecifiedTradeSettlementHeaderMonetarySummation"


def regime_reforme(date_ref: str) -> str:
    """« avertissement » avant la bascule, « bloquant » à partir de ce jour-là.

    Comparaison de chaînes ISO : sûre, et sans dépendance à un fuseau horaire.
    """
    return "bloquant" if date_ref >= BASCULE_REFORME_FR else "avertissement"


def severite_reforme(date_ref: str) -> str:
    return "bloquant" if regime_reforme(date_ref) == "bloquant" else "alerte"


def jours_avant_bascule(date_ref: str) -> int | None:
    """Jours restants avant la bascule, ou None une fois celle-ci passée."""
    from datetime import date
    reference = date.fromisoformat(date_ref)
    bascule = date.fromisoformat(BASCULE_REFORME_FR)
    reste = (bascule - reference).days
    return reste if reste > 0 else None


def load_manifest() -> dict:
    with open(MANIFEST, encoding="utf-8") as handle:
        return json.load(handle)


def french_message(rule_id: str | None, raw: str, lang: str, profile_label,
                   node=None) -> str:
    """Message français d'une assertion officielle. `raw` garde l'original.

    Une reformulation curatée l'emporte toujours, y compris sur un texte
    officiel déjà français : celui des règles BR-FR-* s'adresse à un
    intégrateur, pas au destinataire de la facture.
    """
    value, build = faulty_value(rule_id, node)
    if value and build is not None:
        return build(value, node)

    if rule_id:
        curated = CURATED_FR_REFORME.get(rule_id) or CURATED_FR.get(rule_id)
        if curated:
            return curated

    body = strip_rule_prefix(raw)

    if lang == "fr":
        return body or raw.strip()

    for pattern, template in FX_CARDINALITY_PATTERNS:
        match = pattern.match(body)
        if match:
            return template.format(*match.groups())

    terms = semantic_terms(raw)
    named = ["%s (%s)" % (code, SEMANTIC_LABELS[code])
             for code in terms if code in SEMANTIC_LABELS]
    where = " Champs concernés : %s." % ", ".join(named) if named else ""
    profile = " %s" % profile_label if profile_label else ""
    label = rule_id or "sans identifiant"
    return ("Règle « %s » du validateur officiel Factur-X%s non respectée.%s "
            "Le libellé officiel de la règle est conservé dans « raw »."
            % (label, profile, where))


def parse_svrl(svrl_text: str, layer: str, severity: str, lang: str,
               profile_label, root=None) -> list[dict]:
    """Constatations d'un rapport SVRL.

    Un `successful-report` n'est retenu que pour un schematron `_WARNING` :
    dans un schematron d'erreurs il porte de l'information neutre, à laquelle
    le contrat n'attribue aucune sévérité.
    """
    from lxml import etree
    try:
        report = etree.fromstring(svrl_text.encode("utf-8"),
                                  parser=etree.XMLParser(resolve_entities=False,
                                                         no_network=True))
    except Exception as exc:
        raise RuntimeError("rapport SVRL illisible : %s" % exc)

    keep = {"{%s}failed-assert" % NS["svrl"]}
    if layer == "alertes_fr":
        keep.add("{%s}successful-report" % NS["svrl"])

    checks = []
    for node in report.iter():
        if node.tag not in keep:
            continue
        raw = " ".join("".join(node.itertext()).split())
        rule_id = node.get("id") or None
        if rule_id is None:
            marker = re.match(r"^\s*\[([^\]]+)\]", raw)
            rule_id = marker.group(1).strip() if marker else None
        located = resolve_location(root, node.get("location"))
        checks.append({
            "id": rule_id,
            "severity": severity,
            "layer": layer,
            "message": french_message(rule_id, raw, lang, profile_label, located),
            "location": simplify_location(node.get("location")),
            "raw": raw or None,
        })
    return checks


def run_xsd(xml_bytes: bytes, profile_conf: dict, profile_label) -> tuple[int, list[dict]]:
    from lxml import etree
    xsd_path = os.path.join(SCHEMAS_DIR, profile_conf["xsd_dir"], profile_conf["xsd"])
    schema = etree.XMLSchema(etree.parse(xsd_path))
    document = etree.fromstring(
        xml_bytes, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    if schema.validate(document):
        return 0, []
    checks = []
    for error in schema.error_log:
        location = error.path or (
            "ligne %s" % error.line if error.line and error.line > 0 else None)
        checks.append({
            "id": "XSD",
            "severity": "bloquant",
            "layer": "xsd",
            "message": ("Le XML ne respecte pas le schéma Factur-X %s%s."
                        % (profile_label or "du profil détecté",
                           " (%s)" % location if location else "")),
            "location": location,
            "raw": error.message,
        })
    return len(checks), checks


def run_schematron(processor, xdm_node, xslt_path: str, layer: str, severity: str,
                   lang: str, profile_label, root=None) -> tuple[int, list[dict]]:
    xslt = processor.new_xslt30_processor()
    executable = xslt.compile_stylesheet(stylesheet_file=xslt_path)
    svrl = executable.transform_to_string(xdm_node=xdm_node)
    if svrl is None:
        raise RuntimeError("le validateur %s n'a produit aucun rapport" % xslt_path)
    checks = parse_svrl(svrl, layer, severity, lang, profile_label, root)
    return len(checks), checks


def _fmt(value: Decimal) -> str:
    return format(value, "f")


def run_coherence(invoice: dict) -> tuple[int, list[dict]]:
    """Arithmétique interne en Decimal, uniquement sur ce qui est présent.

    Une valeur absente n'est jamais remplacée par une hypothèse : la règle qui
    en dépend n'est simplement pas évaluée. C'est ce qui évite de déclarer non
    conformes des factures MINIMUM officiellement valides.
    """
    checks = []
    totals = invoice["totals"]
    dec = {key: to_decimal(value) for key, value in totals.items()}

    def fail(rule_id: str, message: str, location: str):
        checks.append({
            "id": rule_id,
            "severity": "bloquant",
            "layer": "coherence",
            "message": message,
            "location": location,
            "raw": COHERENCE_RULES[rule_id],
        })

    # BR-CO-10 — total HT des lignes = somme des montants nets de ligne.
    line_nets = [to_decimal(line["net"]) for line in invoice["lines"]]
    if dec["line_net"] is not None and line_nets and all(v is not None for v in line_nets):
        total = sum(line_nets, Decimal(0))
        if total != dec["line_net"]:
            fail("BR-CO-10",
                 "Le total HT des lignes déclaré (%s) ne correspond pas à la somme des "
                 "montants nets des %d lignes (%s)."
                 % (totals["line_net"], len(line_nets), _fmt(total)),
                 TOTALS_PATH + "/ram:LineTotalAmount")

    # BR-CO-13 — total HT = total HT des lignes - remises + charges.
    if dec["line_net"] is not None and dec["net"] is not None:
        allowances = dec["allowances"] or Decimal(0)
        charges = dec["charges"] or Decimal(0)
        expected = dec["line_net"] - allowances + charges
        if expected != dec["net"]:
            fail("BR-CO-13",
                 "Le total HT déclaré (%s) ne correspond pas au total HT des lignes (%s) "
                 "diminué des remises (%s) et augmenté des charges (%s), soit %s."
                 % (totals["net"], totals["line_net"], _fmt(allowances),
                    _fmt(charges), _fmt(expected)),
                 TOTALS_PATH + "/ram:TaxBasisTotalAmount")

    # BR-CO-14 — total de TVA = somme des montants de TVA par catégorie.
    vat_amounts = [to_decimal(entry["amount"]) for entry in invoice["vat_breakdown"]]
    if dec["vat"] is not None and vat_amounts and all(v is not None for v in vat_amounts):
        total = sum(vat_amounts, Decimal(0))
        if total != dec["vat"]:
            fail("BR-CO-14",
                 "Le total de TVA déclaré (%s) ne correspond pas à la somme des montants "
                 "de TVA de la ventilation (%s)." % (totals["vat"], _fmt(total)),
                 TOTALS_PATH + "/ram:TaxTotalAmount")

    # BR-CO-15 — total TTC = total HT + total TVA.
    if all(dec[key] is not None for key in ("net", "vat", "gross")):
        expected = dec["net"] + dec["vat"]
        if expected != dec["gross"]:
            fail("BR-CO-15",
                 "Le total TTC déclaré (%s) ne correspond pas au total HT (%s) augmenté "
                 "de la TVA (%s), soit %s."
                 % (totals["gross"], totals["net"], totals["vat"], _fmt(expected)),
                 TOTALS_PATH + "/ram:GrandTotalAmount")

    # BR-CO-16 — net à payer = total TTC - déjà payé.
    # Non évaluée si le montant déjà payé est absent : le profil MINIMUM ne le
    # porte pas, et le supposer nul produirait une fausse erreur.
    if all(dec[key] is not None for key in ("gross", "prepaid", "due")):
        expected = dec["gross"] - dec["prepaid"]
        if expected != dec["due"]:
            fail("BR-CO-16",
                 "Le net à payer déclaré (%s) ne correspond pas au total TTC (%s) diminué "
                 "du montant déjà payé (%s), soit %s."
                 % (totals["due"], totals["gross"], totals["prepaid"], _fmt(expected)),
                 TOTALS_PATH + "/ram:DuePayableAmount")

    # BR-CO-17 — montant de TVA d'une catégorie = base x taux / 100.
    for index, entry in enumerate(invoice["vat_breakdown"], start=1):
        basis = to_decimal(entry["basis"])
        rate = to_decimal(entry["rate"])
        amount = to_decimal(entry["amount"])
        if basis is None or rate is None or amount is None:
            continue
        expected = (basis * rate / Decimal(100)).quantize(Decimal("0.01"),
                                                          rounding=ROUND_HALF_UP)
        if expected != amount:
            fail("BR-CO-17",
                 "Pour la catégorie de TVA %s au taux de %s %%, le montant de TVA déclaré "
                 "(%s) ne correspond pas à la base (%s) multipliée par le taux, soit %s."
                 % (entry["category"] or "non précisée", entry["rate"], entry["amount"],
                    entry["basis"], _fmt(expected)),
                 "%s/ram:ApplicableTradeTax%s/ram:CalculatedAmount"
                 % (SETTLEMENT_PATH, "[%d]" % index if index > 1 else ""))

    return len(checks), checks


def validate(xml_bytes: bytes, xml_text: str, root, invoice: dict, profile_label,
             manifest: dict, enabled: bool, date_ref: str) -> tuple[dict, list[dict]]:
    """Exécute les cinq passes. Toute passe non exécutée est déclarée."""
    passes: list[dict] = []
    not_applied: list[dict] = []
    checks: list[dict] = []
    profile_conf = manifest["profiles"].get(profile_label) if profile_label else None

    def skip(pass_id: str, reason: str):
        passes.append({"id": pass_id, "applied": False, "status": None, "errors": None})
        not_applied.append({"pass": pass_id, "reason": reason})

    if not enabled:
        for pass_id in ("xsd", "profil_fnfe", "regles_fr_ctc", "alertes_fr", "coherence"):
            skip(pass_id, "validation désactivée par --no-validate")
        return {
            "level": 0,
            # Saxon n'a pas été sondé : « non vérifié » n'est pas « indisponible ».
            "engine": {"saxon": None, "available": None},
            "reforme_fr": {
                "date_reference": date_ref,
                "regime": regime_reforme(date_ref),
                "bascule": BASCULE_REFORME_FR,
                "jours_avant_bascule": jours_avant_bascule(date_ref),
            },
            "schemas": {"facturx": None,
                        "fnfe_pack": manifest["fnfe_pack"],
                        "pack_date": manifest["pack_date"]},
            "passes": passes,
            "not_applied": not_applied,
        }, checks

    saxon_processor = None
    saxon_version = None
    try:
        from saxonche import PySaxonProcessor
        saxon_processor = PySaxonProcessor(license=False)
        saxon_version = re.sub(r"\s+from\s+Saxonica\s*$", "",
                               saxon_processor.version or "").strip() or None
    except Exception as exc:
        warn("saxonche indisponible : %s" % exc)

    level = 2 if saxon_processor is not None else 1

    # Passe 1 — XSD.
    if profile_conf is None:
        skip("xsd", "profil non reconnu — aucun schéma XSD Factur-X correspondant")
    else:
        try:
            errors, found = run_xsd(xml_bytes, profile_conf, profile_label)
            passes.append({"id": "xsd", "applied": True,
                           "status": "pass" if errors == 0 else "fail", "errors": errors})
            checks.extend(found)
        except Exception as exc:
            warn("passe xsd impossible : %s" % exc)
            skip("xsd", "schéma XSD illisible ou inexploitable (%s)" % exc)

    # Passes 2 à 4 — validateurs officiels FNFE.
    # Un seul des deux schematrons jumeaux est exécuté : ils portent le même
    # jeu de règles, et c'est la date qui donne la sévérité. Exécuter les deux
    # comptait deux fois les mêmes constatations.
    schematron_passes = [
        ("profil_fnfe", (profile_conf or {}).get("profil_xslt"), "bloquant",
         manifest["assertion_language"]["profil_fnfe"]),
        ("regles_fr_ctc", manifest["fr_ctc_xslt"]["regles_fr_ctc"],
         severite_reforme(date_ref),
         manifest["assertion_language"]["regles_fr_ctc"]),
    ]

    xdm_node = None
    if saxon_processor is not None:
        try:
            xdm_node = saxon_processor.parse_xml(xml_text=xml_text)
        except Exception as exc:
            warn("Saxon n'a pas pu charger le XML : %s" % exc)

    for pass_id, xslt_name, severity, lang in schematron_passes:
        if profile_conf is None:
            skip(pass_id, "profil non reconnu — aucun validateur officiel FNFE applicable")
            continue
        fnfe_dir = profile_conf.get("fnfe_dir")
        if not fnfe_dir or (pass_id == "profil_fnfe" and not xslt_name):
            skip(pass_id, profile_conf.get(
                "no_fnfe_reason",
                "aucun validateur officiel FNFE pour le profil %s" % profile_label))
            continue
        if saxon_processor is None or xdm_node is None:
            skip(pass_id, "saxonche non installé — installer pour la validation "
                          "réforme française")
            continue
        path = os.path.join(SCHEMAS_DIR, fnfe_dir, xslt_name)
        if not os.path.exists(path):
            skip(pass_id, "validateur officiel absent du dépôt (%s)" % xslt_name)
            continue
        try:
            errors, found = run_schematron(saxon_processor, xdm_node, path, pass_id,
                                           severity, lang, profile_label, root)
        except Exception as exc:
            warn("passe %s impossible : %s" % (pass_id, exc))
            skip(pass_id, "le validateur officiel n'a pas pu être exécuté (%s)" % exc)
            continue
        if errors == 0:
            status = "pass"
        elif pass_id == "regles_fr_ctc" and regime_reforme(date_ref) != "bloquant":
            # Les règles échouent, mais elles ne sont pas encore opposables.
            status = "warn"
        else:
            status = "fail"
        passes.append({"id": pass_id, "applied": True, "status": status,
                       "errors": errors})
        checks.extend(found)

    # Passe 4 — alertes_fr : jamais exécutée, et on dit pourquoi.
    jumelage = manifest["jumelage_fr_ctc"]
    skip("alertes_fr",
         "doublon mesuré : même jeu de règles que regles_fr_ctc "
         "(%d identifiants d'assertion, recouvrement %d/%d, aucun propre à "
         "l'une ou l'autre), autre date d'application — mode WARNING jusqu'au "
         "%s, mode FATAL ensuite"
         % (jumelage["identifiants"], jumelage["communs"],
            jumelage["identifiants"], BASCULE_REFORME_FR))

    # Passe 5 — cohérence arithmétique.
    errors, found = run_coherence(invoice)
    passes.append({"id": "coherence", "applied": True,
                   "status": "pass" if errors == 0 else "fail", "errors": errors})
    checks.extend(found)

    if saxon_processor is None:
        checks.append({
            "id": "SAXON-ABSENT",
            "severity": "info",
            "layer": "validation",
            "message": "saxonche n'est pas installé : la validation par les schematrons "
                       "officiels FNFE n'a pas pu être exécutée. Reprendre la commande "
                       "d'installation de la skill, qui l'inclut, pour obtenir la "
                       "validation complète de la réforme française.",
            "location": None,
            "raw": None,
        })

    order = {"xsd": 0, "profil_fnfe": 1, "regles_fr_ctc": 2, "alertes_fr": 3,
             "coherence": 4}
    passes.sort(key=lambda p: order[p["id"]])
    not_applied.sort(key=lambda n: order[n["pass"]])

    return {
        "level": level,
        "engine": {"saxon": saxon_version, "available": saxon_processor is not None},
        "reforme_fr": {
            "date_reference": date_ref,
            "regime": regime_reforme(date_ref),
            "bascule": BASCULE_REFORME_FR,
            "jours_avant_bascule": jours_avant_bascule(date_ref),
        },
        "schemas": {
            "facturx": profile_conf["facturx_version"] if profile_conf else None,
            "fnfe_pack": manifest["fnfe_pack"],
            "pack_date": manifest["pack_date"],
        },
        "passes": passes,
        "not_applied": not_applied,
    }, checks


# --------------------------------------------------------------------------
# Synthèse (§8)
# --------------------------------------------------------------------------

def pass_by_id(validation: dict, pass_id: str) -> dict | None:
    for entry in validation["passes"]:
        if entry["id"] == pass_id:
            return entry
    return None


def conformity(validation: dict, pass_id: str):
    """True, False, ou None si la passe n'a pas été exécutée. None ne devient
    jamais False : « non vérifié » et « non conforme » sont deux choses
    différentes."""
    entry = pass_by_id(validation, pass_id)
    if entry is None or not entry["applied"]:
        return None
    return entry["errors"] == 0


MOIS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre")


def date_francaise(iso: str | None) -> str:
    """« 2026-09-01 » → « 1er septembre 2026 ». Une date lue par un artisan."""
    if not iso:
        return "la date de bascule"
    from datetime import date
    d = date.fromisoformat(iso)
    jour = "1er" if d.day == 1 else str(d.day)
    return "%s %s %d" % (jour, MOIS_FR[d.month - 1], d.year)


def profile_phrase(label) -> str:
    return "Factur-X %s" % label if label else "Factur-X de profil non reconnu"


def build_verdict(status: str, profile_label, validation: dict,
                  bloquants: int, alertes: int, conforme_profil, conforme_reforme) -> str:
    if status == "missing_schemas":
        return ("Les schémas officiels de validation ne sont pas installés : "
                "rien n'a pu être vérifié. Ils ne sont pas redistribués avec la "
                "skill ; le champ « remede » donne la commande qui les installe, "
                "une fois pour toutes.")
    if status == "file_not_visible":
        return ("Le fichier n'est pas visible depuis le bac à sable où tourne ce "
                "script : rien n'a été lu, et le chemin fourni n'est pas "
                "nécessairement en cause. Le champ « remede » donne la "
                "manipulation à faire.")
    if status == "missing_dependency":
        return ("Le socle Python nécessaire à la lecture du fichier n'est pas "
                "installé : rien n'a été lu, et aucune conclusion ne peut être "
                "tirée de cette facture. Le champ « remede » donne la commande "
                "exacte à exécuter.")
    if status == "unreadable":
        return "Fichier illisible : ni son contenu ni sa conformité n'ont pu être examinés."
    if status == "unstructured":
        return ("PDF lisible, mais sans XML Factur-X embarqué : cette facture est hors "
                "du périmètre de la skill, aucune extraction n'a été tentée.")
    if status == "invalid_xml":
        return ("Un XML Factur-X est bien embarqué dans le PDF, mais il n'est pas "
                "analysable : aucune donnée n'a pu en être extraite.")

    xsd = pass_by_id(validation, "xsd")

    if conforme_profil is True:
        head = "Facture valide au format %s" % profile_phrase(profile_label)
    elif conforme_profil is False:
        head = "Facture non conforme au profil %s" % profile_phrase(profile_label)
    elif xsd is not None and xsd["applied"] and xsd["status"] == "fail":
        head = ("Facture dont le XML ne respecte pas le schéma %s"
                % profile_phrase(profile_label))
    elif xsd is not None and xsd["applied"]:
        head = ("Facture au format %s, structure XML valide, conformité au profil "
                "non vérifiée" % profile_phrase(profile_label))
    else:
        head = "Facture au format %s, conformité non vérifiée" % profile_phrase(
            profile_label)

    # « mais » n'a de sens qu'en opposition à une première partie favorable.
    positive_head = conforme_profil is True

    if conforme_reforme is True:
        tail = ("%s conforme aux règles françaises de la réforme."
                % ("et" if positive_head else ", mais"))
    elif conforme_reforme is False:
        # Le compte cité est celui des règles françaises en échec, pas celui
        # des points bloquants : avant la bascule, les mêmes constatations sont
        # des avertissements, et « 0 point bloquant » serait absurde.
        entry = pass_by_id(validation, "regles_fr_ctc") or {}
        points = entry.get("errors") or bloquants
        plural = "s" if points > 1 else ""
        regime = (validation.get("reforme_fr") or {}).get("regime")
        if regime == "avertissement":
            echeance = date_francaise(
                (validation.get("reforme_fr") or {}).get("bascule"))
            detail = ("%d point%s : avertissement%s aujourd'hui, bloquant%s à "
                      "partir du %s" % (points, plural, plural, plural, echeance))
        else:
            detail = "%d point%s bloquant%s" % (points, plural, plural)
        tail = ("%s non conforme aux règles françaises de la réforme (%s)."
                % (", mais" if positive_head else " et", detail))
    else:
        tail = " ; conformité aux règles françaises de la réforme non vérifiée."

    return head + (tail if tail.startswith((",", ";", " ")) else " " + tail)


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# `rapport` — le texte français final, assemblé par le script
# --------------------------------------------------------------------------
#
# Le modèle n'a plus qu'à l'afficher tel quel. Tout ce qui lui était demandé
# en prose — une puce par constatation, messages repris mot pour mot, compte à
# rebours avant la bascule — est fait ici, où c'est vérifiable par un test
# plutôt que par un run.

def date_courte(iso: str | None) -> str | None:
    """« 2017-11-13 » → « 13/11/2017 ». Rendu, pas transformation."""
    if not iso:
        return None
    parties = iso.split("-")
    if len(parties) != 3:
        return iso
    return "%s/%s/%s" % (parties[2], parties[1], parties[0])


def montant_fr(valeur: str | None, devise: str | None) -> str | None:
    """« 671.15 » → « 671,15 € ». Aucun chiffre n'est ajouté ni retiré :
    seule la virgule décimale française remplace le point."""
    if valeur is None:
        return None
    texte = valeur.replace(".", ",")
    symbole = {"EUR": "€"}.get((devise or "").upper(), devise or "")
    return ("%s %s" % (texte, symbole)).strip()


def phrase_facture(invoice: dict) -> str | None:
    """En-tête : de quelle facture on parle, et pour quels montants."""
    devise = invoice["currency"]
    totaux = invoice["totals"]
    titre = "Facture" if invoice["type_code"] == "380" else (
        invoice["type_label"] or "Document")

    tete = titre
    if invoice["number"]:
        tete += " n° %s" % invoice["number"]
    if invoice["seller"]["name"]:
        tete += " de %s" % invoice["seller"]["name"]
    if invoice["buyer"]["name"]:
        tete += ", à %s" % invoice["buyer"]["name"]

    morceaux = [tete + "."]

    gross = montant_fr(totaux["gross"], devise)
    net = montant_fr(totaux["net"], devise)
    vat = montant_fr(totaux["vat"], devise)
    if gross and net and vat:
        somme = "%s TTC (%s HT + %s de TVA)" % (gross, net, vat)
    elif gross:
        somme = "%s TTC" % gross
    elif net:
        somme = "%s HT" % net
    else:
        somme = None

    dates = []
    if invoice["issue_date"]:
        dates.append("émise le %s" % date_courte(invoice["issue_date"]))
    if invoice["due_date"]:
        dates.append("échéance le %s" % date_courte(invoice["due_date"]))
    if somme or dates:
        morceaux.append(", ".join([m for m in [somme] + dates if m]) + ".")

    prepaid = to_decimal(totaux["prepaid"])
    if prepaid is not None and prepaid != 0:
        reste = montant_fr(totaux["due"], devise)
        phrase = "Un acompte de %s a déjà été versé" % montant_fr(
            totaux["prepaid"], devise)
        morceaux.append(phrase + (", il reste %s à payer." % reste if reste
                                  else "."))
    elif totaux["due"] and totaux["due"] != totaux["gross"]:
        morceaux.append("Net à payer : %s." % montant_fr(totaux["due"], devise))

    paiement = invoice["payment"]
    if paiement["means_label"] or paiement["iban"]:
        detail = "Paiement"
        if paiement["means_label"]:
            detail += " par %s" % paiement["means_label"].lower()
        if paiement["iban"]:
            detail += " (IBAN %s)" % paiement["iban"]
        morceaux.append(detail + ".")

    return " ".join(morceaux) if len(morceaux) > 1 or invoice["number"] else None


# Un montant : deux décimales exactes, ni précédé ni suivi d'un chiffre. Le
# second garde-fou écarte les numéros de version du genre « 1.09.2 ».
MONTANT_BRUT = re.compile(r"(?<![\d,.])(\d+)\.(\d{2})(?!\d)(?!\.\d)")
SPAN_CITE = re.compile(r"«[^»]*»|\"[^\"]*\"")


def _rendre(match, devise: str | None) -> str:
    """Virgule décimale toujours ; symbole monétaire seulement si c'est un
    montant. Un nombre suivi de « % » est un taux, pas une somme."""
    valeur = "%s,%s" % (match.group(1), match.group(2))
    if match.group(0) != match.group(0).rstrip() or TAUX_SUIVANT.match(
            match.string, match.end()):
        return valeur
    return montant_fr("%s.%s" % (match.group(1), match.group(2)), devise)


TAUX_SUIVANT = re.compile(r"\s*%")


def montants_en_francais(texte: str, devise: str | None) -> str:
    """Rend à la française les montants d'un message, pour le seul rapport.

    Ce qui est cité entre guillemets est laissé intact : un SIREN ou un taux de
    TVA y figure précisément parce que **son écriture** est en cause. Le
    reformater effacerait la faute qu'on signale.
    """
    morceaux = []
    position = 0
    for cite in SPAN_CITE.finditer(texte):
        morceaux.append(MONTANT_BRUT.sub(
            lambda m: _rendre(m, devise), texte[position:cite.start()]))
        morceaux.append(cite.group(0))
        position = cite.end()
    morceaux.append(MONTANT_BRUT.sub(lambda m: _rendre(m, devise), texte[position:]))
    return "".join(morceaux)


def meme_constatation(a: dict, b: dict) -> bool:
    """Deux passes ont-elles constaté la même chose ?

    Même identifiant de règle, et un emplacement qui contient l'autre : le
    validateur de profil signale l'écart sur le bloc des totaux, la passe
    `coherence` sur le montant précis — c'est un seul problème vu de deux
    hauteurs.

    Deux emplacements qui divergent restent deux constatations : les
    identifiants légaux du vendeur et de l'acheteur portent la même règle, ce
    sont bien deux corrections à demander.
    """
    if a["id"] is None or a["id"] != b["id"]:
        return False
    x, y = a["location"], b["location"]
    if x is None or y is None:
        return x == y
    return x == y or x.startswith(y + "/") or y.startswith(x + "/")


def dedupliquer(checks: list[dict]) -> list[dict]:
    """Une constatation, une puce — en gardant la plus précise des deux.

    `checks[]` conserve toutes les occurrences : la confirmation indépendante
    d'une couche par une autre est une propriété qu'on veut garder.
    """
    retenus: list[dict] = []
    for check in checks:
        for index, garde in enumerate(retenus):
            if meme_constatation(check, garde):
                # Le plus précis l'emporte : son message nomme la valeur fautive.
                if len(check["location"] or "") > len(garde["location"] or ""):
                    retenus[index] = check
                break
        else:
            retenus.append(check)
    return retenus


def build_rapport(result: dict) -> str:
    """Texte prêt à afficher, assemblé à partir du seul JSON déjà produit."""
    summary = result["summary"]
    blocs: list[str] = []

    invoice = result.get("invoice")
    if invoice:
        entete = phrase_facture(invoice)
        if entete:
            blocs.append(entete)

    blocs.append(summary["verdict"])

    # L'échéance se raconte selon ce que la passe française a fait, pas selon
    # la seule date. Annoncer « il reste 11 jours pour les faire corriger »
    # quand rien n'a été vérifié laisse un « les » sans antécédent, et fait
    # croire à l'existence de constatations qu'on n'a pas.
    reforme = summary.get("reforme_fr") or {}
    reste = reforme.get("jours_avant_bascule")
    bascule = date_francaise(reforme.get("bascule"))
    passe_fr = pass_by_id(result.get("validation") or {}, "regles_fr_ctc") or {}
    constatations_fr = [c for c in result["checks"]
                        if c["layer"] == "regles_fr_ctc"]

    if not invoice:
        # Fichier illisible, hors montage, socle absent : rien n'a été lu, et
        # parler du calendrier de la réforme n'aurait aucun objet.
        pass
    elif not passe_fr.get("applied"):
        echeance = ("deviennent bloquantes le %s" % bascule if reste
                    else "sont bloquantes depuis le %s" % bascule)
        blocs.append("La conformité aux règles françaises de la réforme n'a pas "
                     "été vérifiée. Ces règles %s." % echeance)
    elif constatations_fr and reste:
        blocs.append(
            "Il reste %d jour%s pour les faire corriger, jusqu'au %s."
            % (reste, "s" if reste > 1 else "", bascule))

    # Ce qui n'a pas pu être vérifié se dit là, en clair, et non en note de bas
    # de texte : c'est une limite du résultat, pas un détail d'installation.
    infos = [c for c in result["checks"] if c["severity"] == "info"] if invoice else []
    validation_infos = [c for c in infos if c["layer"] == "validation"]
    autres_infos = [c for c in infos if c["layer"] != "validation"]
    for info in validation_infos:
        blocs.append(info["message"])

    # Sur un statut terminal — fichier illisible, hors montage, socle absent,
    # XML non analysable — le verdict et le remède disent déjà tout. Y ajouter
    # des puces ne ferait que répéter la même phrase sous une autre forme.
    constatations = dedupliquer(
        [c for c in result["checks"]
         if c["severity"] in ("bloquant", "alerte")]) if invoice else []
    if constatations:
        devise = (invoice or {}).get("currency")
        blocs.append("\n".join(
            "- %s" % montants_en_francais(c["message"], devise)
            for c in constatations))
        if any(c["layer"] in ("regles_fr_ctc", "profil_fnfe", "xsd")
               for c in constatations):
            blocs.append("Ces corrections sont à demander à votre fournisseur : "
                         "elles concernent la facture qu'il a émise.")

    remede = result.get("remede")
    if remede:
        blocs.append(remede)

    if autres_infos:
        blocs.append("À noter : " + " ".join(c["message"] for c in autres_infos))

    return "\n\n".join(blocs)


def source_block(path: str) -> dict:
    block = {"file": os.path.basename(path), "sha256": None, "size_bytes": None}
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        block["sha256"] = hashlib.sha256(data).hexdigest()
        block["size_bytes"] = len(data)
    except OSError:
        pass
    return block


# Le socle, sans lequel le script ne peut rien lire du tout. `saxonche` n'en
# fait pas partie : son absence est un mode de fonctionnement normal (niveau 1),
# pas une dépendance manquante.
DEPENDANCES_SOCLE = ("pypdf", "lxml")

# Ce que le remède fait installer : le socle **et** saxonche, en une seule
# commande. Un modèle qui lit deux commandes séparées n'en exécute qu'une, et
# la skill perd alors silencieusement sa raison d'être — la validation des
# règles françaises. Constaté sur un run réel.
PAQUETS_COMPLETS = ("pypdf==6.16.1", "lxml==6.1.2", "saxonche==13.0.0")


def dependances_manquantes() -> list[str]:
    """Modules du socle qui ne s'importent pas. Un module présent mais cassé
    est compté comme manquant : dans les deux cas le script ne peut pas lire
    le PDF, et l'utilisateur a le même geste à faire."""
    manquant = []
    for module in DEPENDANCES_SOCLE:
        try:
            importlib.import_module(module)
        except Exception:
            manquant.append(module)
    return manquant


def missing_dependency_result(path: str, manquant: list[str],
                              manifest: dict) -> dict:
    """Sortie normale — un JSON, jamais un traceback — quand le socle manque.

    La commande de remède cite l'interpréteur réellement en train d'exécuter le
    script : une commande d'installation générique viserait un autre
    interpréteur, et le problème resterait entier.
    """
    # Versions épinglées : une commande d'installation laissée ouverte expose à
    # la substitution d'un paquet en amont.
    remede = "%s -m %s %s" % (sys.executable, "pip", "install " +
                              " ".join(PAQUETS_COMPLETS))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "missing_dependency",
        "manquant": manquant,
        "remede": remede,
        "source": source_block(path) if os.path.isfile(path)
        else {"file": os.path.basename(path), "sha256": None, "size_bytes": None},
        "detection": {"method": None, "attachment_name": None,
                      "af_relationship": None, "notes": []},
        "profile": {"id": None, "label": None, "source": None},
        "validation": empty_validation(
            manifest, "dépendances Python absentes : %s" % ", ".join(manquant)),
        "checks": [{
            "id": "DEPENDANCE-MANQUANTE",
            "severity": "bloquant",
            "layer": "environnement",
            "message": ("Le module Python %s n'est pas installé pour "
                        "l'interpréteur qui exécute ce script. Rien n'a pu être "
                        "lu du fichier. La commande du champ « remede » installe "
                        "en une fois tout ce dont la skill a besoin, saxonche "
                        "compris — sans lui, les règles françaises de la réforme "
                        "ne seraient pas vérifiées."
                        % " et ".join("« %s »" % m for m in manquant)),
            "location": None,
            "raw": None}],
        "summary": {"bloquants": 1, "alertes": 0, "conforme_profil": None,
                    "conforme_reforme_fr": None,
                    "verdict": build_verdict("missing_dependency", None, {}, 1, 0,
                                             None, None)},
    }


REMEDE_SCHEMAS = (
    "python3 scripts/fetch_schemas.py, depuis la racine du dépôt de la skill, "
    "télécharge les schémas officiels une fois pour toutes. Aucun appel réseau "
    "n'a lieu ensuite : le script de lecture des factures ne sort jamais de la "
    "machine."
)


def schemas_manquants(manifest: dict) -> list[str]:
    """Schémas officiels absents du disque, en chemins relatifs.

    Ils ne sont pas redistribués par le dépôt : trop volumineux, et de licence
    tierce. `scripts/fetch_schemas.py` les installe. Sans eux, le script ne peut
    valider quoi que ce soit — autant le dire clairement plutôt que d'échouer
    au premier `open()`.
    """
    attendus: list[str] = []
    for profil, conf in manifest["profiles"].items():
        attendus.append(os.path.join(conf["xsd_dir"], conf["xsd"]))
        fnfe = conf.get("fnfe_dir")
        if fnfe:
            attendus.append(os.path.join(fnfe, conf["profil_xslt"]))
            for cle in ("regles_fr_ctc", "alertes_fr"):
                attendus.append(os.path.join(fnfe, manifest["fr_ctc_xslt"][cle]))
    return sorted({rel for rel in attendus
                   if not os.path.isfile(os.path.join(SCHEMAS_DIR, rel))})


def missing_schemas_result(path: str, manquant: list[str],
                           manifest: dict) -> dict:
    """Sortie normale — un JSON, jamais un traceback — quand les schémas
    officiels n'ont pas encore été téléchargés."""
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "missing_schemas",
        "manquant": manquant,
        "remede": REMEDE_SCHEMAS,
        "source": source_block(path) if os.path.isfile(path)
        else {"file": os.path.basename(path), "sha256": None, "size_bytes": None},
        "detection": {"method": None, "attachment_name": None,
                      "af_relationship": None, "notes": []},
        "profile": {"id": None, "label": None, "source": None},
        "validation": empty_validation(
            manifest, "schémas officiels absents : %d fichier(s) à installer"
                      % len(manquant)),
        "checks": [{
            "id": "SCHEMAS-ABSENTS",
            "severity": "bloquant",
            "layer": "environnement",
            "message": ("Les schémas officiels Factur-X et FNFE ne sont pas "
                        "installés : %d fichier(s) manquent, et sans eux aucune "
                        "conformité ne peut être vérifiée. Ils ne sont pas "
                        "redistribués avec la skill ; une commande les installe "
                        "une fois pour toutes, indiquée par le champ « remede »."
                        % len(manquant)),
            "location": None,
            "raw": None}],
        "summary": {"bloquants": 1, "alertes": 0, "conforme_profil": None,
                    "conforme_reforme_fr": None,
                    "verdict": build_verdict("missing_schemas", None, {}, 1, 0,
                                             None, None)},
    }


REMEDE_MONTAGE = (
    "Le répertoire de travail n'est pas accessible depuis le bac à sable de "
    "l'agent. Il faut activer son montage dans la configuration de l'agent, "
    "puis recréer les conteneurs — la configuration de montage est figée au "
    "démarrage d'un conteneur, un conteneur déjà lancé ignorerait le "
    "changement. Relancer ensuite la commande."
)


def indices_bac_a_sable(script_path: str | None = None) -> dict:
    """Faits observés sur le système de fichiers. Aucun jugement, aucune
    déduction : trois constats, que `fichier_hors_montage` combine ensuite."""
    chemin = script_path or os.path.abspath(__file__)
    try:
        workspace = os.path.isdir("/workspace") and bool(os.listdir("/workspace"))
    except OSError:
        workspace = False
    return {
        "conteneur": os.path.exists("/.dockerenv"),
        "skills_montees": (os.path.isdir("/root/.hermes/skills")
                           or "%s.hermes%sskills%s" % (os.sep, os.sep, os.sep) in chemin),
        "workspace_monte": workspace,
    }


def fichier_hors_montage(indices: dict) -> bool:
    """Vrai seulement si les trois indices concordent : on tourne dans un
    conteneur, la skill y a été montée par Hermes, et le répertoire de travail
    ne l'a pas été.

    Il en manque un ⇒ faux. Sur une machine ordinaire, un chemin absent est un
    chemin absent, et le dire autrement enverrait l'utilisateur modifier une
    configuration qui n'a rien à voir avec son problème.
    """
    return (bool(indices.get("conteneur"))
            and bool(indices.get("skills_montees"))
            and not bool(indices.get("workspace_monte")))


def file_not_visible_result(path: str, indices: dict, manifest: dict) -> dict:
    """Le fichier existe probablement, mais pas de ce côté du montage.

    Distinct de `unreadable` : là, le chemin est bon et c'est l'environnement
    qu'il faut corriger. Les confondre laisserait l'utilisateur chercher une
    faute de frappe qui n'existe pas.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "file_not_visible",
        "remede": REMEDE_MONTAGE,
        "indices": indices,
        "source": {"file": os.path.basename(path), "sha256": None,
                   "size_bytes": None},
        "detection": {"method": None, "attachment_name": None,
                      "af_relationship": None, "notes": []},
        "profile": {"id": None, "label": None, "source": None},
        "validation": empty_validation(
            manifest, "fichier hors du montage du bac à sable"),
        "checks": [{
            "id": "FICHIER-HORS-MONTAGE",
            "severity": "bloquant",
            "layer": "environnement",
            "message": ("Le fichier « %s » est introuvable depuis le bac à sable, "
                        "mais le chemin n'est pas forcément faux : ce bac à sable "
                        "n'a pas accès au répertoire de travail. Rien n'a été lu. "
                        "Le champ « remede » donne la manipulation exacte."
                        % path),
            "location": None,
            "raw": None}],
        "summary": {"bloquants": 1, "alertes": 0, "conforme_profil": None,
                    "conforme_reforme_fr": None,
                    "verdict": build_verdict("file_not_visible", None, {}, 1, 0,
                                             None, None)},
    }


def empty_validation(manifest: dict, reason: str) -> dict:
    return {
        "level": 0,
        "engine": {"saxon": None, "available": None},
        "schemas": {"facturx": None, "fnfe_pack": manifest["fnfe_pack"],
                    "pack_date": manifest["pack_date"]},
        "passes": [{"id": pass_id, "applied": False, "status": None, "errors": None}
                   for pass_id in ("xsd", "profil_fnfe", "regles_fr_ctc",
                                   "alertes_fr", "coherence")],
        "not_applied": [{"pass": pass_id, "reason": reason}
                        for pass_id in ("xsd", "profil_fnfe", "regles_fr_ctc",
                                        "alertes_fr", "coherence")],
    }


def build(path: str, do_validate: bool, date_ref: str) -> tuple[dict, int]:
    manifest = load_manifest()

    # Les schémas ne sont pas dans le dépôt : sans eux, rien à valider. On le
    # dit avant d'ouvrir quoi que ce soit, plutôt que d'échouer à mi-chemin.
    if do_validate:
        absents = schemas_manquants(manifest)
        if absents:
            warn("schémas absents : %d fichier(s)" % len(absents))
            return missing_schemas_result(path, absents, manifest), 1

    if not os.path.isfile(path):
        indices = indices_bac_a_sable()
        if fichier_hors_montage(indices):
            return file_not_visible_result(path, indices, manifest), 1
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "unreadable",
            "source": {"file": os.path.basename(path), "sha256": None,
                       "size_bytes": None},
            "detection": {"method": None, "attachment_name": None,
                          "af_relationship": None, "notes": []},
            "profile": {"id": None, "label": None, "source": None},
            "validation": empty_validation(manifest, "fichier absent ou illisible"),
            "checks": [{
                "id": "FICHIER-ILLISIBLE", "severity": "bloquant", "layer": "source",
                "message": "Le fichier « %s » est introuvable ou ne peut pas être lu."
                           % path,
                "location": None, "raw": None}],
            "summary": {"bloquants": 1, "alertes": 0, "conforme_profil": None,
                        "conforme_reforme_fr": None,
                        "verdict": build_verdict("unreadable", None, {}, 1, 0,
                                                 None, None)},
        }
        return result, 1

    source = source_block(path)
    base = {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "source": source,
        "detection": {"method": None, "attachment_name": None,
                      "af_relationship": None, "notes": []},
        "profile": {"id": None, "label": None, "source": None},
    }

    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:
                raise Unreadable("PDF chiffré")
            if getattr(reader, "is_encrypted", False):
                raise Unreadable("PDF chiffré")
        attachments = collect_attachments(reader)
    except Unreadable as exc:
        reason = str(exc)
        base.update({
            "status": "unreadable",
            "validation": empty_validation(manifest, reason),
            "checks": [{"id": "FICHIER-ILLISIBLE", "severity": "bloquant",
                        "layer": "source",
                        "message": "Le fichier ne peut pas être exploité : %s." % reason,
                        "location": None, "raw": None}],
            "summary": {"bloquants": 1, "alertes": 0, "conforme_profil": None,
                        "conforme_reforme_fr": None,
                        "verdict": build_verdict("unreadable", None, {}, 1, 0,
                                                 None, None)},
        })
        return base, 1
    except Exception as exc:
        warn("lecture PDF impossible : %s" % exc)
        reason = "fichier non-PDF, corrompu ou illisible"
        base.update({
            "status": "unreadable",
            "validation": empty_validation(manifest, reason),
            "checks": [{"id": "FICHIER-ILLISIBLE", "severity": "bloquant",
                        "layer": "source",
                        "message": "Le fichier n'est pas un PDF exploitable.",
                        "location": None, "raw": str(exc)}],
            "summary": {"bloquants": 1, "alertes": 0, "conforme_profil": None,
                        "conforme_reforme_fr": None,
                        "verdict": build_verdict("unreadable", None, {}, 1, 0,
                                                 None, None)},
        })
        return base, 1

    attachment, detection = detect(attachments)
    base["detection"] = detection

    if attachment is None:
        base.update({
            "status": "unstructured",
            "validation": empty_validation(
                manifest, "aucun XML Factur-X embarqué dans le PDF"),
            "checks": [{
                "id": "SANS-XML", "severity": "info", "layer": "detection",
                "message": "Ce PDF ne contient aucun XML Factur-X : il s'agit d'une "
                           "facture non structurée, hors périmètre de la skill. "
                           "Aucune extraction n'a été tentée.",
                "location": None, "raw": None}],
            "summary": {"bloquants": 0, "alertes": 0, "conforme_profil": None,
                        "conforme_reforme_fr": None,
                        "verdict": build_verdict("unstructured", None, {}, 0, 0,
                                                 None, None)},
        })
        return base, 0

    checks: list[dict] = []
    if detection["method"] == "fallback":
        checks.append({
            "id": "DETECTION-REPLI", "severity": "info", "layer": "detection",
            "message": detection["notes"][0],
            "location": None, "raw": None})

    from lxml import etree
    xml_bytes = attachment["data"]
    try:
        root = etree.fromstring(
            xml_bytes,
            parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except Exception as exc:
        base.update({
            "status": "invalid_xml",
            "validation": empty_validation(
                manifest, "XML embarqué non analysable"),
            "checks": checks + [{
                "id": "XML-NON-ANALYSABLE", "severity": "bloquant", "layer": "xsd",
                "message": "Le XML embarqué dans le PDF n'est pas analysable : il ne "
                           "respecte pas la syntaxe XML.",
                "location": None, "raw": str(exc)}],
            "summary": {"bloquants": 1, "alertes": 0, "conforme_profil": None,
                        "conforme_reforme_fr": None,
                        "verdict": build_verdict("invalid_xml", None, {}, 1, 0,
                                                 None, None)},
        })
        return base, 0

    profile_id = first_text(
        root,
        "rsm:ExchangedDocumentContext/"
        "ram:GuidelineSpecifiedDocumentContextParameter/ram:ID")
    profile_label = PROFILE_LABELS.get(profile_id) if profile_id else None
    base["profile"] = {
        "id": profile_id,
        "label": profile_label,
        "source": "xml" if profile_id else None,
    }
    if profile_label is None:
        checks.append({
            "id": "PROFIL-INCONNU", "severity": "alerte", "layer": "detection",
            "message": ("L'identifiant de profil « %s » n'est pas reconnu : les "
                        "validateurs officiels du profil ne peuvent pas être choisis."
                        % profile_id) if profile_id else
                       ("Le XML ne déclare aucun identifiant de profil "
                        "(ram:GuidelineSpecifiedDocumentContextParameter/ram:ID)."),
            "location": "/rsm:CrossIndustryInvoice/rsm:ExchangedDocumentContext"
                        "/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID",
            "raw": None})

    invoice = extract_invoice(root)
    if profile_label in ("MINIMUM", "BASIC WL"):
        # Ces profils ne portent pas de lignes par construction. Vide ≠ manquant.
        invoice["lines"] = []

    # Saxon attend du texte : on décode avec l'encodage réellement déclaré par
    # le document, pas avec un UTF-8 présumé.
    encoding = root.getroottree().docinfo.encoding or "utf-8"
    try:
        xml_text = xml_bytes.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        xml_text = xml_bytes.decode("utf-8", errors="replace")

    validation, validation_checks = validate(xml_bytes, xml_text, root, invoice,
                                             profile_label, manifest, do_validate,
                                             date_ref)
    checks.extend(validation_checks)

    conforme_profil = conformity(validation, "profil_fnfe")
    conforme_reforme = conformity(validation, "regles_fr_ctc")
    bloquants = sum(1 for c in checks if c["severity"] == "bloquant")
    alertes = sum(1 for c in checks if c["severity"] == "alerte")

    base.update({
        "invoice": invoice,
        "validation": validation,
        "checks": checks,
        "summary": {
            "bloquants": bloquants,
            "alertes": alertes,
            "conforme_profil": conforme_profil,
            # Le fait ne bouge pas avec la date : la facture satisfait les
            # règles françaises, ou non. C'est la sévérité et l'urgence qui
            # sont datées.
            "conforme_reforme_fr": conforme_reforme,
            "reforme_fr": validation["reforme_fr"],
            "verdict": build_verdict("ok", profile_label, validation, bloquants,
                                     alertes, conforme_profil, conforme_reforme),
        },
    })
    return base, 0


def emettre(result: dict, code: int) -> int:
    """Ajoute le rapport, écrit l'unique objet JSON, rend le code de sortie.

    Point de passage obligé : aucune sortie du script ne doit être dépourvue
    de `rapport`, sinon le modèle n'aurait rien à afficher.
    """
    result["rapport"] = build_rapport(result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return code


def date_ref_valide(valeur: str) -> str:
    from datetime import date
    try:
        return date.fromisoformat(valeur).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(
            "date attendue au format AAAA-MM-JJ, reçu %r" % valeur)


def main(argv=None) -> int:
    global _QUIET
    parser = argparse.ArgumentParser(
        description="Extrait et valide une facture Factur-X (PDF/A-3).",
        add_help=True)
    parser.add_argument("pdf", help="chemin du fichier PDF à examiner")
    parser.add_argument("--no-validate", action="store_true",
                        help="n'exécute aucune passe de validation")
    parser.add_argument("--json-only", action="store_true",
                        help="n'écrit aucun diagnostic sur stderr")
    parser.add_argument("--date-ref", metavar="AAAA-MM-JJ", type=date_ref_valide,
                        default=None,
                        help="date d'appréciation des règles françaises "
                             "(défaut : aujourd'hui)")
    args = parser.parse_args(argv)
    _QUIET = args.json_only
    # Seul endroit du script où l'horloge est lue : à entrées données, la
    # sortie est reproductible.
    date_ref = args.date_ref or __import__("datetime").date.today().isoformat()

    # --json-only tait aussi les diagnostics des bibliothèques tierces (pypdf,
    # lxml, Saxon) : elles écrivent sur sys.stderr, qu'on remplace par un
    # tampon mémoire — jamais par un fichier.
    real_stderr = sys.stderr
    if _QUIET:
        sys.stderr = io.StringIO()

    try:
        # Contrôle du socle avant toute lecture : sans lui, un ImportError
        # remonterait en traceback sur stderr et laisserait stdout vide, ce que
        # le modèle ne saurait pas interpréter.
        manquant = dependances_manquantes()
        if manquant:
            warn("dépendances absentes : %s" % ", ".join(manquant))
            try:
                manifest = load_manifest()
            except Exception:
                manifest = {"fnfe_pack": None, "pack_date": None}
            sys.stderr = real_stderr
            return emettre(missing_dependency_result(args.pdf, manquant, manifest), 1)

        result, code = build(args.pdf, do_validate=not args.no_validate,
                             date_ref=date_ref)
    except Exception as exc:  # filet de sécurité : stdout reste du JSON
        warn("erreur inattendue : %r" % exc)
        manifest_pack = {"fnfe_pack": None, "pack_date": None}
        try:
            manifest_pack = load_manifest()
        except Exception:
            pass
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "unreadable",
            "source": {"file": os.path.basename(args.pdf), "sha256": None,
                       "size_bytes": None},
            "detection": {"method": None, "attachment_name": None,
                          "af_relationship": None, "notes": []},
            "profile": {"id": None, "label": None, "source": None},
            "validation": empty_validation(manifest_pack, "erreur interne : %s" % exc),
            "checks": [{"id": "ERREUR-INTERNE", "severity": "bloquant", "layer": "source",
                        "message": "Le fichier n'a pas pu être traité.",
                        "location": None, "raw": str(exc)}],
            "summary": {"bloquants": 1, "alertes": 0, "conforme_profil": None,
                        "conforme_reforme_fr": None,
                        "verdict": build_verdict("unreadable", None, {}, 1, 0,
                                                 None, None)},
        }
        code = 1
    finally:
        sys.stderr = real_stderr

    return emettre(result, code)


if __name__ == "__main__":
    sys.exit(main())

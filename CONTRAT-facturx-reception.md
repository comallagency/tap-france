# Contrat — `facturx-reception`

Version 1.0 — 20/08/2026
Dépôt : `comallagency/tap-france` · Skill : `skills/finance/facturx-reception/`

Ce document est la **référence normative** de l'implémentation. Le script, les tests et le SKILL.md en découlent. Toute divergence entre le code et ce document est un bug du code.

---

## 1. Principe fondateur

Le script produit des faits. Le modèle les raconte.

- Le script ne lit jamais la couche texte du PDF, ne fait jamais d'OCR, ne devine jamais une valeur absente.
- Le modèle ne recalcule jamais un montant, ne réinterprète jamais un verdict, n'invente jamais un champ manquant.
- Toute valeur absente vaut `null`. `null` est une information, pas un échec.

Conséquence : la skill reste fiable même sur un modèle local faible, puisqu'aucune décision critique ne lui est confiée.

---

## 2. Invocation

```
python3 scripts/facturx_extract.py <chemin.pdf> [--no-validate] [--json-only]
```

- **stdout** : un seul objet JSON, toujours. Rien d'autre.
- **stderr** : diagnostics techniques uniquement (jamais lu par le modèle).
- **Code de sortie `0`** : le script a fait son travail — *y compris si la facture est non conforme*.
- **Code de sortie `1`** : le script n'a pas pu faire son travail (fichier illisible, absent, corrompu).

> Une facture non conforme est un **résultat**, pas une erreur. Confondre les deux casserait l'usage : le cas le plus utile de la skill est précisément de dire « cette facture n'est pas conforme ».

**Contraintes absolues :** aucun appel réseau, aucune écriture disque, aucune variable d'environnement requise.

---

## 3. Représentation des montants

Tous les montants et taux sont des **chaînes de caractères**, reprises telles quelles du XML.

```json
"gross": "1234.56"
```

Jamais de `float` : la virgule flottante binaire fausse les centimes, et sur de la conformité fiscale une erreur d'arrondi détruit la crédibilité de l'outil. Les comparaisons arithmétiques internes se font en `decimal.Decimal`.

---

## 4. Structure de sortie

```json
{
  "schema_version": "1.0",
  "status": "ok",

  "source": {
    "file": "facture.pdf",
    "sha256": "…",
    "size_bytes": 89246
  },

  "detection": {
    "method": "standard",
    "attachment_name": "factur-x.xml",
    "af_relationship": "/Data",
    "notes": []
  },

  "profile": {
    "id": "urn:factur-x.eu:1p0:basicwl",
    "label": "BASIC WL",
    "source": "xml"
  },

  "invoice": {
    "number": "FA-2026-0042",
    "type_code": "380",
    "type_label": "Facture commerciale",
    "issue_date": "2026-08-14",
    "due_date": "2026-09-13",
    "currency": "EUR",
    "buyer_reference": null,
    "order_reference": null,
    "billing_period": { "start": null, "end": null },

    "seller": {
      "name": "…", "siren": null, "siret": null, "vat_id": null,
      "legal_id": null, "country": "FR", "electronic_address": null
    },
    "buyer": {
      "name": "…", "siren": null, "siret": null, "vat_id": null,
      "legal_id": null, "country": "FR", "electronic_address": null
    },

    "totals": {
      "line_net": null, "allowances": null, "charges": null,
      "net": "1000.00", "vat": "200.00", "gross": "1200.00",
      "prepaid": null, "due": "1200.00"
    },

    "vat_breakdown": [
      { "category": "S", "rate": "20.00", "basis": "1000.00",
        "amount": "200.00", "exemption_reason": null }
    ],

    "lines": [],

    "payment": { "means_code": null, "means_label": null, "iban": null, "terms": null }
  },

  "validation": { "…": "voir §6" },
  "checks": [ "…voir §7" ],
  "summary": { "…": "voir §8" }
}
```

### Règles de remplissage

- `lines` est un tableau **vide** (`[]`) pour MINIMUM et BASIC WL — ces profils n'en contiennent pas par construction. Vide ≠ manquant.
- `iban` est `null` par défaut **à tous les profils**. Vérifié empiriquement : présent en BASIC WL, absent d'une facture EN16931 réelle. Ne jamais le présupposer.
- `siren` / `siret` / `vat_id` / `legal_id` sont extraits séparément, jamais déduits l'un de l'autre.

---

## 5. Détection de la pièce jointe

Cascade, dans cet ordre :

1. Pièce jointe avec `AFRelationship` ∈ {`/Data`, `/Alternative`} et MIME XML → `method: "standard"`
2. Sinon, toute pièce jointe XML dont la racine est `rsm:CrossIndustryInvoice` → `method: "fallback"`, plus une entrée dans `detection.notes`
3. Sinon → `status: "unstructured"`

> **`/Alternative` est accepté au même titre que `/Data`.** Vérifié : un PDF EN16931 réel de l'écosystème ZUGFeRD porte `/Alternative`. Un filtre strict sur `/Data` rejetterait des factures valides.

Le nom du fichier n'est **jamais** un critère de détection — seulement une information reportée.

### Détection du profil

Lue dans le XML : `rsm:ExchangedDocumentContext / ram:GuidelineSpecifiedDocumentContextParameter / ram:ID`.

Pas via les métadonnées XMP : les émetteurs les renseignent mal, alors que le XML est la source normative.

| Valeur | `label` |
|---|---|
| `urn:factur-x.eu:1p0:minimum` | MINIMUM |
| `urn:factur-x.eu:1p0:basicwl` | BASIC WL |
| `urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic` | BASIC |
| `urn:cen.eu:en16931:2017` | EN 16931 |
| `urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended` | EXTENDED |

Identifiant inconnu → `label: null`, `status: "ok"`, et un `check` de sévérité `alerte`. On n'échoue pas sur un profil qu'on ne connaît pas encore.

---

## 6. Validation — les cinq passes

```json
"validation": {
  "level": 2,
  "engine": { "saxon": "SaxonC-HE 13.0", "available": true },
  "schemas": { "facturx": "1.09.2", "fnfe_pack": "FR_CTC_V1.4.0.03", "pack_date": "2026-08-04" },
  "passes": [
    { "id": "xsd",            "applied": true,  "status": "pass", "errors": 0 },
    { "id": "profil_fnfe",    "applied": true,  "status": "pass", "errors": 0 },
    { "id": "regles_fr_ctc",  "applied": true,  "status": "fail", "errors": 9 },
    { "id": "alertes_fr",     "applied": true,  "status": "warn", "errors": 9 },
    { "id": "coherence",      "applied": true,  "status": "pass", "errors": 0 }
  ],
  "not_applied": []
}
```

| Passe | Ce qu'elle vérifie | Profils concernés | Niveau |
|---|---|---|---|
| `xsd` | Structure du XML | tous | 1 |
| `profil_fnfe` | Validateur officiel FNFE du profil détecté | BASICWL, EN16931, EXTENDED | 2 |
| `regles_fr_ctc` | Règles métier françaises `BR-FR-*` (réforme) | BASICWL, EN16931, EXTENDED | 2 |
| `alertes_fr` | Jumeaux `_WARNING` des règles françaises | idem | 2 |
| `coherence` | Arithmétique interne en `Decimal` sur ce qui est présent | tous | 1 |

**Chaque passe non exécutée est déclarée** dans `not_applied` avec sa raison :

```json
"not_applied": [
  { "pass": "profil_fnfe", "reason": "aucun validateur officiel FNFE pour le profil MINIMUM" },
  { "pass": "regles_fr_ctc", "reason": "saxonche non installé — installer pour la validation réforme française" }
]
```

### Interdits absolus

- **Ne jamais appliquer le schematron générique EN16931 européen à un profil MINIMUM ou BASIC WL.** Vérifié : cela produit 9 et 13 erreurs sur des factures officielles FNFE parfaitement légales. On utilise le validateur officiel du profil, ou rien.
- **Ne jamais appliquer un validateur d'un profil à un autre profil.**
- Aucun validateur officiel n'existe pour MINIMUM → seules `xsd` et `coherence` s'appliquent, et `not_applied` le dit.

### Niveau 1 vs niveau 2

- **Niveau 1** — `pypdf` + `lxml` seuls. Toujours disponible.
- **Niveau 2** — nécessite `saxonche`. `lxml.isoschematron` est inutilisable ici : les schematrons officiels sont en `queryBinding="xslt2"` et lxml est limité à XSLT 1.0 (échec confirmé en test).

L'absence de `saxonche` n'est jamais une erreur : `level: 1`, passes déclarées non appliquées, et un message d'invitation dans `checks` avec sévérité `info`.

---

## 7. `checks[]` — un item par constatation

```json
{
  "id": "BR-FR-10_BT-30",
  "severity": "bloquant",
  "layer": "regles_fr_ctc",
  "message": "Identifiant légal du vendeur (BT-30) absent — exigé par la réforme française.",
  "location": "/rsm:CrossIndustryInvoice/rsm:SupplyChainTradeTransaction/…",
  "raw": "…texte de l'assertion officielle…"
}
```

**Sévérité — jamais un jugement de notre part :**

| Source | Sévérité |
|---|---|
| `failed-assert` d'un schematron d'erreurs | `bloquant` |
| `failed-assert` / `successful-report` d'un schematron `_WARNING` | `alerte` |
| Échec XSD | `bloquant` |
| Écart arithmétique `coherence` | `bloquant` |
| Information opérationnelle (détection en repli, saxonche absent, profil inconnu) | `info` |

`message` est en **français**, reformulé pour un non-technicien. `raw` conserve le texte officiel d'origine, en anglais, pour traçabilité.

---

## 8. `summary` — ce que le modèle lit en premier

```json
"summary": {
  "bloquants": 9,
  "alertes": 9,
  "conforme_profil": true,
  "conforme_reforme_fr": false,
  "verdict": "Facture valide au format Factur-X BASIC WL, mais non conforme aux règles françaises de la réforme (9 points bloquants)."
}
```

- `conforme_profil` et `conforme_reforme_fr` valent `true`, `false`, **ou `null` si la passe correspondante n'a pas été exécutée.**
- **`null` ne devient jamais `false`.** « Non vérifié » et « non conforme » sont deux choses différentes, et les confondre ferait paniquer un utilisateur à tort — ou le rassurerait à tort.
- `verdict` est une phrase française prête à afficher, générée mécaniquement à partir des compteurs.

---

## 9. Statuts terminaux

| `status` | Signification | Code sortie |
|---|---|---|
| `ok` | XML trouvé et exploité (conforme ou non) | 0 |
| `unstructured` | PDF valide, aucun XML Factur-X — hors périmètre, aucune extraction tentée | 0 |
| `unreadable` | Fichier absent, illisible, chiffré, non-PDF | 1 |
| `invalid_xml` | XML présent mais non parsable | 0 |
| `missing_dependency` | Socle Python absent — rien n'a été lu | 1 |
| `file_not_visible` | Fichier hors du montage du bac à sable — le chemin n'est pas en cause | 1 |

En cas de `unstructured`, le champ `invoice` est **absent**, pas rempli de `null`. La skill ne prétend pas avoir lu ce qu'elle n'a pas lu. Il en va de même pour `invalid_xml` et `missing_dependency`.

### `missing_dependency`

Si `pypdf` ou `lxml` ne s'importent pas, le script ne remonte **jamais** d'`ImportError` ni de trace d'appels : il produit un JSON normal, avec deux champs supplémentaires à la racine.

```json
{
  "status": "missing_dependency",
  "manquant": ["pypdf", "lxml"],
  "remede": "/usr/bin/python3 -m pip install pypdf lxml"
}
```

`remede` cite **l'interpréteur qui exécute réellement le script** (`sys.executable`), jamais un `pip install` générique : le cas d'échec le plus courant est justement d'avoir installé les modules dans un autre interpréteur que celui de l'agent. Un module présent mais cassé est compté comme manquant — le geste à faire est le même.

Le `check` correspondant porte la sévérité `bloquant` et la couche `environnement`.

> **`saxonche` n'entre pas dans ce cas.** Son absence est un mode de fonctionnement normal — `level: 1`, passes déclarées dans `not_applied`, message `info` — et jamais un `missing_dependency`. Confondre les deux transformerait une validation partielle en panne.

### `file_not_visible`

Un fichier absent n'est pas toujours un chemin faux. Quand la skill tourne dans un bac à sable qui n'a pas accès au répertoire de travail de l'utilisateur, le chemin est correct et c'est l'environnement qu'il faut corriger.

Le script tranche sur **trois constats concordants**, jamais sur un seul :

| Indice | Ce qui est observé |
|---|---|
| `conteneur` | `/.dockerenv` existe |
| `skills_montees` | `/root/.hermes/skills` existe, ou le script s'exécute depuis un chemin `…/.hermes/skills/…` |
| `workspace_monte` | `/workspace` existe **et** n'est pas vide |

`file_not_visible` n'est émis que si `conteneur` **et** `skills_montees` sont vrais **et** `workspace_monte` est faux. Un seul indice manquant → `unreadable`.

```json
{
  "status": "file_not_visible",
  "remede": "…passer docker_mount_cwd_to_workspace à true, puis purger les conteneurs hermes-*…",
  "indices": { "conteneur": true, "skills_montees": true, "workspace_monte": false }
}
```

`indices` est publié pour que le diagnostic soit auditable : le lecteur voit sur quoi la conclusion repose.

> **Ne jamais diagnostiquer un montage là où il n'y a qu'une faute de frappe.** Envoyer un utilisateur modifier sa configuration Hermes alors qu'il s'est trompé de nom de fichier lui coûte plus cher que de lui dire « fichier introuvable ». D'où l'exigence des trois indices simultanés.

Le `check` porte la sévérité `bloquant` et la couche `environnement`.

---

## 10. Hors périmètre v1 — explicitement

- Aucune écriture disque, aucun archivage : c'est ce qui rend la skill auditable en dix minutes.
- Aucune émission de facture.
- Aucun OCR, aucune extraction depuis la couche texte.
- Aucun appel à une Plateforme Agréée.
- Aucun traitement de lot.

L'archivage légal fera l'objet d'une skill distincte — la seule du tap autorisée à écrire, donc la seule à auditer de près.

---

## 11. Jeu de tests minimal avant de déclarer la v1 prête

| Cas | Attendu |
|---|---|
| `Facture_FR_MINIMUM.pdf` | `status: ok`, profil MINIMUM, `lines: []`, `profil_fnfe` et `regles_fr_ctc` en `not_applied`, **zéro erreur BR-CO-*** |
| `Facture_FR_BASICWL.pdf` | profil BASIC WL, `profil_fnfe` → 0 erreur, `regles_fr_ctc` → 9 bloquants, IBAN renseigné |
| `pdf_zf_en16931_1.pdf` | profil EN 16931, `af_relationship: "/Alternative"`, `method: "standard"`, `profil_fnfe` → 0 erreur, IBAN `null` |
| PDF sans XML embarqué | `status: unstructured`, pas de champ `invoice`, code 0 |
| Fichier non-PDF | `status: unreadable`, code 1 |
| `saxonche` désinstallé | `level: 1`, 3 passes en `not_applied`, `conforme_reforme_fr: null`, code 0 |

**Test de non-régression n°1 :** la facture MINIMUM ne doit produire aucune erreur `BR-CO-*`. C'est le garde-fou contre la régression la plus grave possible — déclarer non conformes des factures officiellement valides.

---

## 12. Point ouvert bloquant pour la publication

Licence de redistribution des XSLT et schematrons FNFE dans un dépôt MIT. À trancher en lisant `2026_06_30_FNFE_SCHEMATRONS_FR_CTC_V1.4.0.pdf` (fourni dans le pack officiel).

Non bloquant pour développer en local. **Bloquant pour publier le tap.**

Repli si la redistribution est interdite : un script `scripts/fetch_schemas.py` que l'utilisateur exécute une fois pour télécharger les schémas depuis fnfe-mpe.org. Moins pratique, mais légalement propre — et cohérent avec la promesse « zéro appel réseau à l'exécution », le téléchargement étant une étape d'installation explicite, jamais un appel au runtime.

# Contrat — `facturx-reception`

Version 1.0 — 20/08/2026
Dépôt : `comallagency/tap-france` · Skill : `skills/facturx-reception/`

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
                                    [--date-ref AAAA-MM-JJ]
```

`--date-ref` fixe la date à laquelle les règles françaises sont appréciées (défaut : aujourd'hui). C'est le **seul** endroit du script où l'horloge est lue. Voir §7.

- **stdout** : un seul objet JSON, toujours. Rien d'autre.
- **stderr** : diagnostics techniques uniquement (jamais lu par le modèle).
- **Code de sortie `0`** : le script a fait son travail — *y compris si la facture est non conforme*.
- **Code de sortie `1`** : le script n'a pas pu faire son travail (fichier illisible, absent, corrompu).

> Une facture non conforme est un **résultat**, pas une erreur. Confondre les deux casserait l'usage : le cas le plus utile de la skill est précisément de dire « cette facture n'est pas conforme ».

**Contraintes absolues :** aucun appel réseau **à l'exécution**, aucune écriture disque, aucune variable d'environnement requise.

Les schémas de validation ne sont pas redistribués par le dépôt — trop volumineux, et de licence tierce. `skills/facturx-reception/scripts/fetch_schemas.py` les installe en une étape explicite, lancée une fois à la main. Le script de lecture des factures, lui, ne sort jamais de la machine : voir §9, `missing_schemas`.

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

## 6. Validation — les cinq passes déclarées

```json
"validation": {
  "level": 2,
  "engine": { "saxon": "SaxonC-HE 13.0", "available": true },
  "reforme_fr": {
    "date_reference": "2026-08-21", "regime": "avertissement",
    "bascule": "2026-09-01", "jours_avant_bascule": 11
  },
  "schemas": { "facturx": "1.09", "fnfe_pack": "FR_CTC_V1.4.0.03", "pack_date": "2026-08-04" },
  "passes": [
    { "id": "xsd",            "applied": true,  "status": "pass", "errors": 0 },
    { "id": "profil_fnfe",    "applied": true,  "status": "pass", "errors": 0 },
    { "id": "regles_fr_ctc",  "applied": true,  "status": "warn", "errors": 9 },
    { "id": "alertes_fr",     "applied": false, "status": null,   "errors": null },
    { "id": "coherence",      "applied": true,  "status": "pass", "errors": 0 }
  ],
  "not_applied": [ { "pass": "alertes_fr", "reason": "doublon mesuré — voir plus bas" } ]
}
```

Le `status` de `regles_fr_ctc` suit le régime en vigueur : `warn` tant que les règles françaises ne sont que des avertissements, `fail` à partir de la bascule. `errors` ne bouge pas.

| Passe | Ce qu'elle vérifie | Profils concernés | Niveau |
|---|---|---|---|
| `xsd` | Structure du XML | tous | 1 |
| `profil_fnfe` | Validateur officiel FNFE du profil détecté | BASICWL, EN16931, EXTENDED | 2 |
| `regles_fr_ctc` | Règles métier françaises `BR-FR-*` (réforme) | BASICWL, EN16931, EXTENDED | 2 |
| `alertes_fr` | **Jamais exécutée** — doublon mesuré de `regles_fr_ctc` | — | — |
| `coherence` | Arithmétique interne en `Decimal` sur ce qui est présent | tous | 1 |

### Les schematrons jumeaux ne sont pas deux jeux de règles

`BR-FR-Flux2-Schematron-CII.sch` et son jumeau `_WARNING` portent **exactement les mêmes règles**, mêmes identifiants et mêmes expressions `test`. Seuls les distinguent l'attribut `flag` et une ligne d'en-tête, qui donne un calendrier :

| Fichier | En-tête |
|---|---|
| `BR-FR-Flux2-Schematron-CII.sch` | Mode « FATAL » — APPLICABLE EN RECEPTION LE 1ER SEPTEMBRE 2026 |
| `..._WARNING.sch` | Mode « WARNING » — APPLICABLE EN RECEPTION DES LA PUBLICATION ET JUSQU'AU SEPTEMBRE 2026 AU PLUS TARD |

Les exécuter tous les deux comptait **deux fois les mêmes constatations** : neuf points bloquants et neuf alertes, pour neuf problèmes. Un seul est donc exécuté, `regles_fr_ctc`, et `alertes_fr` part dans `not_applied` avec le recouvrement mesuré :

```json
{ "pass": "alertes_fr",
  "reason": "doublon mesuré : même jeu de règles que regles_fr_ctc (229 identifiants d'assertion, recouvrement 229/229, aucun propre à l'une ou l'autre), autre date d'application — mode WARNING jusqu'au 2026-09-01, mode FATAL ensuite" }
```

Le recouvrement est consigné dans `assets/manifest.json`, avec la méthode qui permet de le recalculer depuis les fichiers vendorisés.

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
| `failed-assert` du validateur officiel de profil | `bloquant` |
| `failed-assert` d'une règle française `BR-FR-*`, **avant** le 2026-09-01 | `alerte` |
| `failed-assert` d'une règle française `BR-FR-*`, **à partir** du 2026-09-01 | `bloquant` |
| Échec XSD | `bloquant` |
| Écart arithmétique `coherence` | `bloquant` |
| Information opérationnelle (détection en repli, saxonche absent, profil inconnu) | `info` |

`message` est en **français**, reformulé pour un non-technicien. `raw` conserve le texte officiel d'origine — en anglais pour le validateur de profil, en français pour les règles `BR-FR-*` — pour traçabilité.

### La sévérité des règles françaises est datée

Elle reste lue dans la source, pas décidée par nous : ce sont les en-têtes des deux schematrons qui fixent la date de bascule. Le script porte cette date dans une constante nommée, `BASCULE_REFORME_FR = "2026-09-01"`, documentée par la citation des deux en-têtes.

La date d'appréciation est un **paramètre**, `--date-ref AAAA-MM-JJ`, dont le défaut est le jour courant. C'est le seul endroit du script où l'horloge est lue : à entrées données, la sortie reste reproductible, et les tests épinglent les deux régimes.

> **Ce qui est daté, c'est la sévérité — pas le fait.** Une facture qui échoue aux règles françaises y échoue aujourd'hui comme en octobre. Voir §8.

### Une même constatation peut apparaître deux fois

Les passes ne sont pas étanches : le validateur officiel de profil embarque les règles `BR-CO-*`, que la passe `coherence` recalcule de son côté. Un total TTC faux produit donc **deux `checks`**, un par couche.

C'est voulu et `checks[]` les conserve tous les deux. Deux couches indépendantes qui concluent pareil, c'est une confirmation ; l'une qui conclurait seule serait un signal à examiner. Cette propriété a déjà servi — elle a validé la passe `coherence` contre le validateur officiel sur une facture délibérément faussée.

Les deux occurrences ne portent pas le même `location` : le validateur de profil désigne le bloc des totaux, `coherence` le montant précis. C'est le même problème vu de deux hauteurs, et c'est ce qui permet de les rapprocher — voir §8 bis.

Les montants restent dans `message` **sous leur forme brute**, telle que le XML les porte (§3). La mise en forme française appartient au seul champ `rapport`.

---

## 8. `summary` — ce que le modèle lit en premier

```json
"summary": {
  "bloquants": 0,
  "alertes": 9,
  "conforme_profil": true,
  "conforme_reforme_fr": false,
  "reforme_fr": {
    "date_reference": "2026-08-21",
    "regime": "avertissement",
    "bascule": "2026-09-01",
    "jours_avant_bascule": 11
  },
  "verdict": "Facture valide au format Factur-X BASIC WL, mais non conforme aux règles françaises de la réforme (9 points : avertissements aujourd'hui, bloquants à partir du 1er septembre 2026)."
}
```

- `conforme_profil` et `conforme_reforme_fr` valent `true`, `false`, **ou `null` si la passe correspondante n'a pas été exécutée.**
- **`null` ne devient jamais `false`.** « Non vérifié » et « non conforme » sont deux choses différentes, et les confondre ferait paniquer un utilisateur à tort — ou le rassurerait à tort.
- `verdict` est une phrase française prête à afficher, générée mécaniquement à partir des compteurs.

**`conforme_reforme_fr` ne dépend pas de la date.** La question posée est « cette facture satisfait-elle les règles françaises ? », pas « suis-je sanctionnable aujourd'hui ». Neuf règles en échec valent `false` avant comme après la bascule ; seule leur sévérité change.

`reforme_fr` porte le régime en vigueur à la date d'appréciation, la date de bascule et le nombre de jours restants — `null` une fois la bascule passée. C'est ce qui permet à la réponse de dire : « 9 points — avertissements aujourd'hui, bloquants à partir du 1er septembre 2026. »

Le compte cité par `verdict` est celui des **règles françaises en échec**, pas celui des points bloquants : avant la bascule, ces mêmes constatations sont des avertissements, et « 0 point bloquant » serait absurde.

> **À l'intention des intégrateurs.** En régime d'avertissement, `summary.bloquants` vaut `0` alors même que des règles françaises échouent. Ne jamais lire ce champ seul : il ne dit pas « tout va bien », il dit « rien n'est bloquant à cette date ». Toujours le lire avec `summary.reforme_fr.regime` et `summary.conforme_reforme_fr`. Un tableau de bord qui filtrerait sur `bloquants > 0` afficherait zéro anomalie jusqu'au 31 août 2026, puis les découvrirait toutes le 1er septembre.

---

## 8 bis. `rapport` — le texte que le modèle affiche

Le script assemble lui-même la réponse française finale. Le SKILL.md se réduit alors à une consigne : **affiche le champ `rapport` tel quel**.

```
Facture n° FA-2017-0010 de Au bon moulin, à Ma jolie boutique. 671,15 € TTC
(624,90 € HT + 46,25 € de TVA), émise le 13/11/2017, échéance le 13/12/2017.
Un acompte de 201,00 € a déjà été versé, il reste 470,15 € à payer.

Facture valide au format Factur-X BASIC WL, mais non conforme aux règles
françaises de la réforme (9 points : avertissements aujourd'hui, bloquants à
partir du 1er septembre 2026).

Il reste 11 jours pour les faire corriger, jusqu'au 1er septembre 2026.

- …message du premier check, mot pour mot…
- …un par constatation, dans l'ordre, sans regroupement ni omission…

Ces corrections sont à demander à votre fournisseur : elles concernent la
facture qu'il a émise.
```

Composition, dans cet ordre, chaque bloc étant omis s'il est sans objet :

1. **En-tête de facture** — numéro, parties, montants, dates, acompte, moyen de paiement. Les montants y sont rendus à la française (`671.15` → `671,15 €`) : la virgule décimale remplace le point, aucun chiffre n'est ajouté ni retiré.
2. **Verdict** — `summary.verdict`, sans retouche.
3. **Échéance de la réforme** — trois cas, selon ce que la passe `regles_fr_ctc` a fait, jamais selon la seule date :

   | `regles_fr_ctc` | Ce que le rapport dit |
   |---|---|
   | appliquée, avec constatations | « Il reste N jours pour les faire corriger, jusqu'au 1er septembre 2026. » |
   | appliquée, sans constatation | rien — il n'y a rien à corriger |
   | non appliquée | « La conformité aux règles françaises de la réforme n'a pas été vérifiée. Ces règles deviennent bloquantes le 1er septembre 2026. » |

   Sur un statut terminal, rien non plus : aucune facture n'a été lue.

   > **Jamais de « les » sans antécédent.** Annoncer « il reste 11 jours pour **les** faire corriger » quand aucune règle n'a été évaluée fait croire à des constatations qu'on n'a pas. Le défaut a été trouvé sur un run réel, dans un bac à sable dépourvu de `saxonche`.

4. **Ce qui n'a pas pu être vérifié**, en clair et à sa place — pas en note de bas de texte. L'absence de `saxonche` est une limite du résultat, pas un détail d'installation : elle dit ce qui n'a pas été contrôlé et la commande qui l'active.
5. **Une puce par constatation** `bloquant` ou `alerte`, dans l'ordre de `checks[]`, `message` repris à l'identique.
6. **Phrase de clôture** quand les constatations relèvent de l'émetteur.
7. **`remede`** quand il y en a un.
8. **`À noter :`** pour les constatations `info` restantes, celles qui portent sur la détection.

### Pourquoi le script et non le modèle

Ces règles ont d'abord été écrites en prose dans le SKILL.md, et **le modèle les tenait mal** : sur trois runs à consignes identiques, les neuf messages officiels étaient repris 9 fois, puis 1, puis 6. Fondre deux constatations en une puce fait disparaître une correction à demander ; annoncer « 9 points » et n'en lister que cinq laisse l'utilisateur croire qu'il a tout vu.

Déplacer l'assemblage dans le script transforme une consigne comportementale — invérifiable autrement que par un run, et variable d'un run à l'autre — en une propriété **testée**. C'est le principe fondateur du §1 appliqué jusqu'au bout : le script produit des faits, y compris la phrase qui les raconte.

### Déduplication

Une constatation, une puce. Deux `checks` désignent la même constatation lorsqu'ils portent **le même identifiant de règle** et que **l'un des deux `location` contient l'autre**. Le rapport n'en garde alors qu'un : le plus précis, c'est-à-dire celui dont le chemin est le plus profond, parce que son message nomme la valeur fautive plutôt que d'énoncer la règle en général.

Deux emplacements qui ne se contiennent pas restent **deux** constatations. Les identifiants légaux du vendeur et de l'acheteur relèvent de la même règle `BR-FR-32-LEGALID` ; ce sont deux corrections à demander, et les fondre en ferait disparaître une.

`checks[]` n'est jamais dédupliqué : la règle ne s'applique qu'au rapport.

### Montants

Dans le rapport, et **seulement** dans le rapport, les montants se lisent à la française : la virgule décimale remplace le point, le symbole monétaire est ajouté. `671.15` devient `671,15 €`. Aucun chiffre n'est ajouté ni retiré — c'est un rendu, jamais un arrondi. Un nombre suivi de `%` est un taux : il reçoit la virgule, pas le symbole monétaire.

> **Ce qui est cité entre guillemets est laissé intact.** Un SIREN, un taux de TVA refusé y figurent précisément parce que **leur écriture** est en cause. `« 99999999800010 »` et `« 19.00 »` restent tels quels : les reformater effacerait la faute qu'on signale.

> **Sur un statut terminal, `rapport` se limite au verdict et au remède.** Fichier illisible, hors montage, socle absent, XML non analysable : la phrase de verdict dit déjà tout, et y ajouter des puces ne ferait que la répéter.

`rapport` est présent sur **toutes** les sorties, quel que soit le statut : sans lui, le modèle n'aurait rien à afficher.

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
| `missing_schemas` | Schémas officiels pas encore installés — rien n'a été validé | 1 |

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

### `missing_schemas`

Les schémas officiels ne vivent pas dans le dépôt. Tant qu'ils n'ont pas été installés, le script ne peut valider quoi que ce soit — et il le dit **avant** d'ouvrir le PDF, plutôt que d'échouer au premier fichier manquant.

```json
{
  "status": "missing_schemas",
  "manquant": ["fnfe/BASICWL/BR-FR-Flux2-Schematron-CII.xslt", "…"],
  "remede": "python3 scripts/fetch_schemas.py, depuis la racine du dépôt de la skill, …"
}
```

`manquant` liste les chemins relatifs réellement absents, de sorte qu'une installation partielle se diagnostique aussi bien qu'une absence totale. Même forme que `missing_dependency` : jamais de trace d'appels, toujours la commande exacte.

> **`--no-validate` continue de fonctionner sans schémas.** L'extraction ne dépend d'aucun d'eux ; refuser de la faire serait gratuit.

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

## 12. Licence — plus rien à redistribuer

Les schémas officiels ne sont pas dans le dépôt. `skills/facturx-reception/scripts/fetch_schemas.py` les récupère à l'installation auprès de leurs éditeurs : les XSD chez Akretion (BSD-3-Clause), les validateurs de profil et les règles françaises dans le pack officiel FNFE-MPE.

La question de leur redistribution ne se pose donc plus. Elle s'était posée : le document du pack FNFE énonce une mise à disposition sous Apache 2.0, l'en-tête de certains fichiers source mentionne l'EUPL. Les deux mentions restent citées dans `references/NOTICE.md`, parce qu'un utilisateur qui télécharge ces fichiers a le droit de savoir sous quelles conditions.

Ce choix n'a pas été fait pour éviter la question, mais parce que le scanner de sécurité d'Hermes classe toute skill de plus d'1 Mo comme suspecte — les schémas en pesaient 5,5. Le télécharger explicitement à l'installation coûte une commande et vaut mieux qu'un avertissement à chaque installation.

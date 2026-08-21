---
name: facturx-reception
description: "Factur-X : extrait et valide une facture électronique FR reçue en PDF. À utiliser dès qu'un PDF de facture française est fourni, ou quand on demande si une facture est conforme, valide, aux normes, ou prête pour la réforme de la facturation électronique. Extrait les montants, la TVA, les parties et les échéances depuis le XML structuré embarqué, puis valide contre les schémas officiels Factur-X et les règles françaises BR-FR de la réforme CTC. Ne fait ni OCR ni lecture de texte : uniquement des factures Factur-X structurées."
version: 1.0.0
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Facture, FacturX, TVA, Comptabilite, France, Conformite, EN16931, PDF]
    related_skills: [ocr-and-documents]
---

# Réception de factures Factur-X

Lit une facture électronique française au format Factur-X et dit trois choses : ce qu'elle contient, si elle est valide, et si elle est conforme à la réforme française de la facturation électronique.

## Règle absolue

**Tu n'extrais jamais toi-même la moindre donnée de la facture.**

Tu ne lis pas le PDF. Tu ne regardes pas l'image. Tu ne déduis aucun montant. Tu lances le script, tu lis son JSON, et tu le racontes.

Un montant que tu lirais « à l'œil » sur un PDF serait faux tôt ou tard, et il s'agit ici de conformité fiscale. Le XML embarqué contient les valeurs exactes ; le script les extrait sans interprétation. Si une valeur vaut `null`, elle est absente du fichier — tu dis qu'elle est absente, tu ne la reconstitues pas.

Cette règle vaut aussi pour les verdicts : tu ne décides pas si une facture est conforme, le script te le dit.

**Tu ne reconstruis jamais le script non plus.**

Si tu ne peux pas l'exécuter — introuvable, pas de shell, bac à sable sans le dépôt, dépendances absentes — tu le dis franchement, tu expliques ce qui bloque, et **tu t'arrêtes là**.

Tu ne le réécris pas de mémoire. Tu ne retélécharges pas les schémas XSD ou les schematrons. Tu ne recrées pas l'arborescence de la skill ailleurs. Tu ne bricoles pas une extraction de secours avec `pypdf`.

La raison est la même que pour les montants : un verdict de conformité produit par du code improvisé à la volée est un verdict **non testé**, sur un sujet fiscal, présenté avec l'autorité d'un outil vérifié. C'est plus dangereux qu'une absence de réponse. Une skill qui ne peut pas tourner est un problème d'installation, et il se règle en le signalant — pas en le contournant.

« Je n'ai pas pu exécuter le script, voici pourquoi » est une réponse correcte et complète.

## Quand l'utiliser

- Un PDF de facture est fourni, en particulier française
- On demande si une facture est conforme, valide, « aux normes », prête pour la réforme
- On demande d'extraire montants, TVA, échéance, coordonnées d'un fournisseur depuis une facture
- On demande ce qui manque à une facture pour être conforme

## Quand ne pas l'utiliser

- **Facture scannée, photo, PDF sans XML embarqué** → le script renverra `unstructured` ; utilise `ocr-and-documents` pour ces cas
- **Créer ou émettre** une facture → hors périmètre
- **Relevé bancaire, note de frais, devis** → ce n'est pas une facture Factur-X
- **Rapprochement bancaire** → hors périmètre

## Utilisation

```bash
python3 scripts/facturx_extract.py <chemin.pdf>
```

Options :

| Option | Effet |
|---|---|
| `--no-validate` | Extraction seule, aucune validation (`level: 0`) |
| `--json-only` | Silence total sur stderr |
| `--date-ref AAAA-MM-JJ` | Date d'appréciation des règles françaises (défaut : aujourd'hui) |

Sortie : **un objet JSON sur stdout, rien d'autre**. Code `0` si le script a fait son travail — y compris quand la facture est non conforme. Code `1` seulement si le fichier est illisible.

Une facture non conforme n'est pas une erreur. C'est un résultat, et c'est souvent le plus utile.

Aucun appel réseau à l'exécution, aucune écriture disque, aucune clé d'API. Le seul téléchargement est celui des schémas, à l'installation.

## Lire le JSON

Regarde `summary` en premier. Il contient tout ce qu'il faut pour la première phrase de ta réponse.

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
  "verdict": "…phrase française prête à afficher…"
}
```

**`null` ne veut pas dire « non ».** `conforme_reforme_fr: null` signifie que la vérification n'a pas été faite, pas qu'elle a échoué. Ne transforme jamais un `null` en « non conforme » : tu ferais paniquer quelqu'un à tort. Dis « je n'ai pas pu le vérifier » et regarde `validation.not_applied` pour savoir pourquoi.

**Les règles françaises changent de statut le 1er septembre 2026.** Jusqu'à cette date elles sont des avertissements, à partir de cette date des points bloquants — c'est le calendrier officiel de la réforme, et le même jeu de règles échoue dans les deux cas. `summary.reforme_fr` te donne le régime en vigueur, la date de bascule et les jours restants.

Le champ `rapport` porte déjà cette information, compte à rebours compris : tu n'as rien à en déduire.

Le reste :

- `profile.label` — MINIMUM, BASIC WL, BASIC, EN 16931 ou EXTENDED
- `invoice` — montants (en chaînes, jamais des nombres), parties, dates, TVA, lignes
- `checks[]` — un item par problème, avec `severity` : `bloquant`, `alerte` ou `info`
- `validation.passes` / `validation.not_applied` — ce qui a été vérifié, et ce qui ne l'a pas été

## Présenter le résultat

**Affiche le champ `rapport` tel quel.**

C'est le texte français final, déjà assemblé par le script : la phrase de verdict, le compte à rebours si la bascule n'est pas passée, et une puce par constatation avec les montants. Tu le recopies intégralement, sans rien y ajouter, sans rien en retirer, sans le réordonner.

Tu ne le résumes pas, tu ne le reformules pas, tu ne le raccourcis pas. Ces règles étaient autrefois écrites ici en prose et le modèle les tenait mal ; elles sont maintenant appliquées par le script, où un test les vérifie. Ton travail se limite à afficher.

Le reste du JSON — `invoice`, `checks`, `validation` — est là si on te pose une question précise ensuite. Pour la première réponse, `rapport` suffit et se suffit.

**Les données se citent littéralement, la structure ne se cite jamais.**

Cette règle vaut pour tout ce que tu écris **autour** du rapport, et pour les questions de suite. Les données — montants, taux, dates, numéro, parties, IBAN, messages de règles — se reprennent **exactement** comme le JSON les fournit : jamais arrondies, jamais reformulées. Le vocabulaire de structure — noms de champs, `true` / `false` / `null`, syntaxe d'accès — ne sort jamais de ta réponse.

| | |
|---|---|
| ✅ | « 671,15 € TTC (46,25 € de TVA) » |
| ❌ | « environ 671 € TTC » — arrondi, la donnée est perdue |
| ❌ | « `totals.gross` vaut "671.15" » — vocabulaire de structure |
| ✅ | « La facture n'est pas conforme aux règles françaises de la réforme. » |
| ❌ | « `conforme_reforme_fr` vaut `false`. » |
| ✅ | « La conformité aux règles françaises n'a pas pu être vérifiée. » |
| ❌ | « Le champ est à `null`. » |

Autrement dit : le JSON est ta **source**, jamais ton **vocabulaire**.

**Ta réponse commence par le premier caractère du rapport et se termine par le dernier. Rien avant, rien après : ni salutation, ni annonce, ni commentaire, ni conclusion.**

Avant d'envoyer, regarde ton premier caractère et ton dernier : ce sont ceux du rapport, ou ta réponse est fausse. « Voici le résultat », « Script exécuté avec succès », « J'espère que cela vous aide » — rien de tout cela n'a sa place, et une seule de ces lignes suffit à trahir la mécanique à quelqu'un qui n'a demandé que l'état de sa facture.

La seule exception est celle de la règle absolue : si tu **n'as pas pu** exécuter le script, tu le dis franchement et tu expliques ce qui bloque. Un échec se raconte, une réussite ne se raconte pas.

### À quoi ressemble un rapport

Sortie réelle du champ `rapport` sur `tests/fixtures/Facture_FR_BASICWL.pdf`, le 21/08/2026. C'est exactement ce que tu affiches — rien de plus.

> Facture n° FA-2017-0010 de Au bon moulin, à Ma jolie boutique. 671,15 € TTC (624,90 € HT + 46,25 € de TVA), émise le 13/11/2017, échéance le 13/12/2017. Un acompte de 201,00 € a déjà été versé, il reste 470,15 € à payer. Paiement par virement (IBAN FR2012421242124212421242124).
>
> Facture valide au format Factur-X BASIC WL, mais non conforme aux règles françaises de la réforme (9 points : avertissements aujourd'hui, bloquants à partir du 1er septembre 2026).
>
> Il reste 11 jours pour les faire corriger, jusqu'au 1er septembre 2026.
>
> - La facture ne porte pas la mention obligatoire sur l'indemnité forfaitaire de 40 € pour frais de recouvrement, due entre professionnels en cas de retard de paiement. Elle doit figurer parmi les notes de la facture : à faire ajouter par votre fournisseur.
> - La facture ne porte pas la mention obligatoire sur les pénalités de retard de paiement (leur taux, ou le renvoi aux conditions générales de vente). Elle doit figurer parmi les notes de la facture : à faire ajouter par votre fournisseur.
> - La facture n'indique pas les conditions d'escompte en cas de paiement anticipé — ni, à défaut, qu'aucun escompte n'est accordé. L'une ou l'autre mention est obligatoire parmi les notes de la facture.
> - La facture ne précise pas son cas d'usage : le code qui dit s'il s'agit d'un dépôt direct, d'un mandat de facturation, d'une facture de solde, etc. La réforme française le rend obligatoire ; c'est le logiciel de facturation de votre fournisseur qui doit le renseigner.
> - Le SIREN du vendeur doit comporter exactement 9 chiffres ; celui de cette facture en compte 14 chiffres : « 99999999800010 ». C'est presque toujours le SIRET, long de 14 chiffres, saisi à la place du SIREN. À faire corriger par votre fournisseur.
> - L'adresse électronique de l'acheteur est absente. C'est l'identifiant auquel vous recevez vos factures électroniques — souvent votre SIREN, parfois une adresse dédiée — et la réforme l'exige pour acheminer la facture jusqu'à vous. Communiquez-le à votre fournisseur.
> - L'adresse électronique du vendeur est absente. C'est l'identifiant qui permet de reconnaître l'émetteur de la facture sur la plateforme, et la réforme l'exige. À faire renseigner par votre fournisseur dans son logiciel de facturation.
> - L'identifiant légal du vendeur est annoncé comme un SIREN mais en compte 14 chiffres au lieu de 9 : « 99999999800010 ». C'est presque toujours un SIRET, long de 14 chiffres, saisi à la place du SIREN. À faire corriger par l'émetteur de la facture.
> - L'identifiant légal de l'acheteur est annoncé comme un SIREN mais en compte 14 chiffres au lieu de 9 : « 78787878400035 ». C'est presque toujours un SIRET, long de 14 chiffres, saisi à la place du SIREN. À faire corriger par l'émetteur de la facture.
>
> Ces corrections sont à demander à votre fournisseur : elles concernent la facture qu'il a émise.

Les valeurs citées sont celles de cette facture-là ; celles de la tienne seront différentes.

## Pièges

**Une facture MINIMUM ou BASIC WL n'a pas de lignes.** `lines: []` est normal, ce n'est pas une donnée manquante. Ne dis jamais « les lignes de facture sont absentes » : ces profils n'en portent pas, par construction.

**Une facture peut être parfaitement conforme à la norme européenne EN 16931 et échouer les règles françaises.** Ce sont deux couches distinctes, et c'est le cas le plus fréquent. Ne les confonds pas dans ta réponse : `conforme_profil` et `conforme_reforme_fr` répondent à deux questions différentes.

**L'IBAN est souvent absent, à tous les profils.** Ce n'est pas une anomalie.

**Les montants sont des chaînes.** `"1200.00"`, pas `1200.0`. Ne les convertis pas en nombres, tu introduirais des erreurs d'arrondi sur des centimes.

**Le résultat ne dépend pas du modèle.** Si on te demande de « revérifier », relance le script — ne rejoue pas le raisonnement de mémoire.

**Tu ne conseilles pas juridiquement.** Tu rapportes ce que disent les règles officielles. Pour une question de droit fiscal, oriente vers un expert-comptable.

## Vérification

Avant de répondre, contrôle que :

1. Chaque montant que tu cites figure littéralement dans le JSON
2. Tu n'as affiché aucun identifiant de règle ni contenu de `raw`
3. Tu n'as pas écrit « non conforme » là où la valeur était `null`
4. Tu as distingué la conformité au profil de la conformité à la réforme française

Si tu ne peux pas cocher les quatre, relis le JSON plutôt que de compléter au jugé.

## Installation

Deux commandes, et la skill est complète :

```bash
python3 -m pip install pypdf==6.16.1 lxml==6.1.2 saxonche==13.0.0
python3 scripts/fetch_schemas.py
```

La seconde télécharge les schémas officiels, qui ne sont pas redistribués avec la skill. Tant qu'ils manquent, le script renvoie `status: missing_schemas` et la commande exacte — il n'échoue jamais en cours de route.

C'est celle-là qu'il faut exécuter. **N'en installe pas la moitié** : sans `saxonche`, le script tourne encore, mais il ne vérifie plus les règles françaises de la réforme — c'est-à-dire ce pour quoi la skill existe. Ce mode dégradé est décrit plus bas ; ce n'est pas une option de même rang.

**Installe dans l'interpréteur que tu utilises réellement, pas dans un venv de projet.** C'est l'erreur la plus fréquente : les modules sont bien installés quelque part, mais pas là où le script tourne, et il échoue quand même. Si tu as un doute, demande au script lui-même — en cas de socle manquant il renvoie `status: missing_dependency` et un champ `remede` contenant la commande exacte, construite avec le chemin de l'interpréteur qui vient d'échouer. Exécute cette commande-là, telle quelle.

### Le mode dégradé, si `saxonche` manque quand même

Les schematrons officiels sont en XSLT 2.0, que `lxml` ne sait pas exécuter. Sans `saxonche`, le script ne s'arrête pas : il passe en `level: 1`, déclare les passes non exécutées, et le rapport dit en clair que la conformité à la réforme n'a pas été vérifiée. Ce n'est **pas** un `missing_dependency`, et le script ne rend jamais d'erreur pour cette raison.

Mais ce n'est pas le fonctionnement normal. Un run réel s'est déroulé ainsi — le modèle avait lu deux commandes d'installation et n'en avait exécuté qu'une — et la facture est ressortie sans qu'aucune règle française ne soit contrôlée. D'où la commande unique ci-dessus.

## Provenance des schémas

Tous les fichiers de validation sont embarqués dans la skill et lus localement. Aucun téléchargement à l'exécution.

- XSD des cinq profils Factur-X : `akretion/factur-x`, BSD-3-Clause
- Validateurs de profil et règles françaises BR-FR : pack officiel FNFE-MPE FR CTC, Apache 2.0

Détail complet dans `schemas/NOTICE.md`, versions dans `schemas/manifest.json`.

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

Sortie : **un objet JSON sur stdout, rien d'autre**. Code `0` si le script a fait son travail — y compris quand la facture est non conforme. Code `1` seulement si le fichier est illisible.

Une facture non conforme n'est pas une erreur. C'est un résultat, et c'est souvent le plus utile.

Aucun réseau, aucune écriture disque, aucune clé d'API.

## Lire le JSON

Regarde `summary` en premier. Il contient tout ce qu'il faut pour la première phrase de ta réponse.

```json
"summary": {
  "bloquants": 9,
  "alertes": 9,
  "conforme_profil": true,
  "conforme_reforme_fr": false,
  "verdict": "…phrase française prête à afficher…"
}
```

**`null` ne veut pas dire « non ».** `conforme_reforme_fr: null` signifie que la vérification n'a pas été faite, pas qu'elle a échoué. Ne transforme jamais un `null` en « non conforme » : tu ferais paniquer quelqu'un à tort. Dis « je n'ai pas pu le vérifier » et regarde `validation.not_applied` pour savoir pourquoi.

Le reste :

- `profile.label` — MINIMUM, BASIC WL, BASIC, EN 16931 ou EXTENDED
- `invoice` — montants (en chaînes, jamais des nombres), parties, dates, TVA, lignes
- `checks[]` — un item par problème, avec `severity` : `bloquant`, `alerte` ou `info`
- `validation.passes` / `validation.not_applied` — ce qui a été vérifié, et ce qui ne l'a pas été

## Présenter le résultat

Réponds en français simple, à quelqu'un qui ne connaît pas Factur-X.

**Structure :** le verdict d'abord, l'essentiel de la facture ensuite, les problèmes en dernier.

Reprends le champ `message` de chaque check tel quel — il est déjà rédigé pour un non-technicien. **N'affiche jamais les identifiants de règle** (`BR-FR-10_BT-30`) ni le contenu de `raw` sauf si on te les demande explicitement : ils sont là pour la traçabilité, pas pour l'utilisateur.

Les montants se citent tels qu'ils apparaissent dans le JSON. Tu ne les recalcules pas, tu n'en additionnes pas, tu n'en convertis pas.

**Une puce par constatation.** Jamais deux constatations dans la même puce. Jamais de constatation omise. Le nombre de puces est égal au nombre de points bloquants annoncé — si tu annonces 9, tu écris 9 puces. Interdiction d'écrire « dont », « notamment », « entre autres » ou toute formule annonçant une liste partielle.

Compte tes puces avant d'envoyer. Deux constatations regroupées « parce qu'elles se ressemblent » en font disparaître une : sur une facture, deux identifiants légaux faux ne sont pas un problème, ce sont deux corrections à demander.

**Les données se citent littéralement, la structure ne se cite jamais.**

Les données — montants, taux, dates, numéro, parties, IBAN, et les `message` des `checks` — se reprennent **exactement** comme le JSON les fournit : jamais arrondies, jamais reformulées. Le vocabulaire de structure — noms de champs, `true` / `false` / `null`, syntaxe d'accès — ne sort jamais de ta réponse.

| | |
|---|---|
| ✅ | « 671,15 € TTC (46,25 € de TVA) » |
| ❌ | « environ 671 € TTC » — arrondi, la donnée est perdue |
| ❌ | « `totals.gross` vaut "671.15" » — vocabulaire de structure |
| ✅ | « La facture n'est pas conforme aux règles françaises de la réforme. » |
| ❌ | « `conforme_reforme_fr` vaut `false`. » |
| ✅ | « La conformité aux règles françaises n'a pas pu être vérifiée. » |
| ❌ | « Le champ est à `null`. » |

Autrement dit : le JSON est ta **source**, jamais ton **vocabulaire**. Tu en recopies les valeurs au caractère près, et tu n'en montres jamais la forme.

Exemple de bonne réponse. Les puces sont des copies **exactes** du champ `message` des `checks` — mot pour mot, ponctuation comprise. Ne les résume pas, ne les raccourcis pas, ne les reformule pas : c'est ce que fait cet exemple, et c'est ce que tu fais.

> Facture n° FA-2017-0010 de Au bon moulin, à Ma jolie boutique. 671,15 € TTC (624,90 € HT + 46,25 € de TVA), émise le 13/11/2017, échéance le 13/12/2017. Un acompte de 201,00 € a déjà été versé, il reste 470,15 € à payer.
>
> Le fichier est un Factur-X valide au profil BASIC WL. **En revanche, il ne respecte pas encore les règles françaises de la réforme.** 9 points bloquants :
>
> - La facture ne porte pas la mention obligatoire sur l'indemnité forfaitaire de 40 € pour frais de recouvrement, due entre professionnels en cas de retard de paiement. Elle doit figurer parmi les notes de la facture : à faire ajouter par votre fournisseur.
>
> - La facture ne porte pas la mention obligatoire sur les pénalités de retard de paiement (leur taux, ou le renvoi aux conditions générales de vente). Elle doit figurer parmi les notes de la facture : à faire ajouter par votre fournisseur.
>
> - La facture n'indique pas les conditions d'escompte en cas de paiement anticipé — ni, à défaut, qu'aucun escompte n'est accordé. L'une ou l'autre mention est obligatoire parmi les notes de la facture.
>
> - La facture ne précise pas son cas d'usage : le code qui dit s'il s'agit d'un dépôt direct, d'un mandat de facturation, d'une facture de solde, etc. La réforme française le rend obligatoire ; c'est le logiciel de facturation de votre fournisseur qui doit le renseigner.
>
> - Le SIREN du vendeur doit comporter exactement 9 chiffres ; celui de cette facture en compte 14 chiffres : « 99999999800010 ». C'est presque toujours le SIRET, long de 14 chiffres, saisi à la place du SIREN. À faire corriger par votre fournisseur.
>
> - L'adresse électronique de l'acheteur est absente. C'est l'identifiant auquel vous recevez vos factures électroniques — souvent votre SIREN, parfois une adresse dédiée — et la réforme l'exige pour acheminer la facture jusqu'à vous. Communiquez-le à votre fournisseur.
>
> - L'adresse électronique du vendeur est absente. C'est l'identifiant qui permet de reconnaître l'émetteur de la facture sur la plateforme, et la réforme l'exige. À faire renseigner par votre fournisseur dans son logiciel de facturation.
>
> - L'identifiant légal du vendeur est annoncé comme un SIREN mais en compte 14 chiffres au lieu de 9 : « 99999999800010 ». C'est presque toujours un SIRET, long de 14 chiffres, saisi à la place du SIREN. À faire corriger par l'émetteur de la facture.
>
> - L'identifiant légal de l'acheteur est annoncé comme un SIREN mais en compte 14 chiffres au lieu de 9 : « 78787878400035 ». C'est presque toujours un SIRET, long de 14 chiffres, saisi à la place du SIREN. À faire corriger par l'émetteur de la facture.
>
> Ces corrections sont à demander à votre fournisseur : elles concernent la facture qu'il a émise.

Cet exemple est reproductible : c'est la sortie réelle du script sur `tests/fixtures/Facture_FR_BASICWL.pdf`. Les valeurs qu'il cite viennent de cette facture-là — celles de la tienne seront différentes.

**Cas particuliers**

| Situation | Ce que tu dis |
|---|---|
| `status: unstructured` | Le PDF ne contient pas de facture électronique structurée — c'est un PDF classique. Propose `ocr-and-documents` pour une lecture approximative, en précisant qu'aucune validation de conformité n'est alors possible. |
| `status: unreadable` | Le fichier n'a pas pu être ouvert. Demande à vérifier le chemin ou le fichier. |
| `status: invalid_xml` | Le XML Factur-X est bien là, mais illisible : **aucune donnée n'est exploitable**. Le fichier est probablement corrompu ou mal généré par le logiciel de l'émetteur ; c'est à lui de le signaler et de le réémettre. Dis exactement cela et rien de plus. **N'improvise rien** : pas de montant, pas de nom, pas de verdict de conformité. Aucune valeur ne t'a été fournie, et tu ne peux pas en produire une seule. C'est le cas où la tentation de compenser est la plus forte — n'y cède pas. |
| `status: missing_dependency` | Le script n'a pas pu se lancer : une bibliothèque Python lui manque. Le fichier n'a pas été lu du tout. Donne à l'utilisateur la commande exacte du champ `remede` — elle vise le bon interpréteur — puis propose de relancer. Ne conclus rien sur la facture. |
| `status: file_not_visible` | Le chemin est probablement bon : c'est ton bac à sable qui n'a pas accès au dossier de l'utilisateur. **Ne lui dis pas de vérifier son chemin**, il y perdrait son temps. Donne la manipulation du champ `remede` — configuration Hermes puis purge des conteneurs — et précise que les deux étapes sont nécessaires. Ne conclus rien sur la facture. |
| `level: 1` | Tu as extrait et validé la structure, mais **pas** la conformité à la réforme française. Indique que `saxonche` permet cette vérification, sans insister. |
| `profil_fnfe` en `not_applied` pour MINIMUM | Normal, et à expliquer : aucun validateur officiel n'existe pour ce profil. Ce n'est ni un échec ni une lacune de l'outil. |
| `detection.method: "fallback"` | Le XML a été trouvé par un chemin non standard. Le résultat reste exploitable, mais signale-le : le fichier de l'émetteur s'écarte de la norme. |
| 0 bloquant, alertes seulement | Dis-le clairement : la facture est conforme, les alertes sont des recommandations. |

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

Le socle, obligatoire — sans lui le script ne peut rien lire :

```bash
python3 -m pip install pypdf lxml
```

La validation contre les règles françaises de la réforme nécessite en plus :

```bash
python3 -m pip install saxonche
```

**Installe-les dans l'interpréteur que tu utilises réellement, pas dans un venv de projet.** C'est l'erreur la plus fréquente : les modules sont bien installés quelque part, mais pas là où le script tourne, et il échoue quand même. Si tu as un doute, demande au script lui-même — en cas de socle manquant il renvoie `status: missing_dependency` et un champ `remede` contenant la commande exacte, construite avec le chemin de l'interpréteur qui vient d'échouer. Exécute cette commande-là, telle quelle.

Les schematrons officiels sont en XSLT 2.0, que `lxml` ne sait pas exécuter. Sans `saxonche`, le script fonctionne normalement en `level: 1` et déclare les passes non exécutées — il n'échoue jamais pour cette raison, et ce n'est **pas** un `missing_dependency`.

## Provenance des schémas

Tous les fichiers de validation sont embarqués dans la skill et lus localement. Aucun téléchargement à l'exécution.

- XSD des cinq profils Factur-X : `akretion/factur-x`, BSD-3-Clause
- Validateurs de profil et règles françaises BR-FR : pack officiel FNFE-MPE FR CTC, Apache 2.0

Détail complet dans `schemas/NOTICE.md`, versions dans `schemas/manifest.json`.

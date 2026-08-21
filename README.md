# tap-france

**Des skills françaises pour agents IA. Première du lot : la conformité des factures électroniques à la réforme.**

```bash
hermes skills tap add comallagency/tap-france
```

---

## Le problème

L'obligation de **réception** s'applique à toutes les entreprises assujetties à la TVA en France **à partir du 1er septembre 2026**. L'obligation d'**émission**, elle, est échelonnée : grandes entreprises et ETI à la même date, PME, TPE et micro-entreprises au 1er septembre 2027.

La loi de finances pour 2026 a durci les sanctions : **50 € par facture** non émise au format électronique, plafonnés à 15 000 € par année civile ; et, pour une entreprise qui ne peut pas recevoir ses factures, une mise en demeure puis des amendes de **500 € puis 1 000 € par trimestre**.

Ce README n'est pas un guide juridique : les modalités exactes sont sur [entreprendre.service-public.gouv.fr](https://entreprendre.service-public.gouv.fr/vosdroits/F23208).

Et voici ce que presque personne n'a vu venir :

> **Une facture peut être parfaitement conforme au format Factur-X et rester non conforme à la réforme française.**

Ce ne sont pas les mêmes règles. Le format relève de la norme européenne EN 16931. La réforme française y ajoute sa propre couche, les règles `BR-FR-*`, publiées par la FNFE-MPE.

Nous l'avons mesuré sur les **factures d'exemple officielles de la FNFE elles-mêmes** :

| Facture d'exemple officielle | Validateur de profil | Règles françaises |
|---|---|---|
| `Facture_FR_BASICWL.pdf` | 0 erreur | **9 constatations** |
| `Facture_FR_MINIMUM.pdf` | (aucun validateur officiel) | — |

Ces exemples sont antérieurs aux exigences de la réforme : c'est normal, et ce n'est pas un reproche à la FNFE. Mais ça illustre exactement le piège. Un outil qui annonce « conforme Factur-X » peut dire vrai et laisser son utilisateur en infraction.

Ce qui manquait sur ces factures, notamment : le SIREN du vendeur, les adresses électroniques des parties, le code du cas d'usage, les mentions obligatoires sur les pénalités de retard et l'indemnité de recouvrement. Rien d'exotique — les champs que la réforme exige.

## Ce que fait la skill

Vous donnez un PDF à votre agent. Il répond :

```
Facture n° FA-2017-0010 de Au bon moulin, à Ma jolie boutique. 671,15 € TTC (624,90 € HT + 46,25 € de TVA), émise le 13/11/2017, échéance le 13/12/2017. Un acompte de 201,00 € a déjà été versé, il reste 470,15 € à payer. Paiement par virement (IBAN FR2012421242124212421242124).

Facture valide au format Factur-X BASIC WL, mais non conforme aux règles françaises de la réforme (9 points : avertissements aujourd'hui, bloquants à partir du 1er septembre 2026).

Il reste 11 jours pour les faire corriger, jusqu'au 1er septembre 2026.

- Le SIREN du vendeur doit comporter exactement 9 chiffres ; celui de cette facture en compte 14 chiffres : « 99999999800010 ». C'est presque toujours le SIRET, long de 14 chiffres, saisi à la place du SIREN. À faire corriger par votre fournisseur.
- L'adresse électronique de l'acheteur est absente. C'est l'identifiant auquel vous recevez vos factures électroniques — souvent votre SIREN, parfois une adresse dédiée — et la réforme l'exige pour acheminer la facture jusqu'à vous. Communiquez-le à votre fournisseur.

…
```

En français, sans jargon, avec ce qu'il faut demander à qui. Pas d'identifiants de règles à décoder.

**Les cinq profils Factur-X** sont reconnus et extraits : MINIMUM, BASIC WL, BASIC, EN 16931, EXTENDED.

La profondeur de validation, elle, dépend de ce que la FNFE publie. Le validateur officiel de profil n'existe que pour **BASIC WL, EN 16931 et EXTENDED** ; MINIMUM et BASIC sont couverts par le schéma XSD et les contrôles arithmétiques. Le rapport dit toujours ce qui a été vérifié et ce qui ne l'a pas été — il ne laisse jamais croire à un contrôle qui n'a pas eu lieu.

S'y ajoutent les **règles françaises de la réforme** et **la sévérité datée** selon le calendrier officiel.

## Installation

```bash
hermes skills tap add comallagency/tap-france
python3 -m pip install pypdf lxml saxonche
```

Sans `saxonche`, la skill fonctionne en mode dégradé : elle extrait et valide le format, mais **ne vérifie pas la conformité à la réforme française** — c'est-à-dire l'essentiel de ce pour quoi elle existe. Elle vous le dit explicitement plutôt que de vous laisser croire que tout va bien.

**Installez par copie, jamais par lien symbolique.** Un seul lien dans l'arborescence des skills fait basculer tout l'arbre vers une copie assainie côté Hermes, et la skill liée disparaît silencieusement du bac à sable. Nous l'avons appris à nos dépens.

La skill est un dossier contenant un `SKILL.md` et ses scripts — un format de fichiers, pas un exécutable lié à un agent particulier.

## Pourquoi vous pouvez l'installer sans crainte

Une skill qui lit vos factures est la plus sensible qui soit. Des audits publics ont trouvé des skills malveillantes dans certains registres. La méfiance est saine — voici de quoi la lever :

- **Aucun accès réseau à l'exécution.** Zéro. Aucun import de `urllib`, `requests` ou `socket` dans le script. Vérifiez-le.
- **Aucune écriture disque.** La skill lit, analyse, répond. Elle ne déplace, ne copie et n'archive rien.
- **Aucune clé, aucun compte, aucun service tiers.** Vos factures ne quittent jamais votre machine.
- **Un seul script**, plus des schémas officiels embarqués. Comptez une heure pour l'auditer de bout en bout — il fait 2 344 lignes, commentées.
- **Aucun `curl | bash`**, aucune dépendance exotique : `pypdf`, `lxml`, `saxonche`.

## Le principe : le code décide, le modèle raconte

Un modèle de langage ne doit jamais lire un montant sur une facture. Il finira par en halluciner un, et sur de la conformité fiscale une seule erreur détruit la confiance.

Ici, **rien de critique ne passe par le modèle** :

- Les montants viennent du XML structuré embarqué dans le PDF. Pas d'OCR, pas de lecture de la couche texte, pas d'interprétation.
- Les verdicts viennent des schémas et schematrons **officiels**, exécutés localement.
- Le texte de la réponse est **assemblé par le script**. Le modèle l'affiche.

Conséquence directe : **la skill fonctionne aussi bien sur un petit modèle local que sur un modèle frontière.** Ce que le modèle ne décide pas, il ne peut pas le rater.

## Deux suites de tests, parce qu'il y a deux risques

Le premier risque est que le code se trompe. Une suite unitaire classique le couvre — plus de 150 tests sur les cinq profils, les cas dégradés, l'arithmétique, les régimes de date.

Le second risque est **que le modèle n'obéisse pas**, et aucune suite unitaire ne le voit. C'est là que ce projet a le plus dérapé : sur une même facture, avec des consignes strictement identiques et à quelques minutes d'intervalle, le modèle a reproduit fidèlement les constatations **1 fois sur 9**, puis **6 fois sur 9**. Tous les tests étaient verts.

D'où `tests/verif_comportement.py` : il prend la réponse d'un agent, relance le script, compare, et signale toute ligne manquante, ajoutée, reformulée ou déplacée. Il est lui-même testé contre des réponses volontairement abîmées — un détecteur non éprouvé rassure sans garantir, ce qui est pire que pas de détecteur.

Ce qu'il a déjà attrapé en conditions réelles : un préambule ajouté en anglais, et un faux positif de sa propre part qu'il a fallu corriger.

## Ce que la skill ne fait pas

- **Elle ne remplace pas une Plateforme Agréée.** À terme, une facture devra transiter par une PA ; cette skill analyse un fichier, elle ne le transmet pas.
- **Elle ne lit pas les PDF scannés.** Sans XML embarqué, elle le dit et s'arrête plutôt que de deviner.
- **Elle n'émet pas de factures.** Pas encore.
- **Elle n'archive rien.** Ce sera une skill distincte, la seule du tap autorisée à écrire.
- **Elle ne donne pas de conseil juridique.** Elle rapporte ce que disent les règles officielles.

## Écosystème

[`paperasse`](https://github.com/romainsimon/paperasse) couvre la **génération** de factures françaises et la documentation des obligations. Ce tap couvre la **réception** et la validation contre les schematrons officiels. Les deux se complètent plutôt qu'ils ne se concurrencent.

## Provenance et licences

Le code de ce dépôt est sous licence MIT.

Les schémas embarqués ne le sont pas :

- **XSD des cinq profils Factur-X** — [`akretion/factur-x`](https://github.com/akretion/factur-x), BSD-3-Clause
- **Validateurs de profil et règles françaises** — pack officiel FNFE-MPE FR CTC

Le document du pack FNFE annonce une mise à disposition libre sous Apache 2.0, tandis que l'en-tête de certains fichiers source mentionne l'EUPL. **Cette ambiguïté n'est pas levée.** Elle est documentée, citations à l'appui, dans [`skills/finance/facturx-reception/schemas/NOTICE.md`](skills/finance/facturx-reception/schemas/NOTICE.md), et doit être tranchée avec la FNFE avant toute publication.

En repli, `scripts/fetch_schemas.py` récupère les schematrons XSLT auprès de la FNFE et les XSD auprès d'Akretion, à l'installation, plutôt que de les embarquer dans le dépôt.

Nous préférons afficher un doute que le taire.

## Feuille de route

| Skill | État |
|---|---|
| `facturx-reception` | disponible |
| Suivi des échéances, doublons, anomalies de prix | prévu |
| Récapitulatif de TVA mensuel | prévu |
| E-mail de correction au fournisseur | prévu |
| Traitement par lot et export comptable | prévu |
| `facturx-emission` — générer une facture conforme, prouvée par les mêmes validateurs | prévu |
| Archivage légal | prévu |

## Contribuer

Les retours sur de vraies factures sont ce qui a le plus de valeur ici. Une facture qui passe alors qu'elle ne devrait pas, ou l'inverse, fait avancer le projet plus qu'une fonctionnalité.

Ouvrez une issue — sans joindre la facture, un fichier de facture contient des données personnelles et commerciales.

## Qui maintient ce dépôt

[ComAll](https://comallagency.com), agence de développement, également éditrice de [Hermes Agent France](https://hermesagentfrance.com) — un agent IA géré, prêt à l'emploi, où ces skills sont préinstallées.

Ce tap est et restera gratuit et open source, utilisable avec n'importe quel agent, hébergé où vous voulez.

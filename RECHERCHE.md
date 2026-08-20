# Recherche — Skill Hermes Agent de réception de factures Factur-X

Date : 2026-08-20
Périmètre : recherche et analyse uniquement, aucun code écrit, aucune implémentation proposée.
Hermes Agent v0.19.1 installé localement (`~/.hermes/`).

Convention utilisée dans tout le document : **[VÉRIFIÉ]** = source lue/consultée directement (par moi ou par un agent de recherche dédié qui a cité l'URL exacte). **[SUPPOSÉ]** = déduction raisonnable ou source secondaire non recoupée avec un texte primaire — à confirmer avant de coder dessus.

---

## 1. État de l'art concurrentiel

### 1.1 Méthode

Deux canaux distincts ont été interrogés :
- **Registre local Hermes** (`hermes skills search <terme>` et `hermes skills inspect <id>`), qui agrège skills.sh, ClawHub, browse-sh et d'autres sources — exécuté directement dans l'environnement de l'utilisateur.
- **Recherche web** (GitHub, agentskills.io, skills.sh, dépôts officiels Hermes/OpenClaw) via un agent de recherche dédié.

Limite commune aux deux canaux : l'absence de résultat n'est pas une preuve d'absence totale (moteurs de recherche internes non interrogeables de façon exhaustive, ClawHub notamment).

### 1.2 Recherche locale — `hermes skills search`

Commandes exécutées : `hermes skills search facture|facturx|invoice|tva`.

**[VÉRIFIÉ]** Aucun résultat pour `facturx` seul (0 résultat, "No skills found matching your query").

**[VÉRIFIÉ]** Trois trouvailles significatives sur ClawHub (registre communautaire, licence "Interne — usage privé OpenClaw" pour toutes les trois — donc **non open source**, contrairement à notre projet) :

| Skill | Identifiant | Ce qu'elle fait vraiment | Concurrence-t-elle notre projet ? |
|---|---|---|---|
| **E-facture rapprochement** | `e-facture-rapprochement` | Pipeline complet **factures + relevés bancaires → rapprochement bancaire**. Ingère Factur-X/UBL/CII "en fast-path" (préféré) puis bascule sur extraction LLM avec score de confiance pour tickets de caisse / PDF non structurés. Le vrai travail est fait par `scripts/main.py` (`invoice_parsers.py`, `bank_parsers.py`) ; le rapprochement lui-même est délégué à un moteur partagé (`rapprochement-paiements`). Sortie contractuelle : `company.json` + `rapprochement.json`. | **Chevauchement partiel important.** Même format cible (Factur-X/UBL/CII), même principe déterministe ("ne réimplémente jamais le moteur à la main"), mais objectif final différent : rapprochement bancaire multi-clients, pas réception/validation stricte EN 16931 d'une facture isolée. Ne semble pas faire de validation Schematron/EN16931 — le XML CII est une source d'extraction rapide parmi d'autres (fast-path), pas l'objet d'une validation de conformité. |
| **Analyse pièce comptable** | `analyse-piece-comptable` | Analyse **une seule** pièce comptable isolée (facture, relevé, note de frais), lecture seule, extrait montants/TVA/dates/émetteur, signale incohérences (TVA fausse, total qui ne tombe pas juste, IBAN invalide, date aberrante). Extraction faite par `scripts/analyse.py` (déterministe), le modèle ne fait qu'en rendre compte. | **Chevauchement architectural fort, chevauchement fonctionnel partiel.** Le principe "script déterministe fait le calcul, le modèle présente" est identique au nôtre. Mais c'est un outil générique multi-documents (facture OU relevé OU note de frais), pas spécialisé Factur-X : rien n'indique une extraction du XML CII embarqué dans un PDF/A-3, ni une validation contre le schéma EN 16931/Schematron — l'extraction semble reposer sur la couche texte du PDF, avec un mode dégradé explicite si le PDF est scanné sans texte. |
| **Facture Make** | `facture-make` | Génère une facture professionnelle et l'envoie vers Make.com après confirmation. | **Non pertinent** — sens inverse (émission, pas réception) et pas de rapport avec Factur-X/EN16931. |

**[VÉRIFIÉ]** Recherche `tva` : aucun résultat pertinent (Agentvault, PromptVault, Dotnet Expert, Empire Builder, Iaiops — tous hors sujet, faux positifs sur le terme "tva").

**[VÉRIFIÉ]** Recherche `invoice` : ~25 résultats, essentiellement génération/envoi de factures anglo-saxonnes (GitHub JSON invoices, "invoice-automation", "invoice-chase", "invoice-generator", "invoice-organizer" indexés depuis `claude-office-skills` et `anthropics/knowledge-work-plugins` via skills.sh) — aucun ne mentionne Factur-X, EN 16931, CII ou la réforme française. Ce sont des outils de facturation générique anglophone, pas de conformité réglementaire française.

**[VÉRIFIÉ]** Index local des skills Hermes déjà installées/bundlées (`~/.hermes/.skills_prompt_snapshot.json`, `~/.hermes/skills/.bundled_manifest`) : recherche `factur|invoice|tva` → **0 occurrence**. Aucune des skills officielles bundlées avec Hermes (apple, autonomous-ai-agents, creative, email, github, media, mlops, note-taking, productivity, research, smart-home, social-media, software-development) ne traite la facturation.

### 1.3 Recherche web (agent dédié)

**[VÉRIFIÉ]** Découverte principale : **`romainsimon/paperasse`** (github.com/romainsimon/paperasse), 2334 étoiles / 173 forks, dernier push 10/08/2026, licence MIT, installable via `agentskill.sh`. Sa skill `comptable` déclare gérer "facturation (mentions obligatoires, numérotation, Factur-X/UBL/CII, plateformes agréées PDP/PA, e-reporting, réforme 2026, PEPPOL)" et contient `references/facturation/formats-facturx.md`.
- Architecture proche de la nôtre : `scripts/generate-facturx.js` (génération) + `scripts/validate-facture.js` (validation), séparés.
- Limite vérifiée en lisant le code : `validate-facture.js` ne compare qu'à une liste JSON de mentions légales obligatoires — **aucune trace de validation Schematron/XSD EN 16931** (recherche de "BR-", "Schematron", "EN16931" dans le fichier : zéro résultat).
- **Aucun script de réception/extraction d'un Factur-X tiers** — c'est un outil de **génération sortante**, l'inverse de notre cas d'usage (réception).
- Verdict : chevauchement partiel (même écosystème, même sujet, direction opposée) ; acteur actif et populaire à surveiller, une extension vers la réception/validation stricte est plausible à moyen terme.

**[VÉRIFIÉ]** `causa-prima-ai/scribo-skill` (github.com/causa-prima-ai/scribo-skill) : package Claude Code/Codex, 7 étoiles, dernier commit 26/06/2026. Livre ZUGFeRD/XRechnung (Allemagne) et PDF US ; **Factur-X (France) annoncé "coming soon", non livré**. Valide via un **appel HTTP à une API cloud externe**, pas via script local déterministe — architecture opposée à la contrainte "zéro appel réseau" de notre projet. À surveiller (roadmap explicitement tournée vers la France) mais non pertinent aujourd'hui.

**[VÉRIFIÉ]** Catalogue officiel Hermes Agent (`github.com/NousResearch/hermes-agent/tree/main/skills` + `optional-skills-catalog.md`) : catégories Finance/Payments existantes ne couvrent que modélisation financière (DCF, LBO, comps…) et paiements machine-to-machine (Stripe, MPP) — **aucune mention Factur-X/EN16931/CII/UBL/TVA**.

**[VÉRIFIÉ]** OpenClaw officiel (`openclaw/openclaw/skills`) : rien de spécifique à la facturation électronique dans les noms de dossiers visibles ; la skill `nano-pdf` n'a pas pu être auditée en détail (404 lors de l'exploration).

**[VÉRIFIÉ]** `skills.sh` parcouru directement (278 skills au moment du fetch) : aucun résultat pour invoice/facture/Factur-X/EN16931/CII/UBL/TVA. `agentskills.io` n'est pas un registre indexé de skills tierces mais une page de spécification/vitrine. ClawHub (`github.com/openclaw/clawhub`) : aucun résultat via recherche web ciblée, mais moteur de recherche interne non interrogeable depuis l'extérieur — cohérent avec le fait que les 3 skills trouvées localement (§1.2) ne sont apparues que via la recherche **locale** `hermes skills search`, pas via le web.

**[VÉRIFIÉ]** Bibliothèques techniques Factur-X (pas des skills IA, pas de `SKILL.md`) recensées à titre de contexte : `akretion/factur-x`, `invoice-x/factur-x-ng`, `atgp/factur-x` (PHP), `Virgile-Dauge/facturix`, Mustang Project (Java). Ne concurrencent pas directement une skill mais peuvent servir de brique technique à un futur concurrent — voir aussi §3.

### 1.4 Verdict global

**Partiellement occupé, pas saturé.**

- Sur la **génération** de Factur-X et la vérification des mentions légales, un acteur populaire existe (`paperasse`, MIT, 2300+ étoiles) mais sans validation sémantique EN 16931.
- Sur le **rapprochement bancaire** exploitant Factur-X comme source rapide, un acteur privé (non open source) existe dans l'écosystème OpenClaw/ClawHub local (`e-facture-rapprochement`), avec un principe architectural proche du nôtre (script déterministe + moteur partagé) mais un objectif différent (rapprochement, pas validation de conformité).
- Sur l'**analyse déterministe d'une pièce comptable isolée avec le modèle qui ne fait que présenter**, un acteur privé existe aussi (`analyse-piece-comptable`) — c'est le principe architectural le plus proche du nôtre trouvé à ce jour, mais générique (pas de traitement dédié au XML CII embarqué ni de Schematron EN 16931).
- **Aucune skill trouvée, ni localement ni sur le web, ne fait spécifiquement** : extraction fiable du XML CII embarqué dans un PDF/A-3 Factur-X + validation double passe XSD puis Schematron EN 16931 (règles BR-*) + présentation du résultat par le modèle sans jamais recalculer un montant. C'est le créneau exact du projet, non occupé à ce jour d'après cette recherche — mais adjacent à trois acteurs actifs (`paperasse`, `e-facture-rapprochement`, `analyse-piece-comptable`) capables de s'y étendre.

---

## 2. Spécification technique Factur-X

Sources principales utilisées par l'agent de recherche : FNFE-MPE (fnfe-mpe.org, éditeur officiel français du standard), le dépôt `ConnectingEurope/eInvoicing-EN16931` (schematron officiel EN 16931 maintenu par le programme CEF de la Commission européenne), le dépôt `akretion/factur-x` (référence technique communautaire), BOFiP (doctrine fiscale officielle DGFiP), service-public.gouv.fr.

### 2.1 Profils Factur-X

**[VÉRIFIÉ]** Source : https://fnfe-mpe.org/factur-x/factur-x_en/ — 5 profils, du plus simple au plus complet :

**MINIMUM → BASIC WL → BASIC → EN 16931 → EXTENDED**

| Profil | Contenu garanti [SUPPOSÉ pour le détail exact des champs, recoupé sur plusieurs sources secondaires convergentes — non lu directement dans le document FNFE-MPE] |
|---|---|
| **MINIMUM** | N° facture, date, devise, montant total TTC, identifiants vendeur/acheteur. **Pas de ventilation TVA, pas de lignes de facture, pas de coordonnées bancaires garanties.** Équivalent à un en-tête de facture pour rapprochement CHORUS PRO. |
| **BASIC WL** ("Without Lines") | Ajoute : mode de paiement (BT-81), total HT lignes, total HT, total TVA, total TTC, ventilation TVA par taux. **Toujours pas de lignes de facture ni d'IBAN garanti.** |
| **BASIC** | BASIC WL + lignes de facture détaillées (désignation, quantité, prix unitaire, montant net, catégorie TVA par ligne — BG-25). |
| **EN 16931** (dit aussi COMFORT/COMFORT) | Couvre l'intégralité du socle sémantique de la norme européenne : ajoute remises/charges document (BG-20/BG-21), référence bon de commande (BT-13), période de facturation (BG-14), et tous les champs conditionnellement obligatoires EN 16931. C'est le **profil de référence légal** pour la conformité. |
| **EXTENDED** | EN 16931 + champs métier additionnels (remises/charges multi-niveaux, logistique, douane, incoterms). Marqué "under construction" par FNFE-MPE au moment de la recherche. |

**[SUPPOSÉ / NON CONFIRMÉ]** IBAN (BT-84, groupe BG-16 "Payment instructions") : présent dans le modèle sémantique EN 16931 dès lors que le moyen de paiement est un virement, mais aucune confirmation officielle FNFE-MPE trouvée précisant à partir de quel profil (BASIC WL ou EN16931) sa présence devient réellement garantie. **Recommandation pour l'implémentation : ne jamais présupposer la présence d'un IBAN avant le profil EN16931, et le traiter comme optionnel même à ce niveau.**

**Zone d'incertitude signalée par l'agent de recherche** : le nombre exact de champs par profil (chiffres du type "25/45/60/160/200+" vus sur des blogs tiers) n'a pas été recoupé avec un document officiel FNFE-MPE consulté directement — à ne pas utiliser comme donnée dure. **Action recommandée avant codage : télécharger manuellement le pack "Factur-X 1.08" (XSD + Schematron + doc) depuis fnfe-mpe.org/factur-x/ pour obtenir la matrice de champs exacte par profil.**

### 2.2 Embarquement du XML dans le PDF et extraction fiable

**[VÉRIFIÉ]** Source : https://github.com/akretion/factur-x/blob/master/README.rst
- Le PDF conteneur doit être conforme **PDF/A-3** (seule variante PDF/A autorisant l'attachement de fichiers non-PDF/A).
- Le XML est attaché via le mécanisme **Embedded File Specification** du PDF, avec `AFRelationship = /Data` (pas `/Alternative` — distinction importante pour ne pas confondre avec une pièce jointe accessoire).
- Des métadonnées **XMP** dédiées au schéma d'extension `urn:factur-x.eu:1p0` indiquent le profil (`ConformanceLevel`), la version et le nom du fichier attaché.

**[VÉRIFIÉ]** Méthode d'extraction robuste recommandée : ne **jamais** se fier au nom du fichier attendu — parcourir l'arbre `/Names/EmbeddedFiles` du PDF et filtrer par `AFRelationship=/Data` + type MIME `application/xml`. L'outil CLI `facturx-pdfextractxml` (paquet `factur-x` d'Akretion) gère déjà cette robustesse : noms de fichiers non conformes, arborescences avec `/Kids`, compatibilité ZUGFeRD 1.0, bug historique des caractères `#` dans les IDs de fichiers XML (corrigé).

### 2.3 Nom du fichier XML attendu

**[VÉRIFIÉ]** Nom standard imposé (Factur-X/ZUGFeRD 2.1+) : **`factur-x.xml`**. Source : https://gflohr.github.io/e-invoice-eu/en/docs/e-invoice-formats/factur-x-zugferd/, corroboré par le README `akretion/factur-x`.

**[VÉRIFIÉ]** Variantes historiques rencontrées (héritage, toujours supportées en lecture par les outils communautaires) :
- ZUGFeRD 1.x : `ZUGFeRD-invoice.xml`
- ZUGFeRD 2.x avant 2.1 : `zugferd-invoice.xml`
- XRechnung (CIUS allemand) : `xrechnung.xml`

**[NON CONFIRMÉ]** Aucune source fiable trouvée listant des noms de fichiers non conformes observés chez de vrais émetteurs français en production. À traiter comme un risque connu mais non quantifié — **conséquence pour l'implémentation : ne jamais dépendre du nom de fichier comme critère de détection, uniquement de l'attribut `AFRelationship=/Data` + MIME XML.**

### 2.4 Règles de validation métier

**[VÉRIFIÉ]** Lu directement dans le schematron officiel EN 16931 : https://github.com/ConnectingEurope/eInvoicing-EN16931/blob/master/ubl/schematron/abstract/EN16931-model.sch

- **BR-CO-10** : Σ montants nets des lignes (BT-131) = total net des lignes (BT-106).
- **BR-CO-13** : Total HT (BT-109) = Σ montants nets de ligne − Σ remises document (BT-107) + Σ charges document (BT-108).
- **BR-CO-15** : Total TTC (BT-112) = Total HT (BT-109) + Total TVA (BT-110) — *règle centrale de cohérence HT + TVA = TTC*.
- **BR-CO-17** : Montant TVA par catégorie (BT-117) = base taxable (BT-116) × taux (BT-119) / 100, arrondi 2 décimales.
- **BR-CO-18** : au moins un groupe de ventilation TVA (BG-23) obligatoire.
- **BR-S-08 / BR-S-09** : pour chaque taux "Standard rated", la base taxable de la ventilation doit correspondre à la somme des lignes concernées, et le montant TVA = base × taux.

**[VÉRIFIÉ]** Processus de validation en deux passes obligatoires : **XSD d'abord** (validité structurelle) **puis Schematron** (règles métier BR-*) — la validité XSD seule ne garantit pas la conformité EN 16931.

### 2.5 Schematron officiel — où le trouver

**[VÉRIFIÉ]** https://github.com/ConnectingEurope/eInvoicing-EN16931/ — fichiers `EN16931-CII-validation.sch` (syntaxe CII, celle utilisée par Factur-X) et `EN16931-model.sch` (partie abstraite commune UBL/CII). Licence EUPL 1.2.

**[VÉRIFIÉ, contenu détaillé non extrait]** FNFE-MPE distribue aussi un pack XSD/Schematron adapté aux 5 profils Factur-X ("pack Factur-X 1.08") via https://fnfe-mpe.org/factur-x/implementer-factur-x/ — source la plus officielle pour la France, mais son contenu détaillé n'a pas pu être ouvert par l'agent (résumé de page insuffisant). **À télécharger manuellement avant implémentation.**

### 2.6 Les 4 nouvelles mentions obligatoires au 1er septembre 2026

**[VÉRIFIÉ]** Source : https://www.service-public.gouv.fr/entreprendre/vosdroits/F31808
1. **Numéro SIREN du client** (quand il s'agit d'une entreprise assujettie).
2. **Adresse de livraison des biens**, si différente de l'adresse du client.
3. **Nature des opérations facturées** : précision livraison de biens / prestation de services / les deux.
4. Mention **"Option pour le paiement de la taxe d'après les débits"**, si le prestataire a opté pour ce régime.

**[SUPPOSÉ]** Base légale citée par plusieurs sources secondaires convergentes mais **non vérifiée directement sur Légifrance** (page d'accueil renvoyée au lieu du texte) : Décret n° 2022-1299 du 7 octobre 2022, article 242 nonies A de l'annexe II du CGI. **[NON CONFIRMÉ]** Sanction de 15 €/erreur plafonnée à 25 % du montant facturé (une seule source secondaire, RECOV).

### 2.7 Règles d'archivage

**[VÉRIFIÉ]** Source BOFiP officielle DGFiP : https://bofip.impots.gouv.fr/bofip/8865-PGP.html/identifiant=BOI-TVA-DECLA-30-20-30-20-20180207 et https://bofip.impots.gouv.fr/bofip/8862-PGP.html/identifiant=BOI-TVA-DECLA-30-20-30-10-20180207
- Trois garanties exigées pendant toute la durée de conservation : **authenticité de l'origine, intégrité du contenu, lisibilité** — assurables via piste d'audit fiable (PAF), signature électronique qualifiée, ou EDI.
- Lisibilité garantie pendant **au moins 10 ans**.

**[SUPPOSÉ, recoupement de sources secondaires uniquement]** Durée totale de 10 ans = cumul Code de commerce art. L.123-22 (pièces comptables, 10 ans) + Livre des procédures fiscales art. L.102 B (délai de reprise fiscal, 6 ans) — non vérifié directement sur Légifrance.

**[SUPPOSÉ / déduction raisonnable, non confirmé par un texte DGFiP explicite]** Une facture Factur-X doit être archivée dans son **format d'origine** — le PDF/A-3 avec XML embarqué, pas le XML seul extrait, ni une impression papier — sous peine de perdre soit la lisibilité (XML seul), soit la valeur probante des données structurées (impression). Corroboré par plusieurs sources secondaires (Pennylane, comparateur-efacturation.fr) mais pas par un texte primaire DGFiP lu directement.

**[NON CONFIRMÉ]** Norme NF Z42-013 / ISO 14641 mentionnée par des sources secondaires comme référence d'archivage à valeur probante — non vérifiée directement.

---

## 3. Écosystème Python

Contrainte impérative rappelée : **aucune dépendance ne doit faire d'appel réseau au runtime**, le script tournant dans `~/.hermes/` sans garantie de connectivité.

### 3.1 Comparatif

| Bibliothèque | Licence | Maintenance | Dépendances | Validation | Appel réseau ? |
|---|---|---|---|---|---|
| **`factur-x`** (Akretion, PyPI) | BSD-3-Clause [VÉRIFIÉ] | Très active — dernier commit/release v6.8 le 18/08/2026, 303★ [VÉRIFIÉ] | `lxml`, `pypdf≥5.3.0`, `python-stdnum`, **`requests`** (obligatoire, transitive `urllib3`/`certifi`/`idna`/`charset_normalizer`) [VÉRIFIÉ] | XSD embarqués (tous profils), validation Schematron disponible | **XSD : offline** [VÉRIFIÉ]. **Schematron : appelle un serveur externe "Saxon Server"** (`requests.post` vers `http://localhost:5000/transform` par défaut, configurable à distance) **+ fetch réseau par défaut du "CodeDB" sur raw.githubusercontent.com**, mais uniquement si `check_schematron=True` est appelé explicitement [VÉRIFIÉ, code lu] |
| **`drafthorse`** (pretix, PyPI) | Apache-2.0 (schémas XSD sous licence FeRD redistribués) [VÉRIFIÉ] | Semi-active — release 2025.2.0 (15/09/2025), dernier push juin 2026, le README avertit d'un temps de réponse potentiellement long [VÉRIFIÉ] | **Uniquement `lxml` et `pypdf`** [VÉRIFIÉ] | XSD embarqués localement (MINIMUM → EXTENDED + XRechnung) via `lxml.etree.XMLSchema`. **Pas de Schematron** (pas de règles BR-*) [VÉRIFIÉ] | **Aucun trouvé** dans les fichiers centraux [VÉRIFIÉ sur les fichiers principaux, SUPPOSÉ pour l'exhaustivité du dépôt] |
| **`pypdf`** | BSD-3-Clause [VÉRIFIÉ] | Très active, releases quasi hebdomadaires, v6.16.1 (14/08/2026) [VÉRIFIÉ] | Aucune obligatoire (juste `typing_extensions` si Python < 3.11) [VÉRIFIÉ] | N/A — extraction seule, API dédiée `reader.attachments` | Aucun [VÉRIFIÉ] |
| **`pikepdf`** | MPL-2.0 [VÉRIFIÉ] | Active, v10.12.0 (17/08/2026) [VÉRIFIÉ] | `Pillow`, `lxml`, `packaging` + binaire C++ qpdf embarqué (wheel plus lourd) [VÉRIFIÉ] | N/A — extraction seule | Aucun [VÉRIFIÉ] |
| **`lxml`** | BSD-3-Clause [VÉRIFIÉ] | — | — | `lxml.etree.XMLSchema` (XSD local) + `lxml.isoschematron` (Schematron compilé en XSLT, **exécuté localement, sans service externe**) [VÉRIFIÉ] | Aucun par défaut (`no_network` actif par défaut) [VÉRIFIÉ ; comportement exact si le XSD référence un import par URL absolue : SUPPOSÉ, non testé empiriquement] |

### 3.2 Recommandation

**[Position de l'agent de recherche, à valider par l'équipe]**

- **Extraction** : `pypdf` seul — pure Python, zéro dépendance obligatoire, API dédiée aux pièces jointes (`reader.attachments`), aucune capacité réseau.
- **Éviter `factur-x` pour la simple extraction** : l'installer importerait `requests` (+ `urllib3`/`certifi`/`idna`) de façon transitive et obligatoire, même si l'appel réseau lui-même reste opt-in (`check_schematron=True` non appelé). Surface de dépendance jugée inutile pour un besoin de lecture pure.
- **Validation XSD** : soit `lxml.etree.XMLSchema` + XSD vendorisés localement dans le dépôt du projet (copiés depuis `drafthorse/schema/` ou le pack FNFE-MPE), soit `drafthorse` complet (zéro dépendance réseau dans tout son arbre).
- **Validation Schematron (règles BR-*, EN 16931)** : **ne pas utiliser** `factur-x.xml_check_schematron()` (dépend d'un serveur Saxon externe + fetch réseau par défaut). Utiliser `lxml.isoschematron` avec les fichiers `.sch` officiels vendorisés depuis `ConnectingEurope/eInvoicing-EN16931` — validation purement locale via XSLT.
- **Combinaison minimale proposée** : `pypdf` (extraction) + `lxml` (validation XSD et Schematron via `isoschematron`) + schémas EN16931/Factur-X officiels **vendorisés dans le dépôt du projet** (pas de dépendance runtime à `factur-x` ni `drafthorse`).
- **Option stdlib pure** (zlib + `re` pour parser manuellement `/EmbeddedFile`/`/Filespec`) jugée **réaliste en théorie mais déconseillée** : trop de cas limites du format PDF (xref streams, object streams, chiffrement, mises à jour incrémentales) pour rester fiable ; `pypdf` est déjà pur Python, donc tout aussi déterministe/portable, pour un risque bien moindre.

---

## 4. Conventions de skill (lecture locale)

Fichiers lus directement, chemins WSL :
- `~/.hermes/skills/software-development/hermes-agent-skill-authoring/SKILL.md` — la skill Hermes officielle qui documente elle-même les conventions d'auteur de skills.
- `~/.hermes/skills/productivity/google-workspace/SKILL.md`, `~/.hermes/skills/productivity/google-workspace/scripts/google_api.py`
- `~/.hermes/skills/productivity/ocr-and-documents/SKILL.md`, `~/.hermes/skills/productivity/ocr-and-documents/scripts/extract_pymupdf.py`

### 4.1 Frontmatter YAML

Champs obligatoires (validés par `tools/skill_manager_tool.py::_validate_frontmatter`, source citée dans `hermes-agent-skill-authoring`) :
- Le fichier **commence** par `---` (aucune ligne vide avant, pas de BOM).
- Se ferme par `\n---\n` avant le corps.
- `name` (minuscules, tirets, ≤ 64 caractères) et `description` (≤ 1024 caractères) présents.
- **Les 57 premiers caractères de `description` sont seuls affichés dans l'index du prompt système** — le reste n'est visible que via `skills_list()`/`skill_view()`. D'où la convention observée : commencer la description par "Use when …" (ou en français : la formulation observée chez `analyse-piece-comptable` et `e-facture-rapprochement` liste des déclencheurs concrets dès la première phrase).
- Corps non vide après le frontmatter.

Champs non enforced mais présents chez tous les pairs observés : `version`, `author`, `license`, `metadata.hermes.tags`, `metadata.hermes.related_skills`. `google-workspace` ajoute en plus `platforms: [linux, macos, windows]` et un bloc `required_credential_files` (chemin + description) pour déclarer ses besoins en identifiants.

### 4.2 Structure de dossier

```
skills/<catégorie>/<nom-skill>/
├── SKILL.md
├── references/       # docs bulky ou branch-specific, chargées à la demande seulement
├── scripts/           # code exécuté par le modèle, jamais réimplémenté à la main
└── templates/, assets/  # optionnels
```

Observé concrètement : `google-workspace` a `references/gmail-search-syntax.md` + `scripts/{setup.py, google_api.py, gws_bridge.py, _hermes_home.py}` ; `ocr-and-documents` a uniquement `scripts/{extract_pymupdf.py, extract_marker.py}` (pas de `references/`, tout est dans le corps du SKILL.md car le sujet est plus compact).

Deux arborescences distinctes selon le contexte de la skill (précisé dans `hermes-agent-skill-authoring`) :
1. **User-local** : `~/.hermes/skills/<catégorie>/<nom>/SKILL.md` — créée via l'outil `skill_manage(action='create')`.
2. **In-repo** (skill versionnée, livrée avec un dépôt) : `<repo>/skills/<catégorie>/<nom>/SKILL.md` — créée via écriture de fichier directe + `git add`, PAS via `skill_manage(action='create')`.

Pour une skill open source destinée à être publiée/partagée (notre cas), c'est le schéma **in-repo** qui s'applique : le dossier `skills/<catégorie>/<nom>/` doit vivre dans le dépôt Git du projet, pas dans `~/.hermes/skills/`.

### 4.3 Limites de taille

- Description : ≤ 1024 caractères (enforced).
- SKILL.md complet : ≤ 100 000 caractères (enforced, ~36k tokens). Les pairs observés dans `software-development/` visent **8-15k caractères** ; au-delà de ~20k, la convention est de déporter le contenu dans `references/*.md`.

### 4.4 Comment un script est invoqué

Convention observée dans les deux skills lues :
- Scripts Python autonomes avec shebang `#!/usr/bin/env python3`, docstring d'usage en tête de fichier listant les invocations possibles (`ocr-and-documents/scripts/extract_pymupdf.py`).
- Invocation en ligne de commande depuis le SKILL.md, jamais réimplémentée par le modèle : `python scripts/extract_pymupdf.py document.pdf --markdown`.
- Le SKILL.md documente explicitement la **raison** de passer par le script plutôt que par le modèle — retrouvé mot pour mot chez le concurrent local `analyse-piece-comptable` : *"L'extraction des montants, numéros et dates est déterministe et déjà éprouvée. La faire "à l'œil" [...] produit des valeurs incohérentes."* C'est la même justification architecturale que celle voulue pour notre skill Factur-X.

### 4.5 Comment les erreurs sont remontées

Convention observée dans `google_api.py` et `extract_pymupdf.py` :
- **Sortie normale : JSON sur stdout**, systématiquement via `json.dumps(..., indent=2, ensure_ascii=False)` — jamais de texte libre pour un résultat structuré.
- **Erreur : message sur stderr + `sys.exit(1)`** (ou `sys.exit(result.returncode or 1)` quand le script encapsule un sous-processus externe comme `gws`).
- Le modèle est censé lire ce JSON/code de sortie et le traduire en langage naturel pour l'utilisateur — jamais recalculer ou réinterpréter les valeurs lui-même. C'est exactement le principe voulu pour la skill Factur-X ("le modèle ne fait que présenter le résultat").
- Le concurrent local `analyse-piece-comptable` suit le même contrat : `python3 scripts/analyse.py <fichier> --date-ref <AAAA-MM-JJ>` renvoie un JSON unique sur stdout avec des champs `null` explicites ("jamais inventé") plutôt qu'une erreur silencieuse, et une liste `checks[]` avec sévérité (`bloquant | alerte | info`) — un modèle de sortie directement réutilisable pour notre propre script de validation Factur-X.

---

## 5. Jeux de test

**[VÉRIFIÉ]** Sources identifiées, par ordre de complétude pour couvrir les 5 profils en PDF prêts à l'emploi (pas seulement XML) :

1. **`horstoeko/zugferd`** (bibliothèque PHP tierce) — https://github.com/horstoeko/zugferd/tree/master/tests/assets — la source la plus complète en PDF réels : `pdf_fx_minimum_1.pdf` (MINIMUM), `pdf_zf_en16931_1/2/3.pdf` (EN16931), `pdf_fx_extended_1.pdf` / `pdf_zf_extended_1.pdf` (EXTENDED), `pdf_zf_xrechnung_1.pdf` (XRechnung).
2. **`ZUGFeRD/corpus`** (dépôt officiel de l'organisation GitHub ZUGFeRD, allemande, partenaire technique historique de FNFE-MPE) — https://github.com/ZUGFeRD/corpus — sous-dossier `ZUGFeRDv2/correct/FNFE-factur-x-examples/` = **miroir direct des exemples officiels FNFE-MPE** : `Facture_FR_MINIMUM.pdf`, `Facture_DOM_MINIMUM.pdf`, `Facture_UE_MINIMUM.pdf` (MINIMUM) ; `Facture_FR_BASICWL.pdf` + variantes (BASIC WL) ; `Avoir_FR_type381_BASIC.pdf` (BASIC, avoir). Pas de PDF EN16931/EXTENDED dans ce sous-dossier précis. Sous-dossier `ZUGFeRDv2/correct/Mustangproject/` : 3 PDF réels + XML de test (profils non étiquetés).
3. **FNFE-MPE officiel** — https://fnfe-mpe.org/wp-content/uploads/2026/07/FR_and_ENG_XP_Z12-012_Annexes_A_et_B_EXEMPLES_V1.4.zip — **[VÉRIFIÉ que le fichier existe]** (zip volumineux, >10 Mo, confirmé par l'échec de fetch typique d'un vrai binaire) mais **contenu détaillé non inspecté**. Zip additionnel `2026_08_04_FNFE_SCHEMATRONS_FR_CTC_V1.4.0.03.zip` = schematrons/XSD des profils EN16931 et EXTENDED-CTC-FR (utile en complément, pas des exemples PDF). **[SUPPOSÉ]** La page produit Factur-X de fnfe-mpe.org mentionne des exemples "dans tous les profils" (France + Allemagne) mais l'URL exacte de ce lien n'a pas pu être extraite — à vérifier manuellement.
4. **`akretion/factur-x`** (bibliothèque Python de référence) — https://github.com/akretion/factur-x/tree/master/tests/fixtures — `pdf/invoice_EN16931.pdf` (un seul PDF, profil EN16931) ; dossier `xml/` avec XML seuls pour tous les profils (`factur-x-minimum.xml`, `-basicwl.xml`, `-basic.xml`, `-en16931.xml`, `-extended.xml` + équivalents `zugferd-*.xml`) — utiles pour générer ses propres PDF de test mais pas des PDF prêts à l'emploi.
5. **Portails officiels français** (impots.gouv.fr, PPF/AIFE) : **[SUPPOSÉ]** aucun jeu d'exemples PDF direct trouvé — ces portails renvoient vers FNFE-MPE pour la spécification technique.

**Recommandation de l'agent de recherche** : combiner `horstoeko/zugferd/tests/assets` (MINIMUM, EN16931, EXTENDED) + `ZUGFeRD/corpus/FNFE-factur-x-examples` (MINIMUM, BASIC WL, BASIC) pour une couverture complète des 5 profils en PDF réels, et télécharger le zip officiel FNFE-MPE en complément pour disposer de la source la plus autorisée (contenu à inspecter manuellement).

---

## Zones d'incertitude

1. **Matrice exacte des champs garantis par profil** (§2.1) — les chiffres vus (nombre de champs par profil) proviennent de blogs tiers non recoupés avec le document officiel FNFE-MPE, dont le contenu détaillé n'a pas pu être ouvert par la recherche automatisée.
2. **Présence garantie de l'IBAN** (§2.1) — pas de confirmation officielle du profil à partir duquel BT-84 devient réellement garanti.
3. **Base légale exacte des 4 mentions 2026** (§2.6) — décret n° 2022-1299 cité par plusieurs sources secondaires convergentes mais jamais lu directement sur Légifrance (accès bloqué pendant la recherche).
4. **Montant de la sanction** pour mention manquante (§2.6) — vu sur une seule source secondaire, non recoupé.
5. **Obligation explicite d'archiver le PDF/A-3 complet plutôt que le XML seul** (§2.7) — déduction raisonnable à partir des exigences BOFiP d'intégrité/authenticité, mais aucun texte DGFiP trouvé l'énonçant noir sur blanc.
6. **Complétude de la recherche concurrentielle sur ClawHub/skills.sh** — les moteurs de recherche internes de ces registres n'ont pas pu être interrogés de façon exhaustive depuis l'extérieur ; seule la commande locale `hermes skills search` a fait remonter les 3 skills les plus pertinentes (§1.2), le web n'en a trouvé aucune de ce registre précis. Un futur concurrent pourrait exister sur ClawHub sans être remonté par cette recherche.
7. **Comportement réseau de `lxml` sur import XSD par URL absolue** (§3.1) — `no_network` actif par défaut mais non testé empiriquement dans le cas d'un schéma Factur-X réel avec imports externes.
8. **Contenu exact du zip officiel FNFE-MPE** (§5) — vérifié comme existant (fichier volumineux réel) mais jamais ouvert ni son contenu détaillé confirmé.

---

## Décisions à trancher avant de coder

1. **Positionnement vs. `analyse-piece-comptable` et `e-facture-rapprochement`** (§1.2) : ces deux skills locales partagent déjà le principe "script déterministe + présentation par le modèle" et touchent aux factures/TVA. Faut-il se différencier explicitement par la spécialisation Factur-X (extraction XML CII + validation EN 16931 stricte, ce qu'aucune des deux ne fait), ou existe-t-il un risque de confusion/duplication à clarifier dans la description de la nouvelle skill pour que le modèle choisisse la bonne au bon moment ?
2. **Stratégie de dépendances Python** (§3.2) : valider le choix `pypdf` + `lxml` + schémas vendorisés plutôt que d'installer `factur-x` ou `drafthorse` tel quel — implique de maintenir soi-même la copie des XSD/Schematron officiels dans le dépôt (charge de mise à jour manuelle en cas d'évolution de la norme).
3. **Granularité de la validation à livrer en v1** : valider uniquement XSD (structure) en premier jalon, ou XSD + Schematron EN 16931 (règles BR-*) dès la v1 ? Le Schematron est ce qui différencie le projet des concurrents identifiés (aucun ne semble le faire), mais alourdit l'implémentation.
4. **Profils à couvrir en priorité** : MINIMUM/BASIC WL/BASIC (usage CHORUS PRO / PME) vs. EN16931/EXTENDED (conformité stricte réforme 2026) — les deux jeux de test (§5) ne couvrent pas les mêmes profils selon la source, ce qui a un impact sur quels profils peuvent être testés dès le départ sans attendre le contenu du zip FNFE-MPE.
5. **Gestion des noms de fichiers non conformes** (§2.3) : la skill doit-elle uniquement supporter la détection par `AFRelationship=/Data` + MIME (recommandé), ou aussi prévoir un mode de repli permissif si un PDF réel ne respecte pas cet attribut (émetteurs non conformes) ?
6. **Portée de l'archivage** (§2.7) : la skill de réception doit-elle elle-même se soucier de l'archivage légal 10 ans (conserver le PDF/A-3 d'origine tel quel après traitement), ou est-ce hors périmètre et délégué à un système externe ? Cette décision dépend de la confirmation de la zone d'incertitude n°5.
7. **Vérification manuelle du contenu FNFE-MPE** (§2.1, §2.5, §5) : avant toute implémentation, télécharger et inspecter manuellement le pack officiel FNFE-MPE (exemples + XSD/Schematron) pour lever les incertitudes n°1 et n°8 plutôt que de coder sur la base de sources secondaires.

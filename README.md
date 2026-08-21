# tap-france

Skills Hermes pour la conformité réglementaire française. Une seule skill pour l'instant : la réception de factures électroniques Factur-X.

| | |
|---|---|
| `skills/finance/facturx-reception/` | la skill : `SKILL.md`, `scripts/`, `schemas/` |
| `CONTRAT-facturx-reception.md` | **référence normative** de l'implémentation |
| `tests/` | suite de tests, fixtures comprises |
| `tests/verif_comportement.py` | non-régression **comportementale** : ce que le modèle fait du rapport |
| `scripts/install-skill.sh` | installe les skills dans `~/.hermes/skills/` |
| `scripts/fetch_schemas.py` | repli d'installation, non activé — voir `schemas/NOTICE.md` |

Le contrat prime sur le code : toute divergence entre les deux est un bug du code.

Le script assemble lui-même la réponse française finale, dans un champ `rapport` que le modèle affiche tel quel. Ce qui relevait de consignes en prose — une puce par constatation, messages officiels repris mot pour mot, compte à rebours avant l'échéance — est ainsi devenu une propriété testée plutôt qu'un comportement espéré.

## Installation dans Hermes

```bash
./scripts/install-skill.sh
```

Copie chaque skill du dépôt vers `~/.hermes/skills/`, puis vérifie que la copie correspond au dépôt (`diff -r`, plus une empreinte SHA-256 de l'arbre). Sortie `0` si tout concorde, `1` sinon — utilisable en CI.

```bash
./scripts/install-skill.sh --check     # vérifie seulement, n'écrit rien
./scripts/install-skill.sh --dry-run   # montre ce qui serait fait
```

**À relancer après chaque modification du dépôt.** C'est une copie, pas un lien : rien ne se propage tout seul, et `--check` est là pour vous le dire avant que vous ne testiez une version périmée.

### Pourquoi une copie et pas un lien symbolique

Hermes monte `~/.hermes/skills` dans le bac à sable du terminal, ce qui rend `scripts/` et `schemas/` exécutables par l'agent. Mais un bind mount suit les liens symboliques, donc `get_skills_directory_mount()` (`tools/credential_files.py`) refuse d'exposer un arbre qui en contient : il en fabrique une copie assainie **d'où les liens sont retirés**.

Conséquence : une skill installée par `ln -s` disparaît purement et simplement du conteneur, et — pire — un seul lien n'importe où dans l'arbre dégrade *toutes* les autres skills vers cette copie. L'échec est silencieux côté agent, seule une ligne de log en témoigne. `install-skill.sh` refuse donc de s'exécuter s'il trouve un lien symbolique, à la source comme à la destination.

## Dépendances

```bash
python3 -m pip install pypdf lxml saxonche
```

Une seule commande, et pas trois quarts de skill. Sans `saxonche`, le script tourne encore mais ne vérifie plus les règles françaises de la réforme — sa raison d'être. Un run réel s'est déroulé ainsi : deux commandes d'installation étaient documentées, le modèle n'en a exécuté qu'une, et la facture est ressortie sans aucun contrôle français. Le mode dégradé existe et se signale en clair dans le rapport, mais ce n'est pas le fonctionnement attendu.

Dans **l'interpréteur qu'utilise l'agent**, pas dans un venv de projet : c'est l'erreur d'installation la plus fréquente. En cas de doute, lancez le script sur n'importe quel fichier — s'il manque quelque chose, il renvoie `status: "missing_dependency"` et un champ `remede` contenant la commande exacte, construite avec le chemin de l'interpréteur qui vient d'échouer.

Sans `saxonche`, la skill fonctionne normalement en `level: 1` : structure validée, règles françaises déclarées non vérifiées. Ce n'est pas une panne.

## Voir la facture depuis le bac à sable

Par défaut, Hermes monte les skills dans le conteneur mais **pas** votre répertoire de travail (`docker_mount_cwd_to_workspace: false`, choix délibéré d'isolation). L'agent peut donc exécuter le script, mais pas atteindre votre facture.

Le script le détecte et renvoie `status: "file_not_visible"` plutôt qu'un « fichier introuvable » trompeur. Pour y remédier, dans `~/.hermes/config.yaml` :

```yaml
terminal:
  docker_mount_cwd_to_workspace: true
```

puis purger les conteneurs persistants, sans quoi le changement reste sans effet :

```bash
docker rm -f $(docker ps -aq --filter name=hermes-)
```

## Le calendrier de la réforme

Les règles françaises `BR-FR-*` sont des **avertissements jusqu'au 31 août 2026**, des **points bloquants à partir du 1er septembre 2026**. C'est le calendrier officiel, inscrit dans les en-têtes des deux schematrons du pack FNFE — qui portent, à cette date près, exactement le même jeu de règles.

Le script en tire la sévérité des constatations, jamais le verdict de fond : `conforme_reforme_fr` vaut `false` dès qu'une règle échoue, avant comme après la bascule. La question posée est « cette facture satisfait-elle les règles ? », pas « suis-je sanctionnable aujourd'hui ».

La date d'appréciation est un paramètre, pas l'horloge :

```bash
python3 scripts/facturx_extract.py facture.pdf --date-ref 2026-09-01
```

Par défaut c'est le jour courant. C'est le seul endroit du script où l'heure est lue, ce qui le garde reproductible à entrées données.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

151 tests, répartis en deux suites (voir plus bas). Ils invoquent le script en sous-processus, comme le fait l'agent : stdout, stderr et code de sortie sont vérifiés au même titre que le contenu du JSON. Chaque test cite la section du contrat qu'il garde.

Ils épinglent `--date-ref` : aucun ne dépend du jour où il tourne, sans quoi la suite changerait de résultat toute seule le 1er septembre 2026.

Deux d'entre eux méritent d'être connus avant toute modification de la passe `coherence` :

- **Non-régression n°1** — une facture MINIMUM officielle FNFE ne doit produire **aucune** erreur `BR-CO-*`. C'est le garde-fou contre la pire régression possible : déclarer non conforme une facture parfaitement légale.
- **Son symétrique** — une facture BASIC WL dont le seul total TTC est faussé de 1,00 € doit être détectée. La prudence de la passe ne doit pas la rendre aveugle.

## Deux suites, parce qu'il y a deux risques

`tests/test_facturx_extract.py` garde le **script** : à entrées données, la sortie est exacte. 118 tests, déterministes, qui tournent en dix-sept secondes.

Ils ne peuvent rien dire du **modèle**. Or la skill ne vaut que par ce que l'utilisateur lit à la fin, et la suite unitaire n'a aucune prise dessus. Cet angle mort nous a coûté cher : les mêmes consignes de prose ont donné, sur la même facture, 9 messages officiels repris sur 9, puis 1, puis 6. Un run isolé ne prouvait rien, et on ne s'en apercevait qu'en relisant à l'œil.

```bash
python3 tests/verif_comportement.py /tmp/hermes_run.txt --date-ref 2026-08-21
```

`verif_comportement.py` referme l'écart. Il prend la réponse d'un run hermes, la compare au champ `rapport` produit par le script pour la même facture, et signale toute ligne surnuméraire ou manquante. Trois critères binaires — rapport intact, rien ajouté autour, compte à rebours présent — et un code de sortie exploitable en CI.

L'intérêt n'est pas l'outillage, c'est le déplacement. Une propriété comportementale devient une propriété **mesurable** : au lieu d'espérer que le modèle tienne une consigne, on constate s'il l'a tenue, et on l'apprend en une seconde plutôt qu'en relisant vingt lignes. C'est le même mouvement que celui qui a fait naître le champ `rapport` — sortir de la prose tout ce qui peut être vérifié.

Ce qu'il a déjà attrapé :

| Run | Constat |
|---|---|
| V2 | préambule « Le script a été exécuté avec succès (code 0) » |
| W1 | rapport recopié seul, rien autour — conforme |
| W2 | préambule « Script executed successfully. Here is the report: » |

Un transcript s'obtient en redirigeant la sortie : `hermes chat --toolsets skills,terminal -q "…" > /tmp/run.txt 2>&1`.

## Licences des schémas embarqués

XSD des cinq profils : `akretion/factur-x`, BSD-3-Clause. Validateurs de profil et règles françaises BR-FR : pack officiel FNFE-MPE FR CTC, Apache 2.0. Détail et citations dans `skills/finance/facturx-reception/schemas/NOTICE.md`.

Aucun téléchargement à l'exécution : tout est lu localement.

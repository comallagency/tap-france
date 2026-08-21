# Transcripts de runs réels

Sorties brutes de `hermes chat`, conservées comme **pièces**, pas comme
références de non-régression.

| Fichier | Ce qu'il montre |
|---|---|
| `w1_conforme.txt` | le rapport recopié seul, rien avant, rien après |
| `w2_preambule.txt` | « Script executed successfully. Here is the report: » — le préambule de compte rendu, mode de défaillance qui a résisté à deux rédactions de la consigne |
| `x2_niveau1.txt` | un bac à sable sans `saxonche` : le rapport y est légitimement plus court, et le détecteur avait d'abord accusé le modèle de l'avoir amputé |
| `z1_run_avorte.txt` | trois HTTP 429 d'affilée chez le fournisseur d'inférence : le modèle n'a jamais répondu, et le détecteur comparait le rapport attendu à un journal d'erreurs |

Les chemins y sont anonymisés (`/home/agent/tap-france`) : ces fichiers sont
publics, et l'arborescence d'une machine de développement n'a rien à y faire.

Ils **se périment** : ils contiennent le rapport tel qu'il était au moment du
run, et le rapport évolue. `x2_niveau1.txt` est déjà dans ce cas.

Les tests ne s'appuient donc que sur ce qui ne bouge pas : la capacité du
détecteur à peler le cadre d'un vrai `hermes chat`, la première ligne, et
l'environnement déduit du run. Les altérations, elles, sont fabriquées à
l'exécution à partir du rapport du jour — voir `tests/test_verif_comportement.py`.

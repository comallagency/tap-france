# Provenance et licence des schémas vendorisés

Aucun de ces fichiers n'est de notre fait. Ils sont recopiés tels quels depuis
leurs sources officielles, et cette page dit d'où et sous quelle licence.

Deux sources, deux licences, toutes deux redistribuables dans un dépôt MIT sans
réserve : **BSD-3-Clause** pour la totalité des XSD, **Apache 2.0** pour la
totalité des schematrons.

## `factur-x/` — tous les XSD, tous profils

- **Source** : <https://github.com/akretion/factur-x>,
  `src/facturx/xsd_and_schematron/facturx-{minimum,basic,basicwl,en16931,extended}/`
- **Licence** : **BSD-3-Clause**, celle du paquet `factur-x` d'Akretion.
- **Contenu** : pour chacun des cinq profils, le point d'entrée
  `Factur-X_<PROFIL>.xsd` et les trois modules UN/CEFACT qu'il importe
  (`QualifiedDataType`, `ReusableAggregateBusinessInformationEntity`,
  `UnqualifiedDataType`). Tous les `schemaLocation` sont relatifs : rien n'est
  résolu par le réseau.
- **Version** : Factur-X **1.09**. Le champ `validation.schemas.facturx` de la
  sortie JSON reporte cette version, identique pour les cinq profils.
- **Exception amont** : dans le profil EXTENDED, le module
  `ReusableAggregateBusinessInformationEntity` est livré en **1.09.2** par la
  source, les deux autres en 1.09. C'est le choix d'Akretion, repris tel quel ;
  `manifest.json` le consigne dans `facturx_version_note`.

Les XSD des profils BASIC WL, EN 16931 et EXTENDED **ne viennent pas** du pack
FNFE, bien que celui-ci en contienne. Le pack les distribue sous une concession
d'usage FeRD/FNFE-MPE distincte de l'Apache 2.0 qui couvre ses schematrons ;
cette ambiguïté n'a pas lieu d'exister dans le dépôt, d'où la provenance unique
retenue ici. Vérifié après substitution : les trois factures de test restent
valides au regard de ces XSD, et les cinq schémas compilent.

## `fnfe/` — schematrons compilés en XSLT (FNFE-MPE)

- **Source** : pack officiel `2026_08_04_FNFE_SCHEMATRONS_FR_CTC_V1.4.0.03.zip`,
  <https://fnfe-mpe.org/wp-content/uploads/2026/08/2026_08_04_FNFE_SCHEMATRONS_FR_CTC_V1.4.0.03.zip>
- **Fichiers** : `FACTUR-X_*.xslt` (validateur officiel du profil),
  `BR-FR-Flux2-Schematron-CII.xslt` et son jumeau `_WARNING.xslt` (règles
  françaises de la réforme), plus les bases de codes `*_codedb.xml` dont les
  XSLT ont besoin à l'exécution.
- **Licence** : **Apache 2.0**, énoncée en toutes lettres page 8 du document
  `2026_06_30_FNFE_SCHEMATRONS_FR_CTC_V1.4.0.pdf` du pack :

  > L'utilisation des schematrons d'application de la Norme XP Z12-012 est
  > libre de droits, sur une base « TEL QUEL » (« AS IS »), sous réserve des
  > limitations susmentionnées, et relève des dispositions de licence
  > Apache 2.0 disponibles sur le site
  > <https://www.apache.org/licenses/LICENSE-2.0>.

  Apache 2.0 autorise la redistribution dans un dépôt MIT, à condition de
  conserver cette attribution — d'où la présente page.

- **Une ambiguïté, et sur quoi nous nous appuyons.** Le PDF du pack énonce l'Apache 2.0,
  cité ci-dessus. Mais l'en-tête des fichiers `.sch` **sources** porte une
  mention différente :

  > Schematron Licensed under European Union Public Licence (EUPL) version 1.4.0

  L'EUPL est une licence à réciprocité, ce qui ne se relabellise pas en MIT
  aussi simplement que l'Apache 2.0. La formulation paraît fautive — « version
  1.4.0 » est le numéro du pack de schematrons, pas celui de l'EUPL, dont les
  versions vont de 1.0 à 1.2 — et le PDF est la déclaration explicite et datée.
  Par ailleurs, ce que **nous** redistribuons, ce sont les `.xslt` compilés, qui
  ne portent aucune mention de licence.

  **La redistribution se fait sur la base de la mention explicite du document
  officiel du pack**, qui est la déclaration de licence datée et circonstanciée,
  et dont l'attribution est portée par la présente page comme l'Apache 2.0
  l'exige. La contradiction avec l'en-tête des `.sch` est signalée ici plutôt
  que tue ; elle peut être soulevée auprès de FNFE-MPE
  (`schematronReformeFE@fnfe-mpe.org`).

  Pour qui préfère ne rien embarquer, `scripts/fetch_schemas.py` télécharge le
  pack officiel en une étape d'installation explicite, jamais à l'exécution.

- **Réserve du producteur** : composants fournis « TEL QUEL », sans garantie ;
  il revient à chaque utilisateur de faire ses propres tests. Les anomalies se
  signalent à `schematronReformeFE@fnfe-mpe.org`.

Les `*_codedb.xml` sont indispensables : les XSLT les chargent par `document()`
en chemin relatif. Sans eux, la validation échoue — et surtout, une version qui
irait les chercher en ligne violerait la promesse « aucun appel réseau ».

## Mise à jour

`manifest.json` est la seule source de vérité pour le script : versions,
correspondance profil → schémas, langue des assertions de chaque validateur.
Remplacer une source, c'est remplacer les fichiers **et** mettre à jour ce
manifeste, puis relancer `python3 -m unittest discover -s tests`.

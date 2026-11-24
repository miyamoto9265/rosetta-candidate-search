# NOTICE

このリポジトリと ROSETTA Candidate Search（RCS、https://rcs.cobrac.site/）は、次の第三者データを使っています。

## HOMBA（Harmonized Ontology of Mammalian Brain Anatomy）

- 提供: Allen Institute
- ライセンス: [Creative Commons Attribution 4.0 International（CC BY 4.0）](https://creativecommons.org/licenses/by/4.0/)
- 出典: [HOMBA ontology（CCF-MAP）](https://alleninstitute.github.io/CCF-MAP/docs/HOMBA_ontology_v1.html)、[Allen Brain Knowledge Platform](https://knowledge.brain-map.org/data/4OGSMDGXKB34DVKGTJW)（RRID:SCR_027628）
- 論文: Ding, S.-L., Bhandiwad, A. A., Rosen, B. Q., Seeman, S. C., et al. (2026). Harmonized brain ontology and 3D atlases for human, macaque, and marmoset basal ganglia. *Cell*, 189(23). https://doi.org/10.1016/j.cell.2026.10.033
- 含まれるファイル: `rcs/HOMBA_v1_fixed.csv`（HOMBA v1 の CSV に表記の修正を加えた派生物）。HOMBA の ID・名称は `rcs/homba_*_rules.csv`、`homex/homex_terms.csv`、`cbm_data/`、テストデータ、レポートにも含まれます
- 変更点: 表記の誤りを直しています。`homex/`（より細かい区分）と `rcs/homba_*_rules.csv`（検索用の別名・略語）は本リポジトリ独自の追加です。これらの変更は Allen Institute によるものではなく、Allen Institute が本リポジトリや RCS を支持していることを意味しません

HOMBA は Allen Developing Human Brain Atlas（DHBA）のオントロジーをもとにしています。RCS が返す DHBA の名称・略語は HOMBA の CSV に含まれるものです。

### 表示例

> HOMBA の用語データは Allen Institute によるもので、CC BY 4.0 で提供されています（https://creativecommons.org/licenses/by/4.0/）。RCS では一部を修正・追加して使っています。

English:

> HOMBA terms are from the Allen Institute's Harmonized Ontology of Mammalian Brain Anatomy (RRID:SCR_027628), licensed under CC BY 4.0. RCS corrects some typos and adds its own subdivisions and aliases; these changes are not made or endorsed by the Allen Institute.

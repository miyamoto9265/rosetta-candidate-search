# SABRA Ontology — 定義と RCS での扱い

**最終更新**: 2026-09-27

**SABRA**（**S**tandardized Ontology of **A**natomies for **B**rain **R**eference **A**rchitecture）は、
組織内で脳領域名（例: CoBRAC の Circuit 名）を統一するために使う**混合アトラス**。
コード上の正本は [`rcs/sabra.py`](../rcs/sabra.py)。本書と常に一致させること。

---

## 1. 定義

SABRA は独自の ID 体系を持たない。**SABRA の領域は、必ず次のどちらか一方のアトラスの領域**である。

| 部分 | アトラス | 範囲 |
|---|---|---|
| BNA 部分 | **BNA**（Brainnetome Atlas、246 ラベル = 123 領域 × 左右） | 新皮質とその周辺 **210** ラベル（ID 1–210）＋ 皮質下核 **36** ラベル（ID 211–246: 扁桃体 Amyg・海馬 Hipp・大脳基底核 BG・視床 Tha） |
| DHBA 部分 | **DHBA**（Developing Human Brain Atlas） | 上記以外のすべて（視床下部・脳幹・小脳・前障・手綱など） |

- DHBA は HOMBA の一部である。**DHBA の項 = `DHBA_name` を持つ HOMBA 項**（RCS の `dhba_filter="with"` で返る項）。
- SABRA 名は、BNA 部分なら BNA の領域名・略称（例: `A9/46d`、`dlPu`）、DHBA 部分なら DHBA 名・略称（例: `nucleus coeruleus`）を用いる。

### 用語の使い分け（混同しないこと）

| 用語 | 意味 | SABRA との関係 |
|---|---|---|
| HOMBA | Allen Institute の統合オントロジー（本リポジトリ `rcs/HOMBA_v1_fixed.csv`） | SABRA ではない。DHBA 部分を引くための母集合 |
| DHBA | HOMBA のうち DHBA 名を持つ項 | SABRA の**非 BNA 領域**の表現 |
| BNA | Brainnetome Atlas 246 ラベル | SABRA の**皮質＋皮質下核**の表現 |
| SABRA | BNA ∪ DHBA（領域ごとにどちらか一方） | 組織内の標準領域名 |

「HOMBA 化」「BNA 化」は個別アトラスへの対応付け、「SABRA 化」は領域ごとに適切な方を選んで対応付けること。

---

## 2. 境界（HOMBA 階層上の BNA 担当範囲）

HOMBA の項が SABRA でどちらのアトラスに属するかは、次の HOMBA 部分木に含まれるかで決める
（`rcs/sabra.py` の `BNA_TERRITORY_HOMBA_ROOTS`）。含まれれば **BNA**、含まれなければ **DHBA**。

| HOMBA ID | 名称 | 備考 |
|---|---|---|
| `HOMBA:10159` | cerebral cortex | 新皮質＋異種皮質（海馬体を含む）。BNA の皮質 210 と Hipp |
| `HOMBA:12112` | cerebral gyri and lobules | 表面構造側の脳回・脳葉（前頭葉〜島葉） |
| `HOMBA:10610` | cerebral sulci | 脳溝（文献では脳溝名で皮質位置を指すため） |
| `HOMBA:10361` | amygdaloid complex | BNA Amyg |
| `HOMBA:AA30190` | regions of basal ganglia | 線条体・淡蒼球。BNA BG（発生期の一過性構造は含めない） |
| `HOMBA:10391` | dorsal thalamus | BNA Tha の 8 亜領域は背側視床核。上視床（epithalamus: 手綱）・腹側視床（ventral thalamus）・視床腹部（subthalamus: STN, ZI）は BNA にないため DHBA |

境界を変える場合は `rcs/sabra.py` と本表を同時に更新する。

---

## 3. ツールとの対応

| ツール | 対応付け先 | SABRA での役割 |
|---|---|---|
| RCS（`rcs/`、`POST /candidates`） | HOMBA（DHBA 名を含む） | **DHBA 部分**の解決。BNA 担当範囲かどうかの判定 |
| RCS_EBL（`rcs_ebl/`、`POST /candidates-ebl`） | BNA（文献座標に基づく確率分布） | **BNA 部分**の解決 |
| MCP（`/mcp`） | 上記 2 つを 1 サーバーで提供 | 下記ワークフロー |

### MCP ツール

| ツール | 内容 |
|---|---|
| `search_homba_candidates` | RCS。各候補と `ai.results` に `sabra` 注釈（`atlas`: `DHBA` / `BNA`） |
| `search_bna_candidates` | RCS_EBL。BNA 領域の分布（`p_raw`・`k_papers`・`eff_n`）、各候補に `sabra`（`atlas: BNA`, `bna_division`） |
| `get_homba_term` | HOMBA 項の祖先・子・`sabra` 注釈 |
| `get_sabra_definition` | 本定義の機械可読版 |

`sabra` 注釈の形:

```json
{"atlas": "DHBA", "dhba_name": "nucleus coeruleus", "dhba_acronym": "…", "dhba_homba_id": "HOMBA:12499", "dhba_exact": true}
{"atlas": "BNA", "bna_territory": "dorsal thalamus", "bna_territory_root": "HOMBA:10391"}
{"atlas": "BNA", "bna_division": "cortical"}
```

`dhba_exact: false` は、その HOMBA 項自体に DHBA 名がなく、最も近い祖先の DHBA 名を返したことを示す。

### SABRA 化の基本手順（例: CoBRAC の Circuit 名）

1. `search_homba_candidates` で領域名を解決し、`ai.results`（なければ `candidates` 上位）の `sabra.atlas` を見る。
2. `DHBA` → `sabra.dhba_name` / `dhba_acronym` を SABRA 名とする。
3. `BNA` → `search_bna_candidates` を同じ領域名（遺伝子・細胞型などを除いたもの）で呼び、BNA 領域を選ぶ。
   RCS_EBL は文献上の名前 → BNA の**確率分布**であり一意ではない。単一ラベルが必要なら `level: "l2"`（脳回）も検討する。
   左右が分かる場合はクエリに left/right を含めると `bna_label_id` が決まる。

BNA 側の選び方（上位 1 件 / 累積確率 / l2 への丸めなど）は運用未確定。現状はエージェント判断とする。

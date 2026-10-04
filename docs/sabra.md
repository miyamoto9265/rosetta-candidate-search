# SABRA Ontology — 定義と RCS での扱い

**最終更新**: 2026-10-04（BNA/DHBA 境界を「新皮質だけが BNA」に変更）

**SABRA**（**S**tandardized Ontology of **A**natomies for **B**rain **R**eference **A**rchitecture）は、
組織内で脳領域名（例: CoBRAC の Circuit 名）を統一するために使う**混合アトラス**。
コード上の正本は [`rcs/sabra.py`](../rcs/sabra.py)。本書と常に一致させること。

---

## 1. 定義

SABRA は独自の ID 体系を持たない。**SABRA の領域は、必ず次のどちらか一方のアトラスの領域**である。

| 部分 | アトラス | 範囲 |
|---|---|---|
| BNA 部分 | **BNA**（Brainnetome Atlas） | **新皮質だけ**。皮質ラベル 1–210 のうち、HOMBA で新皮質の外にある A28/34（115/116、嗅内皮質）と TI（117/118、側頭無顆粒島皮質）を除く 206 ラベル |
| DHBA 部分 | **DHBA**（Developing Human Brain Atlas） | 上記以外のすべて（扁桃体・海馬体・嗅内皮質・嗅皮質などの不等皮質、大脳基底核・視床・視床下部・脳幹・小脳・前障・手綱など） |

- **2026-10-04 の変更**: それまでは BNA の皮質下核 36 ラベル（ID 211–246: 扁桃体 Amyg・海馬 Hipp・大脳基底核 BG・視床 Tha）と不等皮質も BNA で表していた。現在、これらは SABRA の領域ではなく、DHBA の項で表す。BNA と RCS_EBL にはラベルとして残っているので、`search_bna_candidates` は返すが、`sabra.atlas` は `DHBA`（`sabra_unit: false`）になる。
- 既存のデータ（CoBRAC の既存プロジェクトなど）は書き換えない。新しい境界はこれから作るデータに適用する。
- DHBA は HOMBA の一部である。**DHBA の項 = `DHBA_name` を持つ HOMBA 項**（RCS の `dhba_filter="with"` で返る項）。
- SABRA 名は、BNA 部分なら BNA の領域名・略称（例: `A9/46d`、`A4ul`）、DHBA 部分なら DHBA 名・略称（例: `nucleus coeruleus`）を用いる。

### 用語の使い分け（混同しないこと）

| 用語 | 意味 | SABRA との関係 |
|---|---|---|
| HOMBA | Allen Institute の統合オントロジー（本リポジトリ `rcs/HOMBA_v1_fixed.csv`） | SABRA ではない。DHBA 部分を引くための母集合 |
| DHBA | HOMBA のうち DHBA 名を持つ項 | SABRA の**非 BNA 領域**の表現 |
| BNA | Brainnetome Atlas 246 ラベル | SABRA の**新皮質**の表現（皮質下核 36 ラベルと A28/34・TI は SABRA に含めない） |
| SABRA | BNA ∪ DHBA（領域ごとにどちらか一方） | 組織内の標準領域名 |

「HOMBA 化」「BNA 化」は個別アトラスへの対応付け、「SABRA 化」は領域ごとに適切な方を選んで対応付けること。

---

## 2. 境界（HOMBA 階層上の BNA 担当範囲）

HOMBA の項が SABRA でどちらのアトラスに属するかは、次の HOMBA 部分木に含まれるかで決める
（`rcs/sabra.py` の `BNA_TERRITORY_HOMBA_ROOTS`）。含まれれば **BNA**、含まれなければ **DHBA**。

| HOMBA ID | 名称 | 備考 |
|---|---|---|
| `HOMBA:10160` | neocortex (isocortex) | 新皮質。島皮質（無顆粒部を含む）・帯状皮質（膝下部・脳梁膨大後部を含む）・嗅周皮質（A35/36）・海馬傍皮質（TF/TH）も HOMBA では新皮質の下にある |
| `HOMBA:12112` | cerebral gyri and lobules | 表面構造側の脳回・脳葉（前頭葉〜島葉）。下の除外を除く |
| `HOMBA:10610` | cerebral sulci | 脳溝（文献では脳溝名で皮質位置を指すため） |

BNA 担当範囲から除く HOMBA 部分木（`BNA_TERRITORY_EXCLUDED_HOMBA`。不等皮質・中隔の脳回）:

| HOMBA ID | 名称 |
|---|---|
| `HOMBA:AA30550` | hippocampal gyrus |
| `HOMBA:266441673` | subicular complex |
| `HOMBA:12165` | uncus of (para)hippocampal gyrus |
| `HOMBA:12161` | paraterminal gyrus |

HOMBA の `non-neocortex (allocortex and periallocortex)`（`HOMBA:AA30084`。海馬体・嗅内皮質・嗅皮質・梨状皮質・TI など）、扁桃体、大脳基底核、視床は、すべて DHBA になる。

### BNA の非新皮質ラベルと、それを含む DHBA の項

`search_bna_candidates` は次のラベルに `sabra: {atlas: "DHBA", sabra_unit: false, dhba_homba_id, dhba_acronym}` を付ける（`BNA_DHBA_COUNTERPARTS`）。`dhba_homba_id` はその BNA 領域を**含む** DHBA の項であり、同じ領域ではない。BNA の皮質下の亜領域は結合パターンで定義されているので、名前は `search_homba_candidates` で文献が述べる核を引いて決める。

| BNA ラベル | 略称 | それを含む DHBA の項 |
|---|---|---|
| 115/116 | A28/34 | `HOMBA:10317` EC（entorhinal cortex） |
| 117/118 | TI | `HOMBA:10330` TI（temporal agranular insular cortex） |
| 211/212, 213/214 | mAmyg, lAmyg | `HOMBA:10361` AMY（amygdaloid complex） |
| 215/216, 217/218 | rHipp, cHipp | `HOMBA:12170` HiF（hippocampal formation） |
| 219/220, 227/228 | vCa, dCa | `HOMBA:10334` Ca（caudate nucleus） |
| 221/222 | GP | `HOMBA:10342` GP（globus pallidus） |
| 223/224 | NAC | `HOMBA:10339` NAC（nucleus accumbens） |
| 225/226, 229/230 | vmPu, dlPu | `HOMBA:10338` Pu（putamen） |
| 231–246 | 視床 8 亜領域 | `HOMBA:10391` DTH（dorsal thalamus） |

2026-10-04 より前の担当範囲（`PREVIOUS_BNA_TERRITORY_HOMBA_ROOTS`）は、`HOMBA:10159` cerebral cortex（不等皮質を含む）・脳回・脳溝・`HOMBA:10361` 扁桃体・`HOMBA:AA30190` 大脳基底核・`HOMBA:10391` 背側視床だった。

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
| `search_bna_candidates` | RCS_EBL。BNA 領域の分布（`p_raw`・`k_papers`・`eff_n`）、各候補に `sabra`（新皮質は `atlas: BNA`、それ以外は `atlas: DHBA` と `sabra_unit: false`） |
| `get_homba_term` | HOMBA 項の祖先・子・`sabra` 注釈 |
| `get_sabra_definition` | 本定義の機械可読版（`boundary_version: "2026-10-04"`） |

`sabra` 注釈の形:

```json
{"atlas": "DHBA", "dhba_name": "nucleus coeruleus", "dhba_acronym": "…", "dhba_homba_id": "HOMBA:12499", "dhba_exact": true}
{"atlas": "BNA", "bna_territory": "dorsal thalamus", "bna_territory_root": "HOMBA:10391"}
{"atlas": "BNA", "bna_division": "cortical", "sabra_unit": true}
{"atlas": "DHBA", "bna_division": "subcortical", "sabra_unit": false, "dhba_homba_id": "HOMBA:10339", "dhba_acronym": "NAC", "note": "…"}
```

`dhba_exact: false` は、その HOMBA 項自体に DHBA 名がなく、最も近い祖先の DHBA 名を返したことを示す。

### SABRA 化の基本手順（例: CoBRAC の Circuit 名）

1. `search_homba_candidates` で領域名を解決し、`ai.results`（なければ `candidates` 上位）の `sabra.atlas` を見る。
2. `DHBA` → `sabra.dhba_name` / `dhba_acronym` を SABRA 名とする。
3. `BNA`（新皮質）→ `search_bna_candidates` を同じ領域名（遺伝子・細胞型などを除いたもの）で呼び、`sabra.atlas` が `BNA` の領域を選ぶ。`DHBA` の候補（皮質下・海馬など）は SABRA の領域ではないので使わない。
   RCS_EBL は文献上の名前 → BNA の**確率分布**であり一意ではない。単一ラベルが必要なら `level: "l2"`（脳回）も検討する。
   左右が分かる場合はクエリに left/right を含めると `bna_label_id` が決まる。

BNA 側の選び方（上位 1 件 / 累積確率 / l2 への丸めなど）は運用未確定。現状はエージェント判断とする。

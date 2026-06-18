まず、ファイルの内容を確認します。

[12 tools called]

全2,343エントリを精査しました。論文記述→HOMBAへの自動変換システムを構築する際に課題となりそうなポイントを、カテゴリごとに整理して報告します。

---

## 1. オントロジー自体に含まれるタイプミス・不整合（最重要）

変換システムの**正規化辞書の根幹**に影響するため、まず修正すべき問題です。

| 行 | 問題箇所 | 正しい綴り |
|---|---|---|
| 69, 70 | "**promotor** cortex" | premotor |ok ok
| 128 | "first **auditiory** cortex" | auditory |ok ok
| 154 | "**rostraldivision**" | rostral division（スペース欠落） |ok ok
| 186 | "**sencond** dorsal third visual area" | second |ok
| 559 | "**septohipocampal**" | septohippocampal |ok
| 627, 629, 630 | "**subdivsion**" | subdivision |ok
| 632, 696 | "**densocelllular**" | densocellular（lが3つ） |ok
| 650 | "lateral division of **BNSr**" | BSTr（略称間違い?） |
| 663 | "stria **terminaris**" | terminalis |
| 686, 748, 787, 813, 1087 | "**magocellular**" | magnocellular（nが欠落） |ok
| 938 | "posterior **hypothalmus**" | hypothalamus |ok
| 942–944 | "premammillary **nulcei/nulceus**" | nuclei / nucleus |ok
| 1095 | "(**mantal**) zone" | mantle |ok
| 1512 | "**oflower** brainstem" | of lower（スペース欠落） |ok
| 1536 | "**infundubular**" | infundibular |ok
| 1816 | "in **bindbrain**" | hindbrain |ok
| 1975 | "fasciolar **gyrys**" | gyrus |ok
| 1980 | "intralimbic **gryus**" | gyrus |ok
| 2063 | "uvula and **tosil**" | tonsil |ok
| 2215, 2229 | "spinal **cortex**" | spinal cord（cordの誤り?） |
| 2302 | "dorsal **cloumn**" | column |ok

さらに、余計なスペース（ダブルスペース）が散見されます：行146, 211, 214, 219, 1080 など。これらはテキストマッチングの際にノイズになります。

---

## 2. 一つの領域に対する複数の別名・別体系の同居（表記揺れの最大要因）

HOMBAでは括弧内に別名・Brodmann番号・略称を併記していますが、論文側はどれか**一つだけ**を使うため、マッチングが困難です。

### 特に問題が大きい例：

**皮質領域：**
- `"primary motor cortex (first motor cortex, area 4, area FA)"` — 論文では "M1", "area 4", "area FA", "primary motor cortex" のどれで書かれるか不定
- `"premotor cortex (area 6, area FB, secondary motor cortex)"` — "PMC", "area 6", "secondary motor cortex" など
- `"primary somatosensory cortex (first somatosensory cortex, areas 3,1,2)"` — "S1", "areas 3,1,2" が混在
- `"primary visual cortex (first visual cortex, striate cortex, area 17, area OC)"` — "V1", "striate cortex", "area 17", "calcarine cortex" 等
- `"primary auditory cortex (first auditiory cortex, auditory core region)"` — "A1", "auditory core"
- `"ventrolateral prefrontal cortex (Broca's area in dominant hemisphere)"` — 臨床文脈では "Broca's area" のみ
- `"fifth visual area (middle temporal area, MT)"` — fMRI文献では "MT" か "V5" のみ

**皮質下・その他：**
- `"hippocampal proper (Cornu Ammonis)"` — ラテン語 "Cornu Ammonis" とCA1-4の関係
- `"striatum (neostriatum)"` — "neostriatum" は古い文献
- `"nucleus coeruleus (locus coeruleus)"` — 圧倒的に "locus coeruleus (LC)" が多い
- `"globus pallidus (paleostriatum)"` — "paleostriatum" は旧称
- `"zona incerta"` — ラテン語だが英語化して使われることも

---

## 3. 人名由来（エポニム）の名前

人名のスペルミスが論文中に多く、また同じ構造に対して人名を使う/使わないの両方があるため、難易度が高い。

| HOMBA名 | よくある論文記述の揺れ |
|---|---|
| Edinger-Westphal nucleus | EW nucleus, Edinger–Westphal（ダッシュ種類） |
| basal nucleus of Meynert | nucleus basalis of Meynert, NBM, Ch4 |
| nucleus of Darkschewitsch | Darkschewitsch / Darkschewitz / Darkshewitsch |
| interstitial nucleus of Cajal | INC, nucleus of Cajal |
| Koelliker-Fuse nucleus | Kölliker-Fuse, KF nucleus |
| transverse temporal gyrus (Heschl's gyrus) | Heschl gyrus（'s無し）、HG |
| dorsal (Clarke's) nucleus | Clarke's column, nucleus dorsalis |
| Onuf's nucleus | Onufrowicz's nucleus |
| Meyer's loop of optic radiation | Meyer loop |
| islands of Calleja | Calleja islands |
| Barrington's nucleus | Barrington nucleus |
| field of Forel / prerubral field (field H3) | Forel's field H, H1/H2/H3 |
| band of Giacomini | Giacomini band |
| subcallosal fasciculus (Muratoff bundle) | Muratoff / Muratov bundle |
| Arnolds bundle (line 1765) | Arnold's bundle（'s有無） |
| Lissauer's fasciculus | tract of Lissauer, dorsolateral fasciculus |
| Botzinger / pre-Botzinger complex | Bötzinger（ウムラウト有無） |

---

## 4. 単一文字・番号のみの名称（検索・マッチング困難）

以下は名前が短すぎるか、一般的な単語と衝突するためテキストマッチングが極めて困難です：

- **`nucleus K in pons`**, **`nucleus L in pons`**, **`nucleus U of midbrain`**, **`nucleus X`**, **`nucleus Y`**, **`nucleus Z`** — 単一アルファベットの核
- **`A2 noradrenaline cell group`**, **`A7`**, **`A8`**, **`B9 serotonin cell group`** — セルグループ番号
- **`area x of visual cortex`** (line 183) — 小文字の "x" で、他の "nucleus X" と混同リスク
- **`bundle X`** (line 1612)
- **`field H1`**, **`field H2`**, **`field H3`** — Forelの磁場番号

---

## 5. 種特異的な修飾子

論文の対象種によって名称の有無が変わるため、変換時にフィルタリングが必要です：

- `barrel field of S1fm (rodents)` — 齧歯類のみ
- `unique layer 3 of primary visual cortex (primates)` — 霊長類のみ
- `layer 4a of NCx ... (primates)` — 霊長類のみ
- `principal sulcus (macaque)` — マカクザルのみ
- `arcuate sulcus (macaque)` — マカクザルのみ

---

## 6. 同名・類似名で異なる領域を指すケース（曖昧性）

変換時に**文脈を考慮しないと正しい領域にマッピングできない**ケースです：

| 名前 | 複数の出現箇所 |
|---|---|
| "central nucleus" | 扁桃体 (line 575) vs. 下丘 (line 982) |
| "lateral nucleus" | 扁桃体 (line 602) vs. 視床 |
| "interpositus nucleus" | 小脳 (line 1165) vs. 延髄 (line 1379) |
| "arcuate nucleus" | 視床下部 (line 913) vs. 延髄 (line 1322) |
| "dorsal raphe nucleus" | 単独でも使われるが、複数のdivisionが存在 |
| "paraventricular nucleus" | 視床 (line 704) vs. 視床下部 (line 885) |
| "reticular nucleus" | 視床 (line 831) vs. 網様体各部 |
| "vestibular nuclei" | 橋 (line 1236) vs. 延髄 (line 1387) |
| "lobule VI" - "lobule X" | 小脳虫部 vs. 半球部で同じ番号だが異なる名称 |
| "dentate nucleus" vs. "dentate gyrus" | 小脳 vs. 海馬 — "dentate" だけでは区別不能 |

---

## 7. 体系間の表記揺れ（方向用語の不統一）

HOMBA自体の中でも、以下の同義語対が混在しています。論文側でもどちらを使うか不定です：

| ペア | 例 |
|---|---|
| rostral ↔ anterior | `rostral (ventral) presubiculum` vs. `anterior hypothalamic nucleus` |
| caudal ↔ posterior | `caudal (dorsal) parasubiculum (postsubiculum)` |
| dorsal ↔ superior | 用法が領域により異なる |
| ventral ↔ inferior | 同上 |

---

## 8. 略称の不統一パターン

HOMBA内でも略称の使い方にブレがあり、論文との対応付けに支障をきたします：

- `DFC`, `VFC`, `OFC` — 括弧内で紹介されるが、正式名ではない
- `GPe` / `GPi` — HOMBA内では "external/internal division of globus pallidus" だが、論文では "GPe/GPi" が圧倒的
- `SN(c/r)` — "substantia nigra, compact/reticular division" だが、論文では "SNc", "SNr"
- `VTA` — "ventral tegmental area" だが略称が本文中にない
- `NAc` / `NAcc` — "nucleus accumbens" の一般的略称

---

## 推奨対策

1. **まずタイプミスを修正**して、辞書のベースラインを正確にする
2. **同義語テーブル（synonym table）**を別途構築し、HOMBA名 ↔ 論文中頻出名（略称・エポニム・Brodmann番号等）のマッピングを持たせる
3. **文脈依存の曖昧性解消**（"central nucleus" など）には、周囲の解剖学的キーワード（amygdala, inferior colliculus 等）との共起を使ったルールまたはMLモデルが必要
4. **正規化前処理**として、余分なスペース・アポストロフィの有無・ダッシュ種類（`-` vs `–`）・ウムラウト（`ö` vs `o`）を統一するレイヤーを入れる
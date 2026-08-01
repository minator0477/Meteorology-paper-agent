# 監視対象ジャーナルの出版頻度

`config/sources.yml` で監視しているジャーナル（ISSN）について、OpenAlex API
（`https://api.openalex.org/works`）から実測した出版件数。

- 調査日: 2026-08-01
- 集計方法: `primary_location.source.issn` フィルタで、直近 10日/30日/90日の
  `from_publication_date` を指定し、`meta.count` を取得
- 「週あたり換算」は直近90日の件数を `件数 / 90 * 7` で換算した値（変動をならすため90日平均を採用）

## 集計結果

| ISSN | ジャーナル | 直近10日 | 直近30日 | 直近90日 | 週あたり換算 |
|---|---|---:|---:|---:|---:|
| 0094-8276 | Geophysical Research Letters (GRL) | 57 | 175 | 526 | 約41.0件 |
| 0894-8755 | Journal of Climate | 7 | 27 | 103 | 約8.0件 |
| 0027-0644 | Monthly Weather Review (MWR) | 10 | 18 | 36 | 約2.8件 |
| 0022-4928 | Journal of the Atmospheric Sciences (JAS) | 3 | 9 | 36 | 約2.8件 |
| 2698-4016 | Weather and Climate Dynamics (WCD) | 4 | 14 | 32 | 約2.5件 |
| 1349-6476 | SOLA | 1 | 1 | 12 | 約0.9件 |
| 0026-1165 | Journal of the Meteorological Society of Japan (JMSJ) | 0 | 3 | 9 | 約0.7件 |
| **合計** | | **82** | **247** | **790** | **約59.5件** |

## 所見

- **GRL が全体の約7割**を占める最大の供給源。地球科学全般を扱う総合誌のため、
  対象外分野（化学輸送・エアロゾル単体、観測機器工学など）の論文も相当数含まれると想定される。
- **JMSJ・SOLA は週1件未満**と低頻度で、週次実行でも0件のことが珍しくない。
- 現在の `lookback_days: 10` では1回の実行で概算 **80〜90件程度**の候補取得が見込まれ、
  `batch_size: 25` なら `score.py` は1回あたり Claude API を **4回程度**呼び出す計算になる。
- `authors.ids` は現状未設定のため、候補は全てジャーナルフィルタ経由。著者を追加すると、
  その著者の他誌掲載分がここに上乗せされる。

## 再集計の方法

数値は時間とともに変わるため、必要に応じて以下のように再取得できる（`jq` 使用）。

```bash
SINCE=$(date -d "90 days ago" +%Y-%m-%d)
curl -s "https://api.openalex.org/works?filter=primary_location.source.issn:<ISSN>,from_publication_date:${SINCE}&per-page=1" \
  | jq '.meta.count'
```

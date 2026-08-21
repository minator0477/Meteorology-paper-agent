# Meteorology Paper Agent

気象学・気候学分野の論文を毎週自動でウォッチし、個人の研究興味プロファイルに照らして
スコアリングし、面白そうなものだけを Discord に通知する GitHub Actions 製の週次パイプライン。
Discord の 👍/👎 リアクションを毎週回収してスコアリングにフィードバックするので、
使うほど自分の好みに寄っていく。

## できること

- OpenAlex API から、指定したジャーナル（ISSN）・著者（OpenAlex author ID）の新着論文を取得
- 論文の `title + abstract` を `interests.md` のテーマ別代表文と埋め込みベクトルで比較し、
  コサイン類似度から 0〜10 点を算出（**LLM 呼び出しなし・ローカル計算**）
- しきい値以上の論文だけを Discord に 1 論文 1 メッセージで投稿し、👍/👎 リアクションを
  あらかじめ付与（クリックするだけで反応できる）
- 上位 5 件については、Claude にタイトルと要旨を渡して「なぜ自分の興味に刺さるか」を
  100〜150 字程度で説明するおすすめ理由を生成し、通知に添える
- 過去に投稿した論文への 👍/👎 を毎週集計し、テーマごとの埋め込みベクトルを
  Rocchio 的に更新（`+=` 好評、`-=` 不評）。次週以降のスコアリングに反映される
- しきい値未満も含む全候補の採点結果を `history/YYYY-MM-DD.md` に記録（スコア調整用）

## パイプライン

毎週 GitHub Actions のスケジュール実行で、以下を順番に実行する。

```
collect_feedback.py  → Discord の 👍/👎 を集計し、state/theme_vectors.json を更新
        ↓
fetch.py              → OpenAlex から新着論文を取得し、seen.json 済みを除外 → candidates.json
        ↓
score.py              → interests.md × theme_vectors.json の埋め込みで採点 → scored.json
                         （全候補の採点結果は history/ にも記録）
        ↓
report.py             → scored.json を Discord に投稿。上位5件はClaudeでおすすめ理由を生成。
                         state/seen.json, state/reported_papers.json を更新
```

`collect_feedback.py` が最初に走るのは、その週に集まったリアクションを、その週の
`score.py` の採点に間に合わせて反映するため。

## ディレクトリ構成

```
.github/workflows/paper-digest.yml   # 週次 cron のエントリポイント
scripts/fetch.py                     # OpenAlex から候補取得
scripts/score.py                     # 埋め込みベースの採点
scripts/report.py                    # Discord への投稿・LLMおすすめ理由生成
scripts/collect_feedback.py          # Discordリアクションの回収・フィードバック反映
scripts/embedding_util.py            # score.py / collect_feedback.py 共有のモデルロード処理
config/sources.yml                   # 監視対象・しきい値・埋め込み関連の設定
config/interests.md                  # 研究興味プロファイル（採点基準そのもの）
state/seen.json                      # 通知済み論文ID（重複通知防止、自動コミット）
state/reported_papers.json           # フィードバック待ちの投稿履歴（自動コミット）
state/theme_vectors.json             # 学習済みフィードバックベクトル（自動コミット）
history/YYYY-MM-DD.md                # 毎週の全候補の採点結果（自動コミット）
```

## セットアップ

### 1. Discord Webhook の作成

投稿先チャンネルに Webhook を作成し、URL を `DISCORD_WEBHOOK_URL` として GitHub リポジトリの
Secrets に登録する。

### 2. Discord Bot の作成（リアクション付与・フィードバック回収に必要）

Webhook だけではリアクションを読み取れないため、以下を行う。

1. [Discord Developer Portal](https://discord.com/developers/applications) で
   Application + Bot を作成し、トークンを控える
2. Bot を対象サーバーに招待（`View Channel` / `Read Message History` / `Add Reactions` 権限）
3. 対象チャンネルの Channel ID をコピー（開発者モードを有効化して右クリック）
4. `DISCORD_BOT_TOKEN` と `DISCORD_CHANNEL_ID` を Secrets に登録

未設定でも `report.py` は投稿自体はできる（リアクション付与のみスキップ）が、
`collect_feedback.py` は両方必須。

### 3. Claude API キーの取得（任意・おすすめ理由生成に使用）

`ANTHROPIC_API_KEY` を Secrets に登録すると、上位5件の通知にLLM生成のおすすめ理由が付く。
未設定でも動作は止まらず、埋め込み類似度ベースの機械的な理由にフォールバックする。

### 4. 監視対象・興味プロファイルの設定

- `config/sources.yml` にウォッチしたいジャーナルの ISSN、著者の OpenAlex author ID
  （`https://api.openalex.org/authors?search=<name>` で調べる）、しきい値などを設定
- `config/interests.md` の `## tropical` / `## midlatitude` / `## seam` / `## regional` /
  `## method` の各セクション本文を、自分の興味に合わせて編集する（ここが採点基準そのもの）

### 5. 必要な Secrets 一覧

| 変数名 | 必須/任意 | 用途 |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | 必須 | `report.py` の投稿先 |
| `DISCORD_BOT_TOKEN` | 任意（ソフト必須） | リアクション付与・フィードバック回収 |
| `DISCORD_CHANNEL_ID` | 任意（ソフト必須） | 同上 |
| `ANTHROPIC_API_KEY` | 任意 | 上位5件のおすすめ理由生成 |
| `OPENALEX_MAILTO` | 任意 | OpenAlex API の polite pool 利用 |

## ローカルでの実行

```bash
pip install -r requirements.txt

python scripts/collect_feedback.py  # state/theme_vectors.json を更新（要 Bot 系 env var）
python scripts/fetch.py             # candidates.json を生成
python scripts/score.py             # scored.json を生成（ローカル埋め込み、API キー不要）
python scripts/report.py            # Discord に投稿し state/ を更新（要 Webhook）
```

必ずリポジトリルートから実行すること（各スクリプトが `Path(__file__).resolve().parent.parent`
でルートを解決している）。

`score.py` は初回実行時に `sentence-transformers` のモデルをダウンロードする
（以降は `~/.cache/huggingface` にキャッシュ、CI でもキャッシュされる）。

## スコアの調整

`history/YYYY-MM-DD.md` に、しきい値未満も含む全候補の類似度・スコアが残るので、
実際の分布を見ながら `config/sources.yml` の `embedding.similarity_low` /
`embedding.similarity_high` / `min_score` を調整するとよい。

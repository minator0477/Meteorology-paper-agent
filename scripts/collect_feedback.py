"""
週次サイクルの先頭（fetch.py の前）で実行する: 過去に report.py が投稿した論文への
Discord リアクション（👍/👎）を Bot REST API で集計し、state/theme_vectors.json を
Rocchio 的に更新する。次に走る score.py はこの更新後のベクトルを使って採点する。

- state/reported_papers.json を読み、feedback.window_days 以内のエントリだけ処理する
- 👍が多ければ liked、👎が多ければ disliked、同数/どちらも無ければ「まだ判定なし」として
  次回以降の実行で再チェックする
- 判定がついたエントリは (title+abstract) を embedding_util と同じモデルで埋め込み、
  テーマごとの累積ベクトル (state/theme_vectors.json) に加算/減算したうえで
  reported_papers.json から即座に取り除く（同じ投票を毎週重複カウントしないため、
  一度判定がついたエントリは二度と数えない）
- window_days を過ぎても判定がつかなかったエントリは reported_papers.json から破棄する
"""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import requests
import yaml

from embedding_util import THEMES, get_model

ROOT = Path(__file__).resolve().parent.parent
CONFIG = yaml.safe_load((ROOT / "config" / "sources.yml").read_text(encoding="utf-8"))
REPORTED_PATH = ROOT / "state" / "reported_papers.json"
VECTORS_PATH = ROOT / "state" / "theme_vectors.json"

EMB_CONFIG = CONFIG.get("embedding") or {}
MODEL_NAME = EMB_CONFIG.get("model", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
MAX_SEQ_LENGTH = int(EMB_CONFIG.get("max_seq_length", 384))
WINDOW_DAYS = int((CONFIG.get("feedback") or {}).get("window_days", 21))

BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID = os.environ["DISCORD_CHANNEL_ID"]
DISCORD_API = "https://discord.com/api/v10"
THUMBS_UP = "%F0%9F%91%8D"
THUMBS_DOWN = "%F0%9F%91%8E"


def get_reactor_count(message_id: str, emoji: str) -> int:
    """指定メッセージ・絵文字のリアクター数を返す。メッセージが無ければ 0。"""
    url = f"{DISCORD_API}/channels/{CHANNEL_ID}/messages/{message_id}/reactions/{emoji}"
    r = requests.get(url, headers={"Authorization": f"Bot {BOT_TOKEN}"}, timeout=30)
    if r.status_code == 404:
        return 0
    r.raise_for_status()
    return len(r.json())


def load_vectors() -> dict:
    if VECTORS_PATH.exists():
        data = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
        if data.get("model") == MODEL_NAME:
            return data
    return {"model": MODEL_NAME, "themes": {}}


def main() -> None:
    if not REPORTED_PATH.exists():
        print("state/reported_papers.json が無い。フィードバック対象なし。")
        return

    reported = json.loads(REPORTED_PATH.read_text(encoding="utf-8"))
    if not reported:
        print("フィードバック対象なし。")
        return

    cutoff = date.today() - timedelta(days=WINDOW_DAYS)
    remaining, liked_by_theme, disliked_by_theme = [], {}, {}

    for p in reported:
        reported_date = date.fromisoformat(p["reported_date"])
        if reported_date < cutoff:
            continue  # window を過ぎても判定がつかなかったので破棄
        if p.get("theme") == "other":
            continue  # other には代表ベクトルが無いので学習対象外、破棄してよい
        up = get_reactor_count(p["message_id"], THUMBS_UP)
        down = get_reactor_count(p["message_id"], THUMBS_DOWN)
        if up > down:
            liked_by_theme.setdefault(p["theme"], []).append(p)
            # 判定がついたので二度と数えないよう remaining には戻さない
        elif down > up:
            disliked_by_theme.setdefault(p["theme"], []).append(p)
        else:
            remaining.append(p)  # まだ判定なし。window内なら来週また見る

    themes_touched = set(liked_by_theme) | set(disliked_by_theme)
    if not themes_touched:
        print(f"新規フィードバックなし（集計対象 {len(remaining)} 件）。")
        REPORTED_PATH.write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    model = get_model(MODEL_NAME, MAX_SEQ_LENGTH)
    vectors = load_vectors()

    summary = []
    for theme in themes_touched:
        liked = liked_by_theme.get(theme, [])
        disliked = disliked_by_theme.get(theme, [])
        texts = [f"{p['title']}\n\n{p['abstract']}".strip() for p in liked + disliked]
        embeddings = model.encode(texts, normalize_embeddings=True)

        entry = vectors["themes"].setdefault(
            theme, {"vector": [0.0] * embeddings.shape[1], "liked_count": 0, "disliked_count": 0})
        vec = np.array(entry["vector"], dtype=float)
        for emb in embeddings[:len(liked)]:
            vec += emb
        for emb in embeddings[len(liked):]:
            vec -= emb
        entry["vector"] = vec.tolist()
        entry["liked_count"] += len(liked)
        entry["disliked_count"] += len(disliked)
        summary.append(f"{theme}: +{len(liked)}/-{len(disliked)}")

    vectors["updated_at"] = datetime.utcnow().isoformat()
    VECTORS_PATH.write_text(json.dumps(vectors, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORTED_PATH.write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"フィードバック反映: {', '.join(summary)} -> {VECTORS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

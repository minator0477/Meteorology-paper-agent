"""
ステップ3: scored.json を Discord に通知する（投稿は Webhook、リアクション付与は Bot）。
- 1論文 = 1メッセージで投稿する（Discordのリアクションはメッセージ単位にしか付かないため、
  scripts/collect_feedback.py が👍/👎を論文ごとに区別できるようにするための制約）
- 投稿直後に👍/👎リアクションを Bot で先付けし、ユーザーはクリックするだけで反応できる
  （DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID が未設定なら黙ってスキップする）
- 上位 RECOMMEND_TOP_N 件は、title+abstract を渡して Claude におすすめ理由（100〜150字）を
  生成させ、embed の reason をそれで上書きする（ANTHROPIC_API_KEY 未設定・生成失敗時は
  score.py が書いた埋め込み類似度ベースの reason にフォールバックする）
- 送信できた論文について、state/seen.json に id を追記（再通知防止）し、
  message_id 付きで state/reported_papers.json にも記録する
  （collect_feedback.py がフィードバック集計のために読む）
"""
import json
import os
import re
import time
from datetime import date
from pathlib import Path

import anthropic
import requests

ROOT = Path(__file__).resolve().parent.parent
SCORED_PATH = ROOT / "scored.json"
SEEN_PATH = ROOT / "state" / "seen.json"
REPORTED_PATH = ROOT / "state" / "reported_papers.json"
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

DISCORD_API = "https://discord.com/api/v10"
THUMBS_UP = "\U0001F44D"
THUMBS_DOWN = "\U0001F44E"

RECOMMEND_TOP_N = 5
RECOMMEND_MODEL = "claude-sonnet-5"
RECOMMEND_SYSTEM = """あなたは気象学・気候学研究者向けの論文キュレーターです。
渡された各論文について、タイトルと要旨の内容を踏まえ「なぜこの研究者にとって面白いか」を
具体的に伝えるおすすめ理由を、日本語で100〜150字程度で1つ書いてください。

出力はJSON配列のみ。各要素は次のキーを持つこと:
  "id": 入力のidをそのまま
  "reason": 100〜150字程度のおすすめ理由（日本語）
前置き・後置き・コードフェンスは一切書かず、JSON配列だけを返すこと。"""

THEME_COLOR = {           # Discord embed の色（10進）
    "tropical":   0xD85A30,
    "midlatitude": 0x378ADD,
    "seam":       0xEF9F27,
    "regional":   0x1D9E75,
    "method":     0x7F77DD,
    "other":      0x888780,
}


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def to_embed(p: dict) -> dict:
    authors = ", ".join(p["authors"][:3]) + (" ほか" if len(p["authors"]) > 3 else "")
    lines = [
        f"**{p['journal']}**  ·  {p['date']}",
        f"score **{p['score']}/10**  ·  `{p['theme']}`",
        f"{p['reason']}",
        authors,
    ]
    if p.get("oa_pdf"):
        lines.append(f"[OA PDF]({p['oa_pdf']})")
    return {
        "title": p["title"][:250],
        "url": p["url"],
        "description": "\n".join(lines)[:4000],
        "color": THEME_COLOR.get(p["theme"], THEME_COLOR["other"]),
    }


def post_message(content: str | None, embeds: list[dict]) -> dict | None:
    """?wait=true でメッセージJSONを受け取る（あとで message_id を使うため）。"""
    payload = {"embeds": embeds}
    if content:
        payload["content"] = content
    r = requests.post(f"{WEBHOOK}?wait=true", json=payload, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else None


def strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def generate_recommend_reasons(papers: list[dict]) -> dict[str, str]:
    """上位論文の title+abstract から、おすすめ理由を Claude に生成させる。
    ANTHROPIC_API_KEY 未設定・生成失敗時は空 dict を返し、呼び出し側は
    score.py 由来の reason にフォールバックする。"""
    if not ANTHROPIC_API_KEY or not papers:
        return {}

    payload = [{"id": p["id"], "title": p["title"], "abstract": p.get("abstract", "")[:1500]}
               for p in papers]
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=RECOMMEND_MODEL,
            max_tokens=4000,
            system=RECOMMEND_SYSTEM,
            messages=[{"role": "user",
                       "content": "対象論文:\n" + json.dumps(payload, ensure_ascii=False)}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        items = json.loads(strip_fences(text))
        return {item["id"]: item["reason"] for item in items if item.get("id") and item.get("reason")}
    except (anthropic.APIError, json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"おすすめ理由の生成に失敗（既存のreasonにフォールバック）: {e}")
        return {}


def add_reactions(message_id: str) -> None:
    """👍/👎 を Bot で先付けする。Bot未設定・失敗は致命的でないのでログのみ。"""
    if not BOT_TOKEN or not CHANNEL_ID or not message_id:
        return
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    for emoji in (THUMBS_UP, THUMBS_DOWN):
        url = f"{DISCORD_API}/channels/{CHANNEL_ID}/messages/{message_id}/reactions/{emoji}/@me"
        try:
            r = requests.put(url, headers=headers, timeout=15)
            if not r.ok:
                print(f"リアクション付与に失敗 ({emoji}): {r.status_code} {r.text}")
        except requests.RequestException as e:
            print(f"リアクション付与でエラー ({emoji}): {e}")


def main() -> None:
    scored = json.loads(SCORED_PATH.read_text(encoding="utf-8"))
    if not scored:
        post_message("今週の新着ヒットはありませんでした。", [])
        return

    post_message(f"今週の面白そうな論文 {len(scored)} 件（score 高い順）", [])

    llm_reasons = generate_recommend_reasons(scored[:RECOMMEND_TOP_N])
    for p in scored:
        if p["id"] in llm_reasons:
            p["reason"] = llm_reasons[p["id"]]

    seen = load_json(SEEN_PATH, {"reported": []})
    reported_papers = load_json(REPORTED_PATH, [])
    today = date.today().isoformat()

    reported_ids = []
    for p in scored:
        msg = post_message(None, [to_embed(p)])
        message_id = (msg or {}).get("id", "")
        add_reactions(message_id)
        reported_ids.append(p["id"])
        if message_id:
            reported_papers.append({
                "id": p["id"],
                "message_id": message_id,
                "theme": p["theme"],
                "score": p["score"],
                "title": p["title"],
                "abstract": p.get("abstract", ""),
                "reported_date": today,
            })
        time.sleep(1)  # レート制限に配慮

    seen["reported"] = sorted(set(seen["reported"]) | set(reported_ids))
    SEEN_PATH.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORTED_PATH.write_text(json.dumps(reported_papers, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"reported {len(scored)} papers; seen store now {len(seen['reported'])} ids; "
          f"reported_papers.json now {len(reported_papers)} entries")


if __name__ == "__main__":
    main()

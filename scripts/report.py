"""
ステップ3: scored.json を Discord に通知する（Webhook, Bot不要）。
- テーマ別に色分けした embed で送信
- 送信できた論文の id を seen.json に追記（次回以降は再通知しない）
Discord 制限に合わせて 1 メッセージ最大 10 embed に分割。
"""
import json
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SCORED_PATH = ROOT / "scored.json"
SEEN_PATH = ROOT / "state" / "seen.json"
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

THEME_COLOR = {           # Discord embed の色（10進）
    "tropical":   0xD85A30,
    "midlatitude": 0x378ADD,
    "seam":       0xEF9F27,
    "regional":   0x1D9E75,
    "method":     0x7F77DD,
    "other":      0x888780,
}


def load_seen() -> dict:
    if SEEN_PATH.exists():
        return json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    return {"reported": []}


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


def post(embeds: list[dict], header: str | None = None) -> None:
    payload = {"embeds": embeds}
    if header:
        payload["content"] = header
    r = requests.post(WEBHOOK, json=payload, timeout=30)
    r.raise_for_status()


def main() -> None:
    scored = json.loads(SCORED_PATH.read_text(encoding="utf-8"))
    if not scored:
        post([], header="今週の新着ヒットはありませんでした。")
        return

    embeds = [to_embed(p) for p in scored]
    for i in range(0, len(embeds), 10):
        chunk = embeds[i:i + 10]
        header = (f"今週の面白そうな論文 {len(scored)} 件（score 高い順）"
                  if i == 0 else None)
        post(chunk, header=header)
        time.sleep(1)  # レート制限に配慮

    seen = load_seen()
    seen["reported"] = sorted(set(seen["reported"]) | {p["id"] for p in scored})
    SEEN_PATH.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"reported {len(scored)} papers; seen store now {len(seen['reported'])} ids")


if __name__ == "__main__":
    main()

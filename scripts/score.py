"""
ステップ2: candidates.json を Claude API に渡し、interests.md を基準に
「面白さ」を 0-10 で採点させる。閾値以上を scored.json に残す。
- 構造化出力(JSON配列)を要求し、安全にパースする
- 件数が多い時は batch_size 件ずつに分割
"""
import json
import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
import yaml
CONFIG = yaml.safe_load((ROOT / "config" / "sources.yml").read_text(encoding="utf-8"))
INTERESTS = (ROOT / "config" / "interests.md").read_text(encoding="utf-8")
CAND_PATH = ROOT / "candidates.json"
OUT_PATH = ROOT / "scored.json"

API_URL = "https://api.anthropic.com/v1/messages"
API_KEY = os.environ["ANTHROPIC_API_KEY"]
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")

SYSTEM = f"""あなたは研究者の論文キュレーターです。以下の興味プロファイルに照らして、
渡された論文が「その研究者にとって面白いか」を厳しめに 0-10 で採点します。

{INTERESTS}

出力は JSON 配列のみ。各要素は必ず次のキーを持つこと:
  "id": 入力の id をそのまま
  "score": 0-10 の整数
  "reason": なぜ面白い/面白くないかを日本語で1文（40字以内）
  "theme": tropical / midlatitude / seam / regional / method / other のいずれか
前置き・後置き・コードフェンスは一切書かず、JSON 配列だけを返すこと。"""


def strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def call_claude(batch: list[dict]) -> list[dict]:
    payload = [{"id": c["id"], "title": c["title"],
                "journal": c["journal"], "abstract": c["abstract"][:1500]}
               for c in batch]
    body = {
        "model": MODEL,
        "max_tokens": 2000,
        "system": SYSTEM,
        "messages": [{"role": "user",
                      "content": "採点対象:\n" + json.dumps(payload, ensure_ascii=False)}],
    }
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    r = requests.post(API_URL, headers=headers, json=body, timeout=120)
    if not r.ok:
        print(f"Anthropic API error {r.status_code}: {r.text}", file=sys.stderr)
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", [])
                   if b.get("type") == "text")
    try:
        return json.loads(strip_fences(text))
    except json.JSONDecodeError:
        print("JSON parse に失敗。スキップ:\n", text[:500])
        return []


def main() -> None:
    candidates = json.loads(CAND_PATH.read_text(encoding="utf-8"))
    if not candidates:
        OUT_PATH.write_text("[]", encoding="utf-8")
        print("候補なし。scored.json は空。")
        return

    by_id = {c["id"]: c for c in candidates}
    n = int(CONFIG["batch_size"])
    verdicts: list[dict] = []
    for i in range(0, len(candidates), n):
        verdicts += call_claude(candidates[i:i + n])

    threshold = int(CONFIG["min_score"])
    kept = []
    for v in verdicts:
        c = by_id.get(v.get("id"))
        if not c or int(v.get("score", 0)) < threshold:
            continue
        kept.append({**c, "score": int(v["score"]),
                     "reason": v.get("reason", ""), "theme": v.get("theme", "other")})

    kept.sort(key=lambda x: x["score"], reverse=True)
    OUT_PATH.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"kept {len(kept)}/{len(candidates)} (score >= {threshold}) -> {OUT_PATH.name}")


if __name__ == "__main__":
    main()

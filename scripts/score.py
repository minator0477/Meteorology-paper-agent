"""
ステップ2: candidates.json を3段階でピックアップする。
第1段（キーワード一致）: keywords.yml のいずれかの語がタイトルに含まれる候補は、
  スコア採点なしで即座に「面白そう」として拾う（採否の判断は機械的・無料）。
  おすすめ理由は常に「キーワード「X」に一致」の定型文で、LLM は呼ばない。
第2段（LLM 採点、Haiku）: 第1段で拾われなかった残りの候補だけを、タイトル+ジャーナル名のみ
  （abstract は渡さない・軽量に）Claude に渡し、interests.md を基準に「面白さ」を 0-10 で
  採点させる。閾値以上を残す。
第3段（おすすめ理由生成、Sonnet）: 第2段で閾値を超えた論文についてのみ、今度は abstract も
  含めて Claude に渡し、おすすめ理由を書かせる（失敗時は第2段が返した簡易理由のまま）。
- 構造化出力(JSON配列)を要求し、安全にパースする
- 件数が多い時は batch_size 件ずつに分割
- 全段の結果を合わせて、全候補の採否結果を history/ 以下に Markdown で記録する
  （キーワード一致 / LLM採点でセクションを分けて記録。閾値未満の候補は第2段の結果のみで、
  追加の API 呼び出しなしで書き出す）
- scored.json の各エントリには method: "keyword" / "llm" を付与し、report.py が
  ピックアップ方法別の表示を出し分けられるようにする
"""
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
import yaml
CONFIG = yaml.safe_load((ROOT / "config" / "sources.yml").read_text(encoding="utf-8"))
INTERESTS = (ROOT / "config" / "interests.md").read_text(encoding="utf-8")
KEYWORDS = yaml.safe_load((ROOT / "config" / "keywords.yml").read_text(encoding="utf-8")) or {}
CAND_PATH = ROOT / "candidates.json"
OUT_PATH = ROOT / "scored.json"
HISTORY_DIR = ROOT / "history"

# キーワード一致で拾った候補に付与する表示用スコア（history.md 用。閾値判定はしない＝無条件で採用）
KEYWORD_SCORE = 10
# keywords.yml 内でテーマが重複したときに、どのテーマを優先するか
THEME_ORDER = ["seam", "tropical", "midlatitude", "regional", "method"]

API_URL = "https://api.anthropic.com/v1/messages"
API_KEY = os.environ["ANTHROPIC_API_KEY"]
# 第2段（採点）: 軽量・低コストな Haiku。タイトル+ジャーナル名のみで判断させる。
SCORE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
# 第3段（おすすめ理由生成）: 採用が決まった論文だけが対象なので、abstract も渡して Sonnet に書かせる。
REASON_MODEL = os.environ.get("ANTHROPIC_REASON_MODEL", "claude-sonnet-5")

SYSTEM = f"""あなたは研究者の論文キュレーターです。以下の興味プロファイルに照らして、
渡された論文が「その研究者にとって面白いか」を厳しめに 0-10 で採点します。
各論文はタイトルとジャーナル名のみが与えられます（抄録は渡されません）。それらから
推測して判断してください。

{INTERESTS}

出力は JSON 配列のみ。各要素は必ず次のキーを持つこと:
  "id": 入力の id をそのまま
  "score": 0-10 の整数
  "reason": なぜ面白い/面白くないかを日本語で1文（40字以内）
  "theme": tropical / midlatitude / seam / regional / method / other のいずれか
前置き・後置き・コードフェンスは一切書かず、JSON 配列だけを返すこと。"""

REASON_SYSTEM = f"""あなたは研究者の論文キュレーターです。以下は研究者の興味プロファイルです。

{INTERESTS}

渡された論文は、いずれもこの研究者にとって「面白そう」だとしてすでに採用が決まっています。
タイトル・ジャーナル名・抄録の内容を踏まえ、なぜおすすめなのかを興味プロファイルに照らして
日本語で1文（40字以内）で述べてください。

出力は JSON 配列のみ。各要素は必ず次のキーを持つこと:
  "id": 入力の id をそのまま
  "reason": おすすめ理由（日本語、40字以内）
前置き・後置き・コードフェンスは一切書かず、JSON 配列だけを返すこと。"""


def match_keyword(candidate: dict) -> tuple[str, str] | None:
    """タイトルにキーワードが含まれていれば (theme, matched_keyword) を返す。"""
    text = candidate["title"].lower()
    for theme in THEME_ORDER:
        for kw in KEYWORDS.get(theme, []):
            if kw.lower() in text:
                return theme, kw
    return None


def strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def call_claude(batch: list[dict]) -> list[dict]:
    payload = [{"id": c["id"], "title": c["title"], "journal": c["journal"]}
               for c in batch]
    body = {
        "model": SCORE_MODEL,
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


def call_claude_reasons(batch: list[dict]) -> dict[str, str]:
    """LLM 採点（第2段）で閾値を超えた候補について、abstract も含めて
    Claude（Sonnet）におすすめ理由を生成させる。キーワード一致分はこの関数の対象外
    （常に定型文のまま）。失敗時は空 dict を返す（呼び出し側が第2段の簡易理由のままにする）。"""
    payload = [{"id": c["id"], "title": c["title"],
                "journal": c["journal"], "abstract": c["abstract"][:1500]}
               for c in batch]
    body = {
        "model": REASON_MODEL,
        "max_tokens": 2000,
        "system": REASON_SYSTEM,
        "messages": [{"role": "user",
                      "content": "対象論文:\n" + json.dumps(payload, ensure_ascii=False)}],
    }
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        r = requests.post(API_URL, headers=headers, json=body, timeout=120)
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", [])
                       if b.get("type") == "text")
        data = json.loads(strip_fences(text))
        return {d["id"]: d["reason"] for d in data if d.get("id") and d.get("reason")}
    except (requests.RequestException, json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"おすすめ理由の生成に失敗（機械的な文言にフォールバック）: {e}", file=sys.stderr)
        return {}


def write_history_markdown(candidates: list[dict], verdicts_by_id: dict[str, dict],
                            threshold: int, out_path: Path) -> None:
    """全候補の採否結果を、ピックアップ方法（キーワード一致 / LLM採点）別に分けて
    Markdown で記録する。LLM 採点は閾値未満も含めて全件記録する。"""
    keyword_rows = []
    llm_rows = []
    for c in candidates:
        v = verdicts_by_id.get(c["id"]) or {}
        if v.get("method") == "keyword":
            keyword_rows.append({
                "title": c["title"],
                "journal": c["journal"],
                "theme": v.get("theme", "-"),
                "matched_keyword": v.get("matched_keyword", "-"),
                "reason": v.get("reason", ""),
                "url": c["url"],
            })
            continue
        score = v.get("score")
        llm_rows.append({
            "score": int(score) if score is not None else -1,
            "score_display": str(score) if score is not None else "N/A",
            "notified": "✅" if score is not None and int(score) >= threshold else "",
            "title": c["title"],
            "journal": c["journal"],
            "theme": v.get("theme", "-"),
            "reason": v.get("reason", "(採点結果の取得に失敗)"),
            "url": c["url"],
        })
    llm_rows.sort(key=lambda r: r["score"], reverse=True)

    llm_notified = sum(1 for r in llm_rows if r["notified"])
    total_notified = len(keyword_rows) + llm_notified
    lines = [
        f"# 論文スコア一覧 - {date.today().isoformat()}",
        "",
        f"全 {len(candidates)} 件中 {total_notified} 件を Discord に通知"
        f"（キーワード一致 {len(keyword_rows)} 件 + LLM採点で{threshold}点以上 {llm_notified} 件）。",
    ]

    if keyword_rows:
        lines += [
            "",
            f"## キーワード一致で採用（{len(keyword_rows)}件）",
            "",
            "| タイトル | ジャーナル | テーマ | 一致キーワード | おすすめ理由 |",
            "|---|---|---|---|---|",
        ]
        for r in keyword_rows:
            title = f"[{r['title']}]({r['url']})".replace("|", "\\|")
            reason = r["reason"].replace("|", "\\|").replace("\n", " ")
            journal = r["journal"].replace("|", "\\|")
            lines.append(f"| {title} | {journal} | {r['theme']} | "
                         f"{r['matched_keyword']} | {reason} |")

    lines += [
        "",
        f"## LLM 採点（{len(llm_rows)}件、{threshold}点以上が通知対象）",
        "",
        "| スコア | 通知 | タイトル | ジャーナル | テーマ | 理由 |",
        "|---|---|---|---|---|---|",
    ]
    for r in llm_rows:
        title = f"[{r['title']}]({r['url']})".replace("|", "\\|")
        reason = r["reason"].replace("|", "\\|").replace("\n", " ")
        journal = r["journal"].replace("|", "\\|")
        lines.append(f"| {r['score_display']} | {r['notified']} | {title} | "
                     f"{journal} | {r['theme']} | {reason} |")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        display_path = out_path.relative_to(ROOT)
    except ValueError:
        display_path = out_path
    print(f"wrote {len(candidates)} rows ({len(keyword_rows)} keyword + {len(llm_rows)} llm) "
          f"-> {display_path}")


def main() -> None:
    candidates = json.loads(CAND_PATH.read_text(encoding="utf-8"))
    if not candidates:
        OUT_PATH.write_text("[]", encoding="utf-8")
        print("候補なし。scored.json は空。")
        return

    by_id = {c["id"]: c for c in candidates}
    n = int(CONFIG["batch_size"])

    # 第1段: キーワード一致で機械的にピックアップ（採否は無条件・LLM 不要）
    keyword_kept = []
    remaining = []
    for c in candidates:
        m = match_keyword(c)
        if m:
            theme, kw = m
            keyword_kept.append({**c, "score": KEYWORD_SCORE, "theme": theme,
                                  "method": "keyword", "matched_keyword": kw,
                                  "reason": f"キーワード「{kw}」に一致"})  # フォールバック文言
        else:
            remaining.append(c)

    # 第2段: 残りをタイトル+ジャーナル名だけで Haiku に採点させる
    verdicts: list[dict] = []
    for i in range(0, len(remaining), n):
        verdicts += call_claude(remaining[i:i + n])

    threshold = int(CONFIG["min_score"])
    llm_kept = []
    for v in verdicts:
        c = by_id.get(v.get("id"))
        if not c or int(v.get("score", 0)) < threshold:
            continue
        llm_kept.append({**c, "score": int(v["score"]), "method": "llm",
                          "reason": v.get("reason", ""),  # フォールバック文言（第2段の簡易理由）
                          "theme": v.get("theme", "other")})

    # 第3段: LLM採点で閾値を超えた論文についてのみ、abstract を含めた情報で Sonnet に
    # おすすめ理由を書かせる（失敗時は第2段の簡易理由のまま）。
    # キーワード一致分は常に「キーワード「X」に一致」の定型文のまま（LLM を呼ばない）。
    if llm_kept:
        reasons: dict[str, str] = {}
        for i in range(0, len(llm_kept), n):
            reasons.update(call_claude_reasons(llm_kept[i:i + n]))
        for k in llm_kept:
            if k["id"] in reasons:
                k["reason"] = reasons[k["id"]]

    kept = keyword_kept + llm_kept
    verdicts_by_id = {v["id"]: {**v, "method": "llm"} for v in verdicts if v.get("id")}
    for k in kept:
        entry = {"id": k["id"], "score": k["score"], "reason": k["reason"],
                  "theme": k["theme"], "method": k["method"]}
        if k["method"] == "keyword":
            entry["matched_keyword"] = k["matched_keyword"]
        verdicts_by_id[k["id"]] = entry
    write_history_markdown(candidates, verdicts_by_id, threshold,
                            HISTORY_DIR / f"{date.today().isoformat()}.md")

    kept.sort(key=lambda x: x["score"], reverse=True)
    OUT_PATH.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"keyword-matched {len(keyword_kept)}, LLM-kept "
          f"{len(llm_kept)}/{len(remaining)} (score >= {threshold}) -> {OUT_PATH.name}")


if __name__ == "__main__":
    main()

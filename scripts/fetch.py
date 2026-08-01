"""
ステップ1: OpenAlex から、指定ジャーナル(ISSN)・著者(ID)の直近論文を機械的に取得する。
- seen.json に既にある論文は除外（重複排除）
- 結果を candidates.json に書き出す
OpenAlex は無認証で使えるが、mailto を付けると "polite pool" で安定する。
"""
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = yaml.safe_load((ROOT / "config" / "sources.yml").read_text(encoding="utf-8"))
SEEN_PATH = ROOT / "state" / "seen.json"
OUT_PATH = ROOT / "candidates.json"

OPENALEX = "https://api.openalex.org/works"
MAILTO = os.environ.get("OPENALEX_MAILTO", "")  # 任意。設定推奨


def load_seen() -> set:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text(encoding="utf-8")).get("reported", []))
    return set()


def reconstruct_abstract(inv: dict | None) -> str:
    """OpenAlex は abstract_inverted_index 形式なので平文に戻す。"""
    if not inv:
        return ""
    positions = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def fetch(filter_str: str) -> list[dict]:
    """1 つの filter で works を取得（ページングは 1 ページ 200 件で十分想定）。"""
    params = {
        "filter": filter_str,
        "per-page": "200",
        "sort": "publication_date:desc",
        "select": "id,doi,title,publication_date,authorships,"
                  "primary_location,best_oa_location,abstract_inverted_index",
    }
    if MAILTO:
        params["mailto"] = MAILTO
    q = "&".join(f"{k}={quote(str(v), safe=':|,>-')}" for k, v in params.items())
    r = requests.get(f"{OPENALEX}?{q}", timeout=60)
    r.raise_for_status()
    return r.json().get("results", [])


def to_record(w: dict) -> dict:
    src = (w.get("primary_location") or {}).get("source") or {}
    oa = w.get("best_oa_location") or {}
    authors = [a["author"]["display_name"]
               for a in (w.get("authorships") or []) if a.get("author")]
    return {
        "id": w["id"].rsplit("/", 1)[-1],           # 例: W1234567890
        "doi": w.get("doi"),
        "title": w.get("title") or "(no title)",
        "authors": authors,
        "journal": src.get("display_name") or "",
        "date": w.get("publication_date") or "",
        "abstract": reconstruct_abstract(w.get("abstract_inverted_index")),
        "url": w.get("doi") or w["id"],
        "oa_pdf": oa.get("pdf_url") or "",           # 合法にDLできるPDF（あれば）
    }


def main() -> None:
    seen = load_seen()
    since = (date.today() - timedelta(days=int(CONFIG["lookback_days"]))).isoformat()

    filters = []
    issns = CONFIG.get("journals", {}).get("issns") or []
    if issns:
        j = "|".join(issns)
        filters.append(f"primary_location.source.issn:{j},from_publication_date:{since}")
    author_ids = CONFIG.get("authors", {}).get("ids") or []
    if author_ids:
        a = "|".join(author_ids)
        filters.append(f"author.id:{a},from_publication_date:{since}")

    if not filters:
        print("sources.yml にジャーナルも著者も設定されていません。", file=sys.stderr)
        sys.exit(1)

    records: dict[str, dict] = {}
    for f in filters:
        for w in fetch(f):
            rec = to_record(w)
            if rec["id"] in seen:
                continue
            records[rec["id"]] = rec  # id で自然に重複統合（著者×ジャーナル両取りでも1件）

    out = list(records.values())
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"fetched {len(out)} new candidates (since {since}) -> {OUT_PATH.name}")


if __name__ == "__main__":
    main()

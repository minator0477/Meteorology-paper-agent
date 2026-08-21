"""
ステップ2: candidates.json を、config/interests.md のテーマ別代表文との
埋め込みベクトル・コサイン類似度で採点する（LLM API は使わない）。
- interests.md の `## <theme>` 見出しごとの本文をテーマ代表ベクトルとして埋め込む
- 各候補（title + abstract）を埋め込み、最も類似度の高いテーマとその類似度を採点に使う
- 類似度は sources.yml の embedding.similarity_low/high で 0-10 のスコアに線形マッピングする
  （どのテーマにも類似度 similarity_low 以下しかない候補は theme=other とする）
- 閾値未満も含む全候補の採点結果を history/ 以下に Markdown で記録する
  （追加の外部呼び出しは発生しない。ローカルで計算した結果を書き出すだけ）
"""
import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import yaml
from sentence_transformers import util

from embedding_util import THEMES, get_model

ROOT = Path(__file__).resolve().parent.parent
CONFIG = yaml.safe_load((ROOT / "config" / "sources.yml").read_text(encoding="utf-8"))
INTERESTS_TEXT = (ROOT / "config" / "interests.md").read_text(encoding="utf-8")
CAND_PATH = ROOT / "candidates.json"
OUT_PATH = ROOT / "scored.json"
HISTORY_DIR = ROOT / "history"
VECTORS_PATH = ROOT / "state" / "theme_vectors.json"

EMB_CONFIG = CONFIG.get("embedding") or {}
MODEL_NAME = EMB_CONFIG.get("model", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
SIMILARITY_LOW = float(EMB_CONFIG.get("similarity_low", 0.05))
SIMILARITY_HIGH = float(EMB_CONFIG.get("similarity_high", 0.55))
MAX_SEQ_LENGTH = int(EMB_CONFIG.get("max_seq_length", 384))
FEEDBACK_WEIGHT = float(EMB_CONFIG.get("feedback_weight", 0.5))


def parse_theme_sections(text: str) -> dict[str, str]:
    """`## <theme>` 見出しごとの本文を取り出す。既知テーマ以外の見出しは無視する。"""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = re.match(r"^##\s+(\S+)", line)
        if m:
            name = m.group(1).strip().lower()
            current = name if name in THEMES else None
            if current:
                sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)

    joined = {t: "\n".join(lines).strip() for t, lines in sections.items()}
    missing = [t for t in THEMES if not joined.get(t)]
    if missing:
        raise ValueError(f"interests.md に次のテーマ見出しの本文がありません: {missing}")
    return joined


def similarity_to_score(sim: float) -> int:
    if SIMILARITY_HIGH <= SIMILARITY_LOW:
        raise ValueError("embedding.similarity_high は similarity_low より大きくしてください")
    scaled = (sim - SIMILARITY_LOW) / (SIMILARITY_HIGH - SIMILARITY_LOW) * 10
    return max(0, min(10, round(scaled)))


def write_history_markdown(candidates: list[dict], verdicts_by_id: dict[str, dict],
                            threshold: int, out_path: Path) -> None:
    """閾値未満も含めた全候補の採点結果を Markdown で記録する。"""
    rows = []
    for c in candidates:
        v = verdicts_by_id.get(c["id"])
        score = v.get("score") if v else None
        rows.append({
            "score": int(score) if score is not None else -1,
            "score_display": str(score) if score is not None else "N/A",
            "notified": "✅" if score is not None and int(score) >= threshold else "",
            "title": c["title"],
            "journal": c["journal"],
            "theme": (v or {}).get("theme", "-"),
            "reason": (v or {}).get("reason", "(採点結果の取得に失敗)"),
            "url": c["url"],
        })
    rows.sort(key=lambda r: r["score"], reverse=True)

    notified = sum(1 for r in rows if r["notified"])
    lines = [
        f"# 論文スコア一覧 - {date.today().isoformat()}",
        "",
        f"全 {len(rows)} 件中 {notified} 件が閾値（{threshold}点以上）でDiscordに通知されました。",
        "",
        "| スコア | 通知 | タイトル | ジャーナル | テーマ | 理由 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        title = f"[{r['title']}]({r['url']})".replace("|", "\\|")
        reason = r["reason"].replace("|", "\\|").replace("\n", " ")
        journal = r["journal"].replace("|", "\\|")
        lines.append(f"| {r['score_display']} | {r['notified']} | {title} | "
                     f"{journal} | {r['theme']} | {reason} |")

    HISTORY_DIR.mkdir(exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} rows -> {out_path.relative_to(ROOT)}")


def load_theme_vectors() -> dict:
    """フィードバックで学習した、テーマごとの累積ずれベクトルを読む。
    ファイルが無い/モデルが変わっていれば空を返す（ベースベクトルのみで採点、後方互換）。"""
    if not VECTORS_PATH.exists():
        return {}
    data = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    if data.get("model") != MODEL_NAME:
        return {}
    return data.get("themes", {})


def apply_feedback(theme_names: list[str], base_embeddings: np.ndarray) -> np.ndarray:
    """interests.md 由来のベースベクトルに、学習済みフィードバックのずれを
    feedback_weight で足し込んで再正規化する。"""
    theme_vectors = load_theme_vectors()
    if not theme_vectors or FEEDBACK_WEIGHT <= 0:
        return base_embeddings
    out = np.array(base_embeddings, dtype=float)
    for i, theme in enumerate(theme_names):
        entry = theme_vectors.get(theme)
        if not entry:
            continue
        delta = np.array(entry["vector"], dtype=float)
        norm = np.linalg.norm(delta)
        if norm < 1e-9:
            continue
        combined = out[i] + FEEDBACK_WEIGHT * (delta / norm)
        out[i] = combined / np.linalg.norm(combined)
    return out.astype(base_embeddings.dtype)


def score_candidates(candidates: list[dict], theme_texts: dict[str, str]) -> dict[str, dict]:
    model = get_model(MODEL_NAME, MAX_SEQ_LENGTH)
    batch_size = int(CONFIG.get("batch_size", 25))

    theme_names = list(theme_texts.keys())
    base_embeddings = model.encode([theme_texts[t] for t in theme_names],
                                    normalize_embeddings=True)
    theme_embeddings = apply_feedback(theme_names, base_embeddings)

    cand_texts = [f"{c['title']}\n\n{c['abstract']}".strip() for c in candidates]
    cand_embeddings = model.encode(cand_texts, batch_size=batch_size,
                                    normalize_embeddings=True, show_progress_bar=False)

    sims = util.cos_sim(cand_embeddings, theme_embeddings)  # [n_candidates, n_themes]

    verdicts_by_id = {}
    for c, row in zip(candidates, sims):
        best_idx = int(row.argmax())
        best_theme = theme_names[best_idx]
        best_sim = float(row[best_idx])
        score = similarity_to_score(best_sim)
        verdicts_by_id[c["id"]] = {
            "score": score,
            # スコア0(= similarity_low 以下)はどのテーマにも強く一致しなかったとみなす
            "theme": best_theme if score > 0 else "other",
            "reason": f"「{best_theme}」との埋め込み類似度 {best_sim:.2f}",
        }
    return verdicts_by_id


def main() -> None:
    candidates = json.loads(CAND_PATH.read_text(encoding="utf-8"))
    if not candidates:
        OUT_PATH.write_text("[]", encoding="utf-8")
        print("候補なし。scored.json は空。")
        return

    theme_texts = parse_theme_sections(INTERESTS_TEXT)
    verdicts_by_id = score_candidates(candidates, theme_texts)

    threshold = int(CONFIG["min_score"])
    write_history_markdown(candidates, verdicts_by_id, threshold,
                            HISTORY_DIR / f"{date.today().isoformat()}.md")

    kept = []
    for c in candidates:
        v = verdicts_by_id[c["id"]]
        if v["score"] < threshold:
            continue
        kept.append({**c, "score": v["score"], "reason": v["reason"], "theme": v["theme"]})

    kept.sort(key=lambda x: x["score"], reverse=True)
    OUT_PATH.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"kept {len(kept)}/{len(candidates)} (score >= {threshold}) -> {OUT_PATH.name}")


if __name__ == "__main__":
    main()

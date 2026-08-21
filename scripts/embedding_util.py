"""
score.py と collect_feedback.py で共有する埋め込みモデルのロード処理と定数。
"""
from sentence_transformers import SentenceTransformer

THEMES = ["tropical", "midlatitude", "seam", "regional", "method"]

_model_cache: dict[str, SentenceTransformer] = {}


def get_model(model_name: str, max_seq_length: int) -> SentenceTransformer:
    model = _model_cache.get(model_name)
    if model is None:
        model = SentenceTransformer(model_name)
        model.max_seq_length = max_seq_length
        _model_cache[model_name] = model
    return model

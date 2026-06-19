"""Local semantic index over project text.

Embeddings are computed by a LOCAL sentence-transformers model (no API key) and
stored in a gitignored numpy file under ``index/`` — nothing leaves this machine
(per CLAUDE.md). The corpus is tiny (~36k projects), so a brute-force cosine
search over a normalised matrix is plenty fast; no FAISS needed.

Build:  studio-index            (or: python -m studio_agent.index)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Small, fast, CPU-friendly model good for short project text (384-dim).
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_ROOT = Path(__file__).resolve().parents[2]
INDEX_DIR = _ROOT / "index"
INDEX_PATH = INDEX_DIR / "projects.npz"

_model = None
_cache: tuple[Any, Any] | None = None  # (ids: ndarray, emb: ndarray)


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME)
    return _model


def available() -> bool:
    return INDEX_PATH.exists()


def build_index(batch_size: int = 256) -> int:
    """Embed all non-deleted projects and persist the index. Returns the count."""
    import numpy as np

    from . import repository as repo

    rows = repo.projects_for_index()
    if not rows:
        return 0
    ids = np.array([r["project_id"] for r in rows], dtype=np.int64)
    texts = [r["text"] for r in rows]

    emb = _get_model().encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,  # cosine == dot product
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype("float32")

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.savez(INDEX_PATH, ids=ids, emb=emb, model=np.array(MODEL_NAME))
    _invalidate()
    return int(len(ids))


def _invalidate() -> None:
    global _cache
    _cache = None


def _load():
    global _cache
    if _cache is None:
        if not available():
            return None
        import numpy as np

        data = np.load(INDEX_PATH, allow_pickle=True)
        _cache = (data["ids"], data["emb"])
    return _cache


def search(query: str, limit: int = 10) -> list[tuple[int, float]]:
    """Return [(project_id, cosine_similarity), ...] best first, or [] if no index."""
    loaded = _load()
    if loaded is None or not query.strip():
        return []
    import numpy as np

    ids, emb = loaded
    q = _get_model().encode(
        [query], normalize_embeddings=True, convert_to_numpy=True
    ).astype("float32")[0]
    sims = emb @ q  # both normalised -> cosine similarity
    k = min(limit, len(ids))
    top = np.argpartition(-sims, k - 1)[:k]
    top = top[np.argsort(-sims[top])]
    return [(int(ids[i]), float(sims[i])) for i in top]


def main() -> None:
    print(f"Building semantic index with {MODEL_NAME} …")
    n = build_index()
    print(f"Indexed {n} projects -> {INDEX_PATH}")


if __name__ == "__main__":
    main()

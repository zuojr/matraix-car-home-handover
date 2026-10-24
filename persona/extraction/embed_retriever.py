"""Embedding retrieval stage — the *semantic* half of the RAG retriever.

Where the regex matcher (``regex_matcher.py``) is literal — it only surfaces a
dimension when the prompt contains that dimension's value or topic *word* — this
retriever works by meaning. It embeds a short descriptor of every dimension
("<label>. <description>. options: <values>") once, caches the matrix, and at
query time returns the dimensions whose descriptor is closest to the prompt by
cosine similarity.

That closes the recall gap the regex stage can't: "she writes models at a hedge
fund" has no literal overlap with ``fam_quantitative_trading``'s values, but its
*embedding* is near that dimension's descriptor, so it still becomes a candidate
for the LLM judge to rule on.

Backend: local ``sentence-transformers`` (default
``paraphrase-multilingual-MiniLM-L12-v2`` via ``$TREIVER_EMBED_MODEL``) — offline,
free, no token. The model is loaded lazily and the dimension matrix is cached on
disk, so the first call pays the encode cost and later calls are instant.

The default is multilingual (en/zh/ja/ko/es/pt and 50+ others). For English-only
latency, set ``TREIVER_EMBED_MODEL=all-MiniLM-L6-v2``. For higher multilingual
quality, prefer ``paraphrase-multilingual-mpnet-base-v2``.

If ``sentence-transformers`` is unavailable, this module degrades to a keyword
overlap scorer so the pipeline still runs (lower recall, zero dependency).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

from .schema import Dimension, DimensionSchema

_DEFAULT_MODEL = os.environ.get(
    "TREIVER_EMBED_MODEL",
    # Covers Playground UI locales: en, zh, ja, ko, es, pt (+ 50).
    # Faster MiniLM sibling; override with mpnet-base-v2 for max quality.
    "paraphrase-multilingual-MiniLM-L12-v2",
)
_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".embed_cache")


@dataclass
class EmbedHit:
    """One dimension retrieved by semantic similarity."""

    dimension_id: str
    score: float  # cosine similarity in [-1, 1] (or overlap ratio in fallback)


def _dimension_text(
    dim: Dimension,
    overlay: dict | None = None,
) -> str:
    """The descriptor we embed for a dimension — label, gloss, and its values.

    When ``overlay`` is a label-pack entry ``{label, values}``, append the
    localized label/value strings so non-English queries can still retrieve
    the same canonical dimension (values emitted later stay English).
    """
    values = ", ".join(dim.values)
    base = f"{dim.label}. {dim.description} Options: {values}."
    if not isinstance(overlay, dict):
        return base
    loc_label = overlay.get("label")
    loc_values = overlay.get("values")
    parts: list[str] = []
    if isinstance(loc_label, str) and loc_label.strip() and loc_label.strip() != dim.label:
        parts.append(loc_label.strip())
    if isinstance(loc_values, dict):
        paired: list[str] = []
        for value in dim.values:
            translated = loc_values.get(value)
            if isinstance(translated, str) and translated.strip() and translated.strip() != value:
                paired.append(f"{value} ({translated.strip()})")
            else:
                paired.append(value)
        if paired:
            parts.append("Options: " + ", ".join(paired))
    if not parts:
        return base
    return f"{base} Localized: {'. '.join(parts)}."


class EmbedRetriever:
    """Semantic retriever over dimension descriptors.

    Parameters
    ----------
    schema:
        The dimension taxonomy.
    model_name:
        A sentence-transformers model id. Defaults to ``all-MiniLM-L6-v2`` (or
        ``$TREIVER_EMBED_MODEL``). Prefer a multilingual model (for example
        ``paraphrase-multilingual-MiniLM-L12-v2``) when queries are often
        non-English.
    encoder:
        Inject a pre-built encoder (anything with ``encode(list[str]) -> ndarray``)
        — used by tests to avoid loading a real model.
    label_overlays:
        Optional ``{dimension_id: {label, values}}`` from a locale label pack.
    cache_key:
        Extra cache-key fragment (typically the UI locale) so localized
        descriptor matrices do not collide with the English default.
    """

    def __init__(
        self,
        schema: DimensionSchema,
        model_name: str = _DEFAULT_MODEL,
        encoder=None,
        label_overlays: dict[str, dict] | None = None,
        cache_key: str | None = None,
    ) -> None:
        self.schema = schema
        self.model_name = model_name
        self._encoder = encoder
        self._dim_ids: list[str] = [d.id for d in schema]
        self._label_overlays = label_overlays or {}
        self._cache_key = (cache_key or "").strip()
        self._matrix = None  # lazily built (num_dims, dim) unit vectors
        self._fallback = False  # True once we've dropped to keyword overlap

    # -- encoder / matrix -----------------------------------------------------

    def _get_encoder(self):
        if self._encoder is not None:
            return self._encoder
        from sentence_transformers import SentenceTransformer  # lazy, heavy

        self._encoder = SentenceTransformer(self.model_name)
        return self._encoder

    def _cache_path(self) -> str:
        # Key the cache by model + schema + locale overlay so it invalidates on change.
        overlay_sig = ""
        if self._label_overlays:
            # Stable short fingerprint — full JSON is large.
            blob = repr(sorted((k, self._label_overlays[k]) for k in sorted(self._label_overlays)))
            overlay_sig = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]
        sig = hashlib.sha1(
            (
                self.model_name
                + "|"
                + self._cache_key
                + "|"
                + overlay_sig
                + "|"
                + "|".join(self._dim_ids)
            ).encode("utf-8")
        ).hexdigest()[:16]
        return os.path.join(_CACHE_DIR, f"dims-{sig}.npy")

    def _build_matrix(self):
        import numpy as np

        # Only use the on-disk cache for the default model. An injected encoder
        # (tests, custom models) produces vectors the cache key can't identify,
        # so caching it would corrupt later runs — encode fresh instead.
        use_cache = self._encoder is None
        cache = self._cache_path() if use_cache else None
        if cache and os.path.exists(cache):
            return np.load(cache)

        texts = [
            _dimension_text(self.schema.get(i), self._label_overlays.get(i))
            for i in self._dim_ids
        ]
        vecs = self._get_encoder().encode(
            texts, batch_size=64, show_progress_bar=False, convert_to_numpy=True
        )
        vecs = _l2_normalize(np.asarray(vecs, dtype="float32"))
        if cache:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            try:
                np.save(cache, vecs)
            except OSError:
                pass  # cache is an optimization, not a requirement
        return vecs

    def _ensure_matrix(self):
        if self._matrix is not None:
            return
        try:
            self._matrix = self._build_matrix()
        except Exception:
            # sentence-transformers missing or model load failed → keyword mode.
            self._fallback = True

    # -- query ----------------------------------------------------------------

    def retrieve(
        self, prompt: str, top_k: int = 12, min_score: float = 0.25
    ) -> list[EmbedHit]:
        """Return up to ``top_k`` dimensions most similar to ``prompt``.

        Only hits at or above ``min_score`` are returned. Falls back to keyword
        overlap if embeddings are unavailable.
        """
        self._ensure_matrix()
        if self._fallback or self._matrix is None:
            return self._retrieve_keyword(prompt, top_k, min_score)

        import numpy as np

        q = self._get_encoder().encode(
            [prompt], show_progress_bar=False, convert_to_numpy=True
        )
        q = _l2_normalize(np.asarray(q, dtype="float32"))[0]
        sims = self._matrix @ q  # cosine, since both sides are unit vectors
        order = np.argsort(-sims)[:top_k]
        return [
            EmbedHit(self._dim_ids[i], float(sims[i]))
            for i in order
            if sims[i] >= min_score
        ]

    def best_value(
        self,
        prompt: str,
        dimension_id: str,
        *,
        min_score: float = 0.42,
        min_margin: float = 0.06,
    ) -> tuple[str, float] | None:
        """Pick the closest allowed English value for ``dimension_id``.

        Used by Playground ``keyword_and_embed`` search (no LLM judge): recall a
        dimension, then assign a closed-set value by embedding similarity.
        Requires a clear winner (``min_margin`` over 2nd place) so ambiguous
        short prompts do not invent weak enum assignments — use ``keyword_and_embed_and_llm`` mode
        when you need those.
        """
        dim = self.schema.get(dimension_id)
        if dim is None or not dim.values:
            return None
        overlay = self._label_overlays.get(dimension_id)
        loc_values = overlay.get("values") if isinstance(overlay, dict) else None
        texts: list[str] = []
        for value in dim.values:
            translated = None
            if isinstance(loc_values, dict):
                raw = loc_values.get(value)
                if isinstance(raw, str) and raw.strip() and raw.strip() != value:
                    translated = raw.strip()
            texts.append(f"{value} ({translated})" if translated else value)

        self._ensure_matrix()
        if self._fallback or self._matrix is None:
            # Keyword fallback: overlap prompt tokens with value strings.
            p_words = _content_words(prompt)
            if not p_words:
                return None
            ranked: list[tuple[str, float]] = []
            for value, text in zip(dim.values, texts):
                v_words = _content_words(text)
                if not v_words:
                    continue
                score = len(p_words & v_words) / max(len(p_words), 1)
                ranked.append((value, float(score)))
            ranked.sort(key=lambda item: -item[1])
            if not ranked or ranked[0][1] < min_score:
                return None
            if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < min_margin:
                return None
            return ranked[0]

        import numpy as np

        encoder = self._get_encoder()
        q = encoder.encode([prompt], show_progress_bar=False, convert_to_numpy=True)
        q = _l2_normalize(np.asarray(q, dtype="float32"))[0]
        vecs = encoder.encode(
            texts, batch_size=64, show_progress_bar=False, convert_to_numpy=True
        )
        vecs = _l2_normalize(np.asarray(vecs, dtype="float32"))
        sims = vecs @ q
        order = np.argsort(-sims)
        best_i = int(order[0])
        best_score = float(sims[best_i])
        second = float(sims[int(order[1])]) if len(order) > 1 else -1.0
        if best_score < min_score or best_score - second < min_margin:
            return None
        return dim.values[best_i], best_score

    def candidate_dimension_ids(
        self, prompt: str, top_k: int = 12, min_score: float = 0.25
    ) -> list[str]:
        return [h.dimension_id for h in self.retrieve(prompt, top_k, min_score)]

    # -- keyword fallback -----------------------------------------------------

    def _retrieve_keyword(self, prompt: str, top_k: int, min_score: float):
        """Dependency-free fallback: Jaccard-ish overlap on content words."""
        p_words = _content_words(prompt)
        if not p_words:
            return []
        scored: list[EmbedHit] = []
        for dim_id in self._dim_ids:
            d_words = _content_words(
                _dimension_text(self.schema.get(dim_id), self._label_overlays.get(dim_id))
            )
            if not d_words:
                continue
            overlap = len(p_words & d_words) / len(p_words)
            if overlap >= min_score:
                scored.append(EmbedHit(dim_id, overlap))
        scored.sort(key=lambda h: -h.score)
        return scored[:top_k]


def _l2_normalize(mat):
    import numpy as np

    norms = np.linalg.norm(mat, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


_STOP = frozenset(
    "a an the of in on at to for with and or is are be by who works work lives "
    "this that person options based their her his".split()
)


def _content_words(text: str) -> set[str]:
    return {w for w in re.split(r"\W+", text.lower()) if w and w not in _STOP and len(w) > 2}

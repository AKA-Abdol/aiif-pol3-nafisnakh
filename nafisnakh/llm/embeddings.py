"""Persian embeddings via a local Ollama instance.

Benchmarked on Persian complaint prose (PLAN §1.9), same-mechanism pairs versus
unrelated pairs:

| model                    | dim  | same  | other | ratio | speed (4 texts) |
|--------------------------|------|-------|-------|-------|-----------------|
| ``bge-m3:567m``          | 1024 | 0.590 | 0.454 | 1.30  | 1.6 s           |
| ``qwen3-embedding:8b-q8_0`` | 4096 | 0.406 | 0.274 | 1.48  | 5.1 s           |

Both discriminate correctly; qwen3 separates better, bge-m3 is 3× faster and is
the default. Every text goes through :func:`normalize_fa` first — that alone
collapsed 11.5% of the raw complaint vocabulary as orthographic noise.

Ollama is optional. When it is not reachable, :class:`OllamaEmbeddings` raises
:class:`EmbeddingsUnavailable` rather than returning zeros, so a caller can
never mistake "no embedding backend" for "these texts are unrelated".
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import httpx
import numpy as np

from ..config import Settings, get_settings
from ..io.normalize import normalize_fa

log = logging.getLogger(__name__)


class EmbeddingsUnavailable(RuntimeError):
    """Raised when no embedding backend can be reached."""


class OllamaEmbeddings:
    """POST ``/api/embed`` with ``{"model": ..., "input": [...]}``."""

    def __init__(self, settings: Settings | None = None, model: str | None = None):
        self.settings = settings or get_settings()
        self.model = model or self.settings.embed_model
        self.host = self.settings.ollama_host.rstrip("/")
        self._cache_dir = Path(self.settings.cache_dir) / "embeddings"

    # ----------------------------------------------------------- availability
    def available(self, timeout: float = 2.0) -> bool:
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=timeout)
            r.raise_for_status()
            models = {m["name"] for m in r.json().get("models", [])}
            return self.model in models or not models
        except Exception:
            return False

    # ------------------------------------------------------------------ embed
    def _cache_path(self, text: str) -> Path:
        key = hashlib.sha1(f"{self.model}|{text}".encode()).hexdigest()
        return self._cache_dir / f"{key}.json"

    def embed(self, texts: list[str], *, use_cache: bool = True) -> np.ndarray:
        normalised = [normalize_fa(t) for t in texts]
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        vectors: dict[int, list[float]] = {}
        pending: list[int] = []
        for i, t in enumerate(normalised):
            path = self._cache_path(t)
            if use_cache and path.exists():
                vectors[i] = json.loads(path.read_text())
            else:
                pending.append(i)

        if pending:
            try:
                r = httpx.post(
                    f"{self.host}/api/embed",
                    json={"model": self.model, "input": [normalised[i] for i in pending]},
                    timeout=120.0,
                )
                r.raise_for_status()
                got = r.json()["embeddings"]
            except Exception as exc:
                raise EmbeddingsUnavailable(
                    f"Ollama at {self.host} did not answer for model {self.model!r}: {exc}"
                ) from exc
            for i, vec in zip(pending, got):
                vectors[i] = vec
                if use_cache:
                    self._cache_path(normalised[i]).write_text(json.dumps(vec))

        return np.array([vectors[i] for i in range(len(texts))], dtype=float)


def cosine_matrix(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    unit = vectors / np.where(norms == 0, 1.0, norms)
    return unit @ unit.T


def get_embeddings(settings: Settings | None = None) -> OllamaEmbeddings:
    return OllamaEmbeddings(settings)

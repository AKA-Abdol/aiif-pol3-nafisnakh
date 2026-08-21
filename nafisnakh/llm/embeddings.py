"""Persian embeddings, from a local daemon or from OpenRouter.

`NN_EMBED_BACKEND` chooses; nothing above this module knows which one answered.

| backend      | model            | dim  | needs                        |
|--------------|------------------|------|------------------------------|
| ``ollama``   | ``bge-m3:567m``  | 1024 | a running Ollama daemon      |
| ``openrouter`` | ``baai/bge-m3`` | 1024 | ``OPENROUTER_API_KEY``       |

Both defaults are **the same model**, so switching backends does not move the
vector geometry and the PLAN §1.9 Persian benchmark still describes it:

| model                    | dim  | same  | other | ratio | speed (4 texts) |
|--------------------------|------|-------|-------|-------|-----------------|
| ``bge-m3``               | 1024 | 0.590 | 0.454 | 1.30  | 1.6 s           |
| ``qwen3-embedding:8b_q8`` | 4096 | 0.406 | 0.274 | 1.48  | 5.1 s           |

Every text goes through :func:`normalize_fa` first — that alone collapsed 11.5%
of the raw complaint vocabulary as orthographic noise.

Neither backend is guaranteed to be there. When one cannot be reached it raises
:class:`EmbeddingsUnavailable` rather than returning zeros, so a caller can never
mistake "no embedding backend" for "these texts are unrelated". The disk cache is
keyed on model *and* backend, so vectors from one never answer for the other.
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


class BaseEmbeddings:
    """Shared normalisation, caching and batching.

    A subclass implements exactly one method, :meth:`_embed_batch`, which turns
    already-normalised texts into vectors or raises. Everything the callers rely
    on — Persian normalisation, the on-disk cache, the ndarray shape — lives here
    so the two backends cannot drift apart.
    """

    backend: str = "base"

    def __init__(self, settings: Settings | None = None, model: str | None = None):
        self.settings = settings or get_settings()
        self.model = model or self.settings.active_embed_model
        self._cache_dir = Path(self.settings.cache_dir) / "embeddings"

    # ----------------------------------------------------------- to implement
    def available(self, timeout: float = 2.0) -> bool:
        raise NotImplementedError

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    # ----------------------------------------------------------------- shared
    def _cache_path(self, text: str) -> Path:
        key = hashlib.sha1(f"{self.backend}|{self.model}|{text}".encode()).hexdigest()
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
            got = self._embed_batch([normalised[i] for i in pending])
            for i, vec in zip(pending, got):
                vectors[i] = vec
                if use_cache:
                    self._cache_path(normalised[i]).write_text(json.dumps(vec))

        return np.array([vectors[i] for i in range(len(texts))], dtype=float)


class OllamaEmbeddings(BaseEmbeddings):
    """POST ``/api/embed`` with ``{"model": ..., "input": [...]}``."""

    backend = "ollama"

    def __init__(self, settings: Settings | None = None, model: str | None = None):
        super().__init__(settings, model or (settings or get_settings()).embed_model)
        self.host = self.settings.ollama_host.rstrip("/")

    def available(self, timeout: float = 2.0) -> bool:
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=timeout)
            r.raise_for_status()
            models = {m["name"] for m in r.json().get("models", [])}
            return self.model in models or not models
        except Exception:
            return False

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            r = httpx.post(
                f"{self.host}/api/embed",
                json={"model": self.model, "input": texts},
                timeout=120.0,
            )
            r.raise_for_status()
            return r.json()["embeddings"]
        except Exception as exc:
            raise EmbeddingsUnavailable(
                f"Ollama at {self.host} did not answer for model {self.model!r}: {exc}"
            ) from exc


class OpenRouterEmbeddings(BaseEmbeddings):
    """POST ``/embeddings`` — the OpenAI-shaped route, same key as generation.

    The response comes back in ``data`` and is **not** guaranteed to be in
    request order, so vectors are placed by their own ``index`` rather than by
    position; a silent transposition here would corrupt every similarity.
    """

    backend = "openrouter"

    def __init__(self, settings: Settings | None = None, model: str | None = None):
        super().__init__(
            settings, model or (settings or get_settings()).openrouter_embed_model
        )
        self.base_url = self.settings.embed_base_url.rstrip("/")

    @property
    def _key(self) -> str | None:
        return self.settings.openrouter_api_key

    def available(self, timeout: float = 2.0) -> bool:
        return bool(self._key)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not self._key:
            raise EmbeddingsUnavailable(
                "OPENROUTER_API_KEY is not set, so the openrouter embedding "
                "backend cannot run. Set the key, or NN_EMBED_BACKEND=ollama."
            )
        try:
            r = httpx.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": self.model, "input": texts},
                timeout=120.0,
            )
            r.raise_for_status()
            rows = r.json()["data"]
        except Exception as exc:
            raise EmbeddingsUnavailable(
                f"OpenRouter at {self.base_url} did not answer for model "
                f"{self.model!r}: {exc}"
            ) from exc
        ordered = sorted(rows, key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in ordered]


BACKENDS: dict[str, type[BaseEmbeddings]] = {
    "ollama": OllamaEmbeddings,
    "openrouter": OpenRouterEmbeddings,
}


def cosine_matrix(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    unit = vectors / np.where(norms == 0, 1.0, norms)
    return unit @ unit.T


def get_embeddings(
    settings: Settings | None = None, backend: str | None = None
) -> BaseEmbeddings:
    """The embedding backend named by ``NN_EMBED_BACKEND`` (or ``backend``)."""
    st = settings or get_settings()
    name = backend or st.embed_backend
    if name not in BACKENDS:
        raise ValueError(
            f"unknown embed_backend {name!r}; available: {sorted(BACKENDS)}"
        )
    return BACKENDS[name](st)

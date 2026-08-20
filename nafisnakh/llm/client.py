"""Generation behind a swappable interface: LangChain → OpenRouter.

Q3 fixed the shape of this: embeddings run locally on Ollama, generation goes
through LangChain/LangGraph to OpenRouter on ``google/gemini-2.0-flash-001``,
cheap first, upgradeable later. Q14 says the API key arrives later — so every
call site here has to work without one.

Three modes, and which one produced an answer is always recorded on the answer
itself. Nothing in this package is allowed to silently degrade:

* ``live``   — a real key is present; calls go to OpenRouter.
* ``cached`` — a previous live response for the identical prompt is on disk.
* ``offline`` — no key and no cached response. :meth:`LLMClient.structured`
  raises :class:`LLMUnavailable` unless the caller passed an explicit fallback,
  and any fallback result is tagged ``source="rules"``.

The cache is keyed on a content hash of (model, temperature, schema, prompt), so
re-runs during development are free (PLAN §3.8).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

from ..config import Settings, get_settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """No API key, and no recorded response for this prompt."""


@dataclass
class LLMResult:
    value: Any
    source: str          # "live" | "cached" | "rules"
    model: str
    prompt_hash: str

    @property
    def confidence_multiplier(self) -> float:
        """Rule-derived output is not the same thing as model output, and the
        difference has to survive into the evidence confidence."""
        return {"live": 1.0, "cached": 1.0, "rules": 0.6}.get(self.source, 0.6)


class LLMClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.cache_dir = Path(self.settings.cache_dir) / "llm"
        self._chat = None

    # --------------------------------------------------------------- plumbing
    @property
    def available(self) -> bool:
        return self.settings.llm_available

    def _client(self):
        if self._chat is None:
            from langchain_openai import ChatOpenAI

            self._chat = ChatOpenAI(
                model=self.settings.llm_model,
                base_url=self.settings.llm_base_url,
                api_key=self.settings.openrouter_api_key,
                temperature=self.settings.llm_temperature,
                max_retries=self.settings.llm_max_retries,
            )
        return self._chat

    def prompt_hash(self, system: str, user: str, schema_name: str) -> str:
        payload = "|".join([
            self.settings.llm_model, str(self.settings.llm_temperature),
            schema_name, system, user,
        ])
        return hashlib.sha256(payload.encode()).hexdigest()[:24]

    def _cache_path(self, prompt_hash: str) -> Path:
        return self.cache_dir / f"{prompt_hash}.json"

    def read_cache(self, prompt_hash: str) -> dict | None:
        path = self._cache_path(prompt_hash)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.warning("corrupt LLM cache entry %s", path)
        return None

    def write_cache(self, prompt_hash: str, payload: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(prompt_hash).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------- the call
    def structured(
        self,
        system: str,
        user: str,
        schema: type[T],
        *,
        fallback: Callable[[], T] | None = None,
        use_cache: bool | None = None,
    ) -> LLMResult:
        """One structured-output call, cached, with an explicit offline path."""
        use_cache = self.settings.llm_cache if use_cache is None else use_cache
        h = self.prompt_hash(system, user, schema.__name__)

        if use_cache:
            cached = self.read_cache(h)
            if cached is not None:
                return LLMResult(schema.model_validate(cached), "cached",
                                 self.settings.llm_model, h)

        if self.available:
            structured = self._client().with_structured_output(schema)
            value: T = structured.invoke(
                [{"role": "system", "content": system},
                 {"role": "user", "content": user}]
            )
            if use_cache:
                self.write_cache(h, value.model_dump())
            return LLMResult(value, "live", self.settings.llm_model, h)

        if fallback is not None:
            return LLMResult(fallback(), "rules", "rules", h)

        raise LLMUnavailable(
            "OPENROUTER_API_KEY is not set and no recorded response exists for this "
            "prompt (PLAN Q14). Pass an explicit fallback to run offline."
        )


def get_client(settings: Settings | None = None) -> LLMClient:
    return LLMClient(settings)

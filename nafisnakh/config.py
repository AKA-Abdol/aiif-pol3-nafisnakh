"""Central settings — every tunable in the system lives here (PLAN §7).

Nothing below this module hard-codes a threshold, a path or a model name.
Values are overridable by environment variable with the ``NN_`` prefix or by a
``.env`` file; see ``.env.example``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class LLMProfile(BaseModel):
    """One named generation backend.

    Every profile routes through **OpenRouter** — the standing instruction is
    that any LLM call in this system goes there, so a profile varies the model
    and the provider pin, never the gateway. ``provider_only`` is OpenRouter's
    provider-routing pin: a comma-separated list of endpoint tags the request is
    allowed to land on (`GET /models/{id}/endpoints` lists the valid tags).
    """

    name: str
    model: str
    base_url: str = "https://openrouter.ai/api/v1"
    api_key_env: str = "OPENROUTER_API_KEY"
    provider_only: str = ""
    note: str = ""


# The default and, since the OpenRouter-only ruling, the only profile.
# Gemini 3.7 Flash pinned to Vertex `global`; verified against
# `/models/google/gemini-3.7-flash/endpoints`, which offers google-vertex/global
# (plus /flex and /priority) and google-ai-studio. Pinning keeps a run from
# silently landing on a different serving stack mid-book.
PROFILE_GEMINI = LLMProfile(
    name="gemini",
    model="google/gemini-3.7-flash",
    provider_only="google-vertex/global",
    note="OpenRouter → google-vertex/global — تنها مسیر مجاز فراخوانی مدل",
)

# The AgentRouter and AvalAI profiles were removed here: every call goes through
# OpenRouter now. Both were dead anyway — AgentRouter gates non-whitelisted API
# clients (PLAN §8 Q17) and the AvalAI key was quota-blocked (Q18). Restoring one
# means adding an LLMProfile with its own base_url and api_key_env; nothing else
# in the package hard-codes a gateway.
LLM_PROFILES: dict[str, LLMProfile] = {p.name: p for p in (PROFILE_GEMINI,)}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NN_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---------------------------------------------------------------- paths
    dataset_path: Path = ROOT / "DATASET.xlsx"
    metadata_path: Path = ROOT / "METADATA.xlsx"
    out_dir: Path = ROOT / "outputs"
    cache_dir: Path = ROOT / "cache"

    # ------------------------------------------------------------- windowing
    as_of: date = date(2021, 6, 30)          # PLAN §1.6 — the demo anchor
    date_from: date = date(2019, 12, 1)
    date_to: date = date(2026, 12, 31)
    currency_scale: float = 1e6
    currency_label: str = "M"

    # ------------------------------------------------------------- economics
    cost_basis: Literal["realized_then_estimated", "realized_only"] = (
        "realized_then_estimated"
    )
    late_charge_monthly: float = 0.04        # Q10 — confirmed, actually collected
    # Q11 / Q12 remain unanswered; the defaults below are ASSUMPTIONS and every
    # Evidence derived from them says so in its provenance.
    wacc_monthly: float | None = 0.025
    wacc_is_assumption: bool = True
    bad_debt_rate: float | None = 0.006      # ≈ observed bounce rate, §5.5
    bad_debt_is_assumption: bool = True
    # ⚠️ The currency unit is never declared in the metadata (PLAN §5.4) — the
    # median invoice in this file is ~72,800 units, so any absolute rial figure
    # for cost-to-serve would be off by orders of magnitude. Until Q12 gives a
    # real rate card, cost-to-serve is expressed as a **multiple of the median
    # invoice value**, which is scale-free and cannot silently swamp revenue.
    cost_to_serve_complaint_invoices: float = 0.5
    cost_to_serve_return_invoices: float = 0.1
    cost_to_serve_dev_request_invoices: float = 0.3
    cost_to_serve_is_assumption: bool = True

    # ------------------------------------------- detector thresholds (§3.4)
    cadence_breach_ratio: float = 2.0
    cadence_min_invoices: int = 6
    volume_decline_pct: float = -0.30
    volume_surge_pct: float = 0.30
    price_erosion_pct: float = -0.05
    sku_narrowing_pct: float = -0.33
    dso_slippage_days: float = 15.0
    credit_exposure_ratio: float = 0.80
    # Sanity guard on Credit_Limit before it is allowed to gate an action.
    # A limit worth more than this many months of the customer's own purchasing
    # cannot function as a constraint, so "credit is open" would be a vacuous
    # claim. It also catches the scale defect in PLAN §5.4: Universe B limits are
    # ~18,000× Universe A's while their trade differs by only 54×, which would
    # otherwise read as unlimited room for all 20 of them.
    # Book distribution at the demo anchor: median 2.3, p95 11.8, p99 50.0.
    credit_room_max_months: float = 60.0
    margin_peer_percentile: float = 20.0
    complaint_recurrence_days: int = 180
    dev_request_stall_days: int = 90
    late_interest_drag_pct: float = 0.25
    unresolved_aging_days: int = 24          # median resolution days, §5.5
    # Age-based detectors fire above whichever is larger: the fixed floor above
    # and this percentile of the *currently open* population. At a mid-extract
    # as_of, later resolutions are not yet visible, so almost every open item is
    # older than the book median — a fixed floor alone would flag 94% of them.
    aging_percentile: float = 70.0
    # A percentile of three observations is not a threshold, it is the largest
    # of the three — which makes a percentile-based detector unable to fire on
    # small books or on the golden fixture. Below this count the fixed floor is
    # used instead.
    min_percentile_observations: int = 5
    return_rate_percentile: float = 90.0
    return_rate_floor: float = 0.02          # used when the book is too small to rank
    first_repeat_gap_multiple: float = 2.0
    wallet_headroom_share_max: float = 0.35
    wallet_headroom_margin_min: float = 0.05
    mix_downgrade_steps: float = 0.5
    # customers are strongly specialised by product family in this book, so a
    # "most of your peers buy this" rule finds nothing; a quarter of them is the
    # level at which the gap is worth a conversation.
    cross_sell_peer_adoption: float = 0.25
    cross_sell_min_peers: int = 8
    discount_return_window_months: int = 6
    discount_min_offers: int = 4             # median price offers per customer is 1

    # window lengths used by the metric layer (months)
    recent_window_months: int = 3
    baseline_window_months: int = 6
    long_window_months: int = 12

    # ------------------------------------------------------------------- LLM
    # `llm_profile` selects a backend from LLM_PROFILES. The fields below remain
    # the gemini defaults so nothing that reads them changes behaviour.
    llm_profile: str = "gemini"
    llm_provider: Literal["openrouter"] = "openrouter"
    llm_model: str = "google/gemini-3.7-flash"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    # OpenRouter provider routing. Comma-separated endpoint tags, most preferred
    # first; empty means "let OpenRouter choose". Kept as a string rather than a
    # list because pydantic-settings JSON-decodes list-typed env vars, which
    # would make `NN_LLM_PROVIDER_ONLY=google-vertex/global` a parse error.
    llm_provider_only: str = "google-vertex/global"
    llm_temperature: float = 0.0
    llm_cache: bool = True
    llm_max_retries: int = 2
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")

    # ------------------------------------------------------------ embeddings
    # `NN_EMBED_BACKEND` picks where vectors come from. Both defaults are the
    # *same* model — bge-m3, 1024-dim — so switching backends does not move the
    # geometry and the PLAN §1.9 Persian benchmark still describes it. `ollama`
    # is free and offline but needs a running daemon; `openrouter` needs only
    # the key that generation already uses.
    embed_backend: Literal["ollama", "openrouter"] = "openrouter"
    embed_model: str = "bge-m3:567m"                    # ollama tag
    openrouter_embed_model: str = "baai/bge-m3"         # openrouter model id
    embed_base_url: str = "https://openrouter.ai/api/v1"
    ollama_host: str = "http://localhost:11434"

    # ---------------------------------------------------------------- output
    plot_lang: Literal["fa", "en"] = "fa"
    top_n_actions: int = 25
    random_state: int = 42

    # feedback loop (Phase 2) — see nafisnakh/feedback.py for why these are shy
    feedback_min_events: int = 10        # below this a detector keeps weight 1.0
    feedback_prior_strength: float = 10.0  # shrink toward neutral by this many pseudo-events
    feedback_weight_range: float = 0.35  # weights stay inside [0.65, 1.35]

    # calibration guard-rails (§4 Phase 1b)
    calib_max_fire_rate: float = 0.60
    calib_min_fire_rate: float = 0.02
    # A fire rate over a handful of eligible customers is not a rate. Below this
    # count the verdict is `insufficient` — reported, but never counted as a
    # failure, because "1 fired of 1 eligible = 100%, too_broad" says nothing
    # about the threshold. Same reasoning as `min_percentile_observations`.
    # 30 is the usual floor for a proportion estimate; on the full book the
    # smallest eligible population is 51, so this changes no verdict there and
    # only silences sample runs and the 16-customer fixture.
    calib_min_eligible: int = 30

    @field_validator("as_of", "date_from", "date_to", mode="before")
    @classmethod
    def _parse_date(cls, v):
        if isinstance(v, str):
            return date.fromisoformat(v.strip())
        return v

    # ------------------------------------------------------- profile resolution
    @property
    def profile(self) -> LLMProfile:
        if self.llm_profile not in LLM_PROFILES:
            raise ValueError(
                f"unknown llm_profile {self.llm_profile!r}; "
                f"available: {sorted(LLM_PROFILES)}"
            )
        return LLM_PROFILES[self.llm_profile]

    @property
    def active_model(self) -> str:
        """Explicit `NN_LLM_MODEL` wins; otherwise the profile decides.

        The gemini profile's model *is* the field default, so overriding the
        field for gemini is a no-op and the documented behaviour is preserved.
        """
        if self.llm_profile == "gemini":
            return self.llm_model
        return self.profile.model

    @property
    def active_base_url(self) -> str:
        if self.llm_profile == "gemini":
            return self.llm_base_url
        return self.profile.base_url

    @property
    def active_provider_only(self) -> list[str]:
        """The OpenRouter endpoint tags this run is allowed to land on."""
        raw = (
            self.llm_provider_only
            if self.llm_profile == "gemini"
            else self.profile.provider_only
        )
        return [tag.strip() for tag in raw.split(",") if tag.strip()]

    @property
    def provider_routing(self) -> dict | None:
        """OpenRouter's ``provider`` request field, or None when unpinned.

        Deliberately **not** part of the prompt cache key: routing decides which
        datacentre serves a model, not which model answers, so a pinned and an
        unpinned run may share a cached response.
        """
        only = self.active_provider_only
        return {"only": only} if only else None

    @property
    def active_embed_model(self) -> str:
        return (
            self.openrouter_embed_model
            if self.embed_backend == "openrouter"
            else self.embed_model
        )

    @property
    def active_api_key(self) -> str | None:
        return {"OPENROUTER_API_KEY": self.openrouter_api_key}.get(
            self.profile.api_key_env
        )

    @property
    def llm_available(self) -> bool:
        """True only when the active profile has a key (Q14)."""
        return bool(self.active_api_key)

    def ensure_dirs(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings(**overrides) -> Settings:
    """Process-wide settings singleton; ``overrides`` forces a fresh instance."""
    global _settings
    if overrides:
        return Settings(**overrides)
    if _settings is None:
        _settings = Settings()
    return _settings

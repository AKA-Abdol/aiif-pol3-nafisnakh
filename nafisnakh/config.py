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

    Profiles exist so a second model can be added without disturbing the first.
    Q3 chose Gemini Flash over OpenRouter and PLAN §7 documents it; that decision
    stands and the ``gemini`` profile below reproduces it exactly. Anything else
    is an *additional* profile, selected with ``NN_LLM_PROFILE`` or ``--profile``.
    """

    name: str
    model: str
    base_url: str
    api_key_env: str
    note: str = ""


# The documented default (Q3) — do not change these values; add a profile instead.
PROFILE_GEMINI = LLMProfile(
    name="gemini",
    model="google/gemini-2.0-flash-001",
    base_url="https://openrouter.ai/api/v1",
    api_key_env="OPENROUTER_API_KEY",
    note="انتخاب مستندشده در Q3 — ارزان و کافی برای تست اولیه",
)

# Added on request. AgentRouter restricts its API to whitelisted coding-agent
# clients and answers generic callers with `unauthorized_client_error`; a token
# alone is not enough until they authorise the client.
PROFILE_AGENTROUTER = LLMProfile(
    name="agentrouter",
    model="gpt-5.6-sol",
    base_url="https://agentrouter.org/v1",
    api_key_env="AGENTROUTER_API_KEY",
    note="نیازمند مجوز کلاینت از سمت AgentRouter",
)

# Second AgentRouter profile (key "mehdi-claude"). Same gateway, different model.
PROFILE_AGENTROUTER_CLAUDE = LLMProfile(
    name="agentrouter-claude",
    model="claude-opus-4-8",
    base_url="https://agentrouter.org/v1",
    api_key_env="AGENTROUTER_CLAUDE_API_KEY",
    note="⚠ متن فارسی را با content-blocked رد می‌کند — برای این پروژه غیرقابل استفاده",
)


PROFILE_AVALAI = LLMProfile(
    name="avalai",
    model="gpt-5.5",
    base_url="https://api.avalai.ir/v1",
    api_key_env="AVALAI_API_KEY",
    note="کلید فقط به gpt-5.5 دسترسی دارد و اعتبار حساب کافی نیست — §8 Q18",
)

LLM_PROFILES: dict[str, LLMProfile] = {
    p.name: p
    for p in (PROFILE_GEMINI, PROFILE_AGENTROUTER, PROFILE_AGENTROUTER_CLAUDE,
              PROFILE_AVALAI)
}


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
    llm_model: str = "google/gemini-2.0-flash-001"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_temperature: float = 0.0
    llm_cache: bool = True
    llm_max_retries: int = 2
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    agentrouter_api_key: str | None = Field(default=None, alias="AGENTROUTER_API_KEY")
    agentrouter_claude_api_key: str | None = Field(
        default=None, alias="AGENTROUTER_CLAUDE_API_KEY"
    )
    avalai_api_key: str | None = Field(default=None, alias="AVALAI_API_KEY")

    # ------------------------------------------------------------ embeddings
    embed_backend: Literal["ollama"] = "ollama"
    embed_model: str = "bge-m3:567m"
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
    def active_api_key(self) -> str | None:
        return {
            "OPENROUTER_API_KEY": self.openrouter_api_key,
            "AGENTROUTER_API_KEY": self.agentrouter_api_key,
            "AGENTROUTER_CLAUDE_API_KEY": self.agentrouter_claude_api_key,
            "AVALAI_API_KEY": self.avalai_api_key,
        }.get(self.profile.api_key_env)

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

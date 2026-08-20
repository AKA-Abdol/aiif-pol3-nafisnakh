"""Dataset and metadata loading, with a parquet cache.

Reading the 16-sheet workbook takes ~40 s; every module below this one wants
the same frames, so the first read writes parquet into ``cache_dir`` keyed by
the workbook's mtime+size and later runs load in well under a second.

Loading is where normalisation happens, once: dates coerced (Jalali included,
PLAN §1.5), customer ids canonicalised and tagged with their universe,
``*_Pct`` fraction columns scaled (PLAN §5.4).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import pandas as pd

from ..config import Settings, get_settings
from . import schema as S
from .normalize import (
    add_universe_column,
    normalize_customer_id,
    fix_fraction_pct,
    normalize_fa,
    to_datetime_mixed,
)

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ metadata
@dataclass
class Contract:
    """The METADATA.xlsx contract: grains, PKs, column definitions, the 26
    relationships, the 7 integration rules, the 8 DQ caveats."""

    sheets: pd.DataFrame
    columns: pd.DataFrame
    relationships: pd.DataFrame
    integration_rules: pd.DataFrame
    dq_notes: pd.DataFrame
    domains: pd.DataFrame

    def primary_key(self, sheet: str) -> str | None:
        row = self.sheets.loc[self.sheets["Sheet_Name"] == sheet]
        return None if row.empty else row.iloc[0]["Primary_Key"]

    def declared_columns(self, sheet: str) -> list[str]:
        return self.columns.loc[
            self.columns["Sheet_Name"] == sheet, "Column_Name"
        ].tolist()

    def allowed_values(self, sheet: str, column: str) -> list[str]:
        row = self.columns[
            (self.columns["Sheet_Name"] == sheet)
            & (self.columns["Column_Name"] == column)
        ]
        if row.empty or pd.isna(row.iloc[0]["Allowed_Values_or_Rule"]):
            return []
        return [v.strip() for v in str(row.iloc[0]["Allowed_Values_or_Rule"]).split("|")]


def load_contract(path: Path | None = None, settings: Settings | None = None) -> Contract:
    st = settings or get_settings()
    xl = pd.ExcelFile(path or st.metadata_path)
    name = {n.replace("‌", ""): n for n in xl.sheet_names}
    return Contract(
        sheets=xl.parse(name["متادیتای_شیتها"]),
        columns=xl.parse(name["متادیتای_ستونها"]),
        relationships=xl.parse(name["روابط"]),
        integration_rules=xl.parse(name["راهنمای_یکپارچهسازی"]),
        dq_notes=xl.parse(name["نکات_کیفیت_داده"]),
        domains=xl.parse(name["دامنه_مقادیر"]),
    )


# ------------------------------------------------------------------- dataset
def _cache_key(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha1(
        f"{path.resolve()}|{stat.st_size}|{int(stat.st_mtime)}|v3".encode()
    ).hexdigest()[:16]


def _normalize_sheet(sheet: str, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    for col in S.DATE_COLUMNS.get(sheet, []):
        if col in df.columns:                      # resolve dynamically (§5.4)
            df[col] = to_datetime_mixed(df[col])

    if S.CUSTOMER_ID in df.columns:
        df = add_universe_column(df, S.CUSTOMER_ID)

    if sheet == S.S_LOT_QUALITY:
        df = fix_fraction_pct(df, S.FRACTION_PCT_COLUMNS)

    if sheet == S.S_COMPLAINTS:
        df["_title_norm"] = df[S.K_TITLE].map(normalize_fa)
        df["_text_norm"] = df[S.K_TEXT].map(normalize_fa)
        df["_resolution_norm"] = df[S.K_RESOLUTION_TEXT].map(normalize_fa)

    for col in (S.MONTH_KEY,):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df


@dataclass
class Dataset:
    """All 16 sheets, normalised. Access by attribute or by ``ds[sheet_name]``."""

    frames: dict[str, pd.DataFrame]
    settings: Settings
    contract: Contract | None = field(default=None, repr=False)

    def __getitem__(self, sheet: str) -> pd.DataFrame:
        return self.frames[sheet]

    def __contains__(self, sheet: str) -> bool:
        return sheet in self.frames

    # convenience accessors — named so call sites never carry a Persian literal
    customers = property(lambda self: self.frames[S.S_CUSTOMERS])
    products = property(lambda self: self.frames[S.S_PRODUCTS])
    invoices = property(lambda self: self.frames[S.S_INVOICES])
    sales = property(lambda self: self.frames[S.S_SALES])
    cost_realized = property(lambda self: self.frames[S.S_COST_REAL])
    cost_planned = property(lambda self: self.frames[S.S_COST_PLAN])
    collections = property(lambda self: self.frames[S.S_COLLECTIONS])
    complaints = property(lambda self: self.frames[S.S_COMPLAINTS])
    complaint_link = property(lambda self: self.frames[S.S_COMPLAINT_LINK])
    crm = property(lambda self: self.frames[S.S_CRM])
    dev_requests = property(lambda self: self.frames[S.S_DEV_REQUESTS])
    lot_quality = property(lambda self: self.frames[S.S_LOT_QUALITY])
    hembaft_lot = property(lambda self: self.frames[S.S_HEMBAFT_LOT])
    offers = property(lambda self: self.frames[S.S_OFFERS])
    wallet = property(lambda self: self.frames[S.S_WALLET])
    market = property(lambda self: self.frames[S.S_MARKET])

    @cached_property
    def crm_latest(self) -> pd.DataFrame:
        """Integration rule #5: latest visible ``Record_Version`` per interaction."""
        df = self.crm.sort_values([S.X_ID, S.X_VERSION])
        return df.groupby(S.X_ID, as_index=False).tail(1)

    def row_counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.frames.items()}


def subset_dataset(
    ds: Dataset, customer_ids: list[str] | None = None, *, sample: int = 0,
    seed: int | None = None, prefer_active: bool = True,
) -> Dataset:
    """A smaller Dataset containing only the named customers.

    For trying the pipeline on a handful of real accounts without waiting for
    the full book. Every customer-bearing sheet is filtered on ``Customer_ID``;
    sheets without one (products, planned cost, the همبافت bridge) are kept
    whole, because they are dimensions and filtering them would break joins.

    ⚠️ **Peer-comparison detectors weaken on a small sample.** `margin_below_peer_cohort`
    needs 5 customers in a cohort and `cross_sell_peer_gap` needs 8, so below
    roughly 30 customers those two go quiet. That is correct behaviour — a
    percentile over four customers is not a percentile — but it means a small
    sample tests the plumbing, not the calibration. Use the full book for that.
    """
    frames = dict(ds.frames)
    customers = frames[S.S_CUSTOMERS]

    if customer_ids:
        wanted = {normalize_customer_id(c) for c in customer_ids}
        missing = wanted - set(customers[S.CUSTOMER_ID])
        if missing:
            raise KeyError(f"unknown customer ids: {sorted(missing)}")
    else:
        pool = customers
        if prefer_active:
            # customers with real trading history make a far more useful sample
            # than the dormant tail, which triggers almost nothing
            counts = frames[S.S_SALES][S.CUSTOMER_ID].value_counts()
            busy = counts[counts >= 20].index
            if len(busy) >= sample:
                pool = customers.loc[customers[S.CUSTOMER_ID].isin(busy)]
        wanted = set(
            pool[S.CUSTOMER_ID].sample(
                min(sample, len(pool)), random_state=seed or ds.settings.random_state
            )
        )

    for sheet, frame in frames.items():
        if S.CUSTOMER_ID in frame.columns and len(frame):
            frames[sheet] = frame.loc[frame[S.CUSTOMER_ID].isin(wanted)].copy()

    # keep the invoice/cost/collection tables consistent with the kept sales lines
    kept_invoices = set(frames[S.S_SALES][S.INVOICE_NO])
    kept_lines = set(frames[S.S_SALES][S.SALES_LINE_ID])
    for sheet, key, keep in (
        (S.S_COST_REAL, S.SALES_LINE_ID, kept_lines),
        (S.S_COLLECTIONS, S.INVOICE_NO, kept_invoices),
    ):
        frame = frames[sheet]
        if key in frame.columns and len(frame):
            frames[sheet] = frame.loc[frame[key].isin(keep)].copy()

    log.info("subset to %d customers, %d sales lines",
             len(wanted), len(frames[S.S_SALES]))
    return Dataset(frames=frames, settings=ds.settings, contract=ds.contract)


def load_dataset(
    settings: Settings | None = None, *, use_cache: bool = True, refresh: bool = False
) -> Dataset:
    st = settings or get_settings()
    st.ensure_dirs()
    key = _cache_key(Path(st.dataset_path))
    cache_dir = Path(st.cache_dir) / f"dataset-{key}"

    frames: dict[str, pd.DataFrame] = {}
    if use_cache and not refresh and cache_dir.is_dir():
        try:
            for i, sheet in enumerate(S.ALL_SHEETS):
                frames[sheet] = pd.read_parquet(cache_dir / f"{i:02d}.parquet")
            log.info("dataset loaded from cache %s", cache_dir)
            return Dataset(frames=frames, settings=st)
        except Exception as exc:                    # corrupt/partial cache
            log.warning("cache miss (%s); re-reading workbook", exc)
            frames = {}

    raw = pd.read_excel(st.dataset_path, sheet_name=None)
    for sheet in S.ALL_SHEETS:
        if sheet not in raw:
            raise KeyError(f"sheet {sheet!r} missing from {st.dataset_path}")
        frames[sheet] = _normalize_sheet(sheet, raw[sheet])

    if use_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        for i, sheet in enumerate(S.ALL_SHEETS):
            frames[sheet].to_parquet(cache_dir / f"{i:02d}.parquet", index=False)

    return Dataset(frames=frames, settings=st)

"""Text, date and identifier normalisation.

Three jobs:

1. ``normalize_fa`` — canonicalise Persian text (ported from ``main.ipynb`` §2).
   Collapsed 11.5% of the raw complaint vocabulary as pure orthographic noise;
   every LLM/embedding call must go through it first.
2. Jalali → Gregorian (PLAN §1.5). The 20 ``CUST-*`` rows carry
   ``Relationship_Start_Date`` as ``1395/08/12`` while the other 624 are ISO.
   Left alone, tenure and LTV go NaN for exactly the 20 real customers.
3. The dual customer-ID namespace: ``C_*`` (MDM, universe A) and ``CUST-***``
   (CRM_MASTER, universe B) never overlap, so the universe is derivable from
   the id itself.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any, Literal

import numpy as np
import pandas as pd

# --------------------------------------------------------------- Persian text
_CHAR_MAP = {
    "ي": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "ٱ": "ا",
    "ؤ": "و", "ئ": "ی", "ى": "ی", "ﻻ": "لا", "�": " ",
}
_DIGITS = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_DIGITS.update({ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")})
_DIACRITICS = re.compile(r"[ً-ْٰـ]")
_PUNCT = re.compile(r"[^\w\s؀-ۿ]+")
_WS = re.compile(r"\s+")
_ZW = ("‌", "‏", "‎")


def normalize_fa(s: Any) -> str:
    """Canonicalise Persian text: orthography, digits, ZWNJ, punctuation, space."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKC", s)
    for a, b in _CHAR_MAP.items():
        s = s.replace(a, b)
    s = s.translate(_DIGITS)
    s = _DIACRITICS.sub("", s)
    for z in _ZW:
        s = s.replace(z, " ")
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def normalize_fa_keep_punct(s: Any) -> str:
    """Like :func:`normalize_fa` but keeps punctuation — for LLM prompts, where
    sentence boundaries and quotation marks carry meaning."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKC", s)
    for a, b in _CHAR_MAP.items():
        s = s.replace(a, b)
    s = s.translate(_DIGITS)
    s = _DIACRITICS.sub("", s)
    s = s.replace("‌", " ")
    return _WS.sub(" ", s).strip()


# ---------------------------------------------------------- Jalali → Gregorian
def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """Convert a Jalali (Solar Hijri) date to Gregorian.

    Standard day-count algorithm; exact across the 1394–1404 range present in
    the data and well beyond it.
    """
    jy += 1595
    days = -355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd
    days += (jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    month_len = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > month_len[gm]:
        gd -= month_len[gm]
        gm += 1
    return gy, gm, gd


# A 4-digit year in 1300–1499 cannot be a Gregorian date in this dataset, so the
# year alone identifies the calendar.
_JALALI_RE = re.compile(r"^\s*(1[34]\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})\s*$")
_ISO_RE = re.compile(r"^\s*(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})")


def parse_date_any(value: Any):
    """Parse a date that may be ISO Gregorian, Jalali, or already a datetime."""
    if value is None:
        return pd.NaT
    if isinstance(value, float) and np.isnan(value):
        return pd.NaT
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value)
    s = str(value).strip()
    if not s or s.lower() in {"nan", "nat", "none"}:
        return pd.NaT
    s = s.translate(_DIGITS)
    m = _JALALI_RE.match(s)
    if m:
        gy, gm, gd = jalali_to_gregorian(int(m[1]), int(m[2]), int(m[3]))
        return pd.Timestamp(gy, gm, gd)
    m = _ISO_RE.match(s)
    if m:
        try:
            return pd.Timestamp(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return pd.NaT
    return pd.to_datetime(s, errors="coerce")


def to_datetime_mixed(series: pd.Series) -> pd.Series:
    """Vectorised :func:`parse_date_any`. Fast path when no Jalali value is present."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    as_str = series.astype("string")
    has_jalali = as_str.str.match(_JALALI_RE.pattern, na=False).any()
    if not has_jalali:
        return pd.to_datetime(series, errors="coerce", format="mixed")
    return pd.Series(
        [parse_date_any(v) for v in series], index=series.index, dtype="datetime64[ns]"
    )


# ------------------------------------------------------ customer-ID namespace
Universe = Literal["A", "B", "unknown"]

_MDM_RE = re.compile(r"^C_\d+$")
_CRM_RE = re.compile(r"^CUST-\d+$", re.IGNORECASE)


def customer_universe(customer_id: Any) -> str:
    """Which of the two disjoint universes an id belongs to (PLAN §1.1).

    A = ``C_*`` (MDM, 2019-12…2022-06, rich commercial history, 624 customers)
    B = ``CUST-***`` (CRM_MASTER, 2025-03…2026-08, real complaint prose, 20)
    No customer appears in both.
    """
    s = str(customer_id).strip()
    if _MDM_RE.match(s):
        return "A"
    if _CRM_RE.match(s):
        return "B"
    return "unknown"


def normalize_customer_id(customer_id: Any) -> str:
    """Canonical id: trim, upper-case the ``CUST-`` prefix, zero-pad to 3 digits."""
    s = str(customer_id).strip()
    if _CRM_RE.match(s):
        return f"CUST-{int(s.split('-', 1)[1]):03d}"
    return s


def add_universe_column(df: pd.DataFrame, col: str = "Customer_ID") -> pd.DataFrame:
    """Attach a ``_universe`` column derived from the id namespace."""
    if col not in df.columns:
        return df
    out = df.copy()
    out[col] = out[col].map(normalize_customer_id)
    out["_universe"] = out[col].map(customer_universe)
    return out


# ------------------------------------------------------------------ numerics
def fix_fraction_pct(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Columns named ``*_Pct`` that actually hold fractions (PLAN §5.4) are scaled
    by 100 so that ``_Pct`` means percent everywhere downstream."""
    out = df.copy()
    for c in columns:
        if c not in out.columns:
            continue
        v = pd.to_numeric(out[c], errors="coerce")
        vmax = v.abs().max()
        out[c] = v * 100.0 if pd.notna(vmax) and vmax <= 1.5 else v
    return out


def month_floor(series: pd.Series) -> pd.Series:
    """First day of the month as datetime64 — join key for every monthly grain."""
    return pd.to_datetime(series, errors="coerce").dt.to_period("M").dt.to_timestamp()

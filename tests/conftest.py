"""Shared fixtures. The dataset is loaded once per session (parquet-cached)."""

from __future__ import annotations

from datetime import date

import pytest

from nafisnakh.config import get_settings
from nafisnakh.core.cohort import build_cohorts
from nafisnakh.core.spine import build_spine
from nafisnakh.io.loader import load_contract, load_dataset

FULL_AS_OF = date(2026, 12, 31)   # everything visible — for count regressions
DEMO_AS_OF = date(2021, 6, 30)    # PLAN §1.6 anchor


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def ds(settings):
    return load_dataset(settings)


@pytest.fixture(scope="session")
def contract(settings):
    return load_contract(settings=settings)


@pytest.fixture(scope="session")
def full_spine(ds):
    return build_spine(ds, as_of=FULL_AS_OF)


@pytest.fixture(scope="session")
def spine(ds):
    return build_spine(ds, as_of=DEMO_AS_OF)


@pytest.fixture(scope="session")
def cohorts(spine, ds):
    return build_cohorts(spine, ds.customers)

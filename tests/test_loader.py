import pandas as pd

from nafisnakh.io import schema as S


def test_all_sheets_present_with_expected_row_counts(ds):
    assert set(ds.frames) == set(S.ALL_SHEETS)
    assert ds.row_counts() == S.EXPECTED_ROWS


def test_jalali_start_dates_are_normalised(ds):
    c = ds.customers
    assert pd.api.types.is_datetime64_any_dtype(c[S.C_START_DATE])
    crm = c.loc[c[S.SOURCE_SYSTEM] == "CRM_MASTER"]
    assert len(crm) == 20
    # the defect in PLAN §1.5: these 20 silently went NaN before the fix
    assert crm[S.C_START_DATE].notna().all()
    assert crm[S.C_START_DATE].dt.year.between(2015, 2025).all()


def test_universes_are_disjoint(ds):
    c = ds.customers
    assert set(c["_universe"]) == {"A", "B"}
    assert (c["_universe"] == "A").sum() == 624
    assert (c["_universe"] == "B").sum() == 20
    sales_customers = set(ds.sales[S.CUSTOMER_ID])
    complaint_customers = set(ds.complaints[S.CUSTOMER_ID])
    universe_b = set(c.loc[c["_universe"] == "B", S.CUSTOMER_ID])
    # universe B has both sales and complaints, but no id spans both universes
    assert not {i for i in sales_customers if i.startswith("C_")} & universe_b
    assert complaint_customers  # sanity


def test_cache_round_trip_is_identical(ds, settings):
    from nafisnakh.io.loader import load_dataset

    again = load_dataset(settings)
    for sheet in S.ALL_SHEETS:
        pd.testing.assert_frame_equal(ds[sheet], again[sheet])


def test_fraction_pct_columns_are_scaled(ds):
    """PLAN §5.4 — the three ``*_Pct`` columns arrive as fractions. Scaled, they
    must land in their physically plausible percent ranges for POY yarn."""
    q = ds.lot_quality
    ranges = {
        S.Q_ELONGATION: (15.0, 40.0),    # POY elongation ≈ 18–35%
        S.Q_EVENNESS: (0.5, 3.0),        # Uster CV%
        S.Q_OIL: (0.2, 2.0),             # spin-finish pickup
    }
    for col, (lo, hi) in ranges.items():
        v = q[col].dropna()
        assert lo <= v.min() and v.max() <= hi, f"{col} out of range: {v.min()}–{v.max()}"
    # tensile is correctly named and must NOT have been rescaled
    assert q[S.Q_TENSILE].max() < 10


def test_contract_exposes_the_seven_integration_rules(contract):
    assert len(contract.integration_rules) == 7
    assert len(contract.relationships) == 26
    assert contract.primary_key(S.S_SALES) == S.SALES_LINE_ID


def test_crm_latest_applies_rule_5(ds):
    latest = ds.crm_latest
    assert latest[S.X_ID].is_unique
    merged = latest.merge(
        ds.crm.groupby(S.X_ID)[S.X_VERSION].max().rename("_max"), on=S.X_ID
    )
    assert (merged[S.X_VERSION] == merged["_max"]).all()

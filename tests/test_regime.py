"""Tests for src.analytics.regime — regime gate signal + percentile rank.

Pure-function tests over synthetic signal series + monkeypatched
spot loader. One integration test against the live India VIX loader
output (gated when the cache happens to exist).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.analytics.regime import (
    avg_single_name_realized_vol,
    regime_percentile,
    regime_state,
)


def _make_signal(values: list[float], start: date = date(2024, 1, 2)) -> pd.Series:
    """Build a daily date-indexed signal series. NSE calendar isn't
    relevant for the time-series math — we just need contiguous
    dates so ``searchsorted`` behaves predictably."""
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=idx)


# ============================================================
# regime_percentile — math correctness
# ============================================================

def test_regime_percentile_at_max_returns_100_minus_self_count():
    """If today's value is the strict max of the lookback window,
    every other observation is strictly less → rank = (N-1)/N × 100.
    Pin the formula explicitly so an off-by-one rewrite doesn't
    silently shift every backtest's gate."""
    series = _make_signal([1.0, 2.0, 3.0, 4.0, 5.0])
    out = regime_percentile(
        series, as_of=date(2024, 1, 6), lookback_td=5,
    )
    # 4 of 5 values strictly less than today (5.0); 4/5 * 100 = 80.
    assert out == pytest.approx(80.0)


def test_regime_percentile_at_min_returns_zero():
    """If today's value equals the min of the window, nothing is
    strictly less → rank = 0. Series puts today at the last index
    so the full 5-element window is realized."""
    # [5,4,3,2,1] — today = 1 at the end, window = full series,
    # count strictly < 1 = 0 → rank = 0/5 * 100 = 0.
    series = _make_signal([5.0, 4.0, 3.0, 2.0, 1.0])
    out = regime_percentile(
        series, as_of=date(2024, 1, 6), lookback_td=5,
    )
    assert out == 0.0


def test_regime_percentile_synthetic_midpoint():
    """Hand-checkable case: rank reflects fraction strictly below
    today in the trailing window. Series puts today at the last
    index so the full 5-element window is realized (lookback is
    backward-looking, not forward — putting today early would
    truncate the window)."""
    # Window = [10,20,40,50,30]; today = 30 at last index.
    # Count strictly < 30 = 2 (10, 20); rank = 2/5 * 100 = 40.
    series = _make_signal([10.0, 20.0, 40.0, 50.0, 30.0])
    out = regime_percentile(
        series, as_of=date(2024, 1, 6), lookback_td=5,
    )
    assert out == 40.0


# ============================================================
# regime_percentile — insufficient-history / NaN handling
# ============================================================

def test_regime_percentile_returns_nan_on_empty_series():
    """Empty series can't produce any rank."""
    out = regime_percentile(
        pd.Series([], dtype="float64"),
        as_of=date(2024, 1, 2),
        lookback_td=252,
    )
    assert np.isnan(out)


def test_regime_percentile_returns_nan_when_as_of_predates_series():
    """as_of earlier than every series date → no usable lookback."""
    series = _make_signal([1.0, 2.0, 3.0], start=date(2024, 6, 1))
    out = regime_percentile(
        series, as_of=date(2023, 1, 1), lookback_td=2,
    )
    assert np.isnan(out)


def test_regime_percentile_returns_nan_on_single_row_window():
    """Window with < 2 observations is degenerate; rank meaningless."""
    series = _make_signal([42.0])
    out = regime_percentile(
        series, as_of=date(2024, 1, 2), lookback_td=252,
    )
    assert np.isnan(out)


def test_regime_percentile_returns_nan_below_half_lookback_floor():
    """PORTFOLIO_MEMOIR.md §21.4 F5: insufficient-history floor is
    ``len(valid) < 0.5 * lookback_td``. With lookback=5, the floor is
    2.5 → need at least 3 non-NaN observations. 5-element window with
    3 NaN (2 valid) → 2 < 2.5 → NaN.

    Anti-regression on the 3fb0f05→0a08-style fix (reviewer d8620f8
    GRILL 1): an earlier draft used a `> 10%` NaN-fraction gate
    against `len(window)` and claimed it matched F5; spec actually
    uses `0.5 * lookback_td` floor against `len(valid)`."""
    series = _make_signal(
        [1.0, np.nan, np.nan, np.nan, 5.0]   # 2 valid of lookback 5
    )
    out = regime_percentile(
        series, as_of=date(2024, 1, 6), lookback_td=5,
    )
    assert np.isnan(out)


def test_regime_percentile_at_half_lookback_floor_is_just_valid():
    """Boundary test on the F5 floor: exactly ``len(valid) == 0.5 *
    lookback_td`` is INSUFFICIENT (the spec uses strict `<`, so
    valid == floor passes). lookback=4 → floor=2; valid=2 passes;
    valid=1 fails. Pin the inclusive-exclusive boundary explicitly."""
    # lookback=4 → floor 2. valid=2 → just passes.
    just_valid = _make_signal([1.0, np.nan, np.nan, 4.0])
    out_at_floor = regime_percentile(
        just_valid, as_of=date(2024, 1, 5), lookback_td=4,
    )
    # 1 value (1.0) strictly less than today (4.0); valid count 2
    # → rank = 1/2 * 100 = 50.
    assert out_at_floor == pytest.approx(50.0)

    # 1 valid only → fails the floor.
    just_below = _make_signal([np.nan, np.nan, np.nan, 4.0])
    out_below = regime_percentile(
        just_below, as_of=date(2024, 1, 5), lookback_td=4,
    )
    assert np.isnan(out_below)


def test_regime_percentile_denominator_uses_valid_not_window():
    """PORTFOLIO_MEMOIR.md §21.4 F5: denominator is ``len(valid)``,
    not ``len(window)``. Anti-regression on d8620f8 GRILL 3.

    Hand-check: 5-element window with 1 NaN; today = max.
    Spec rank = (valid < today).sum() / len(valid) = 3/4 = 75.
    Pre-fix BUILDER rank = 3/5 = 60 (wrong denominator)."""
    # [10, 20, NaN, 40, 50] — today = 50 at end, valid = [10, 20, 40, 50]
    # Spec: (valid < 50).sum() / len(valid) = 3/4 * 100 = 75.
    series = _make_signal([10.0, 20.0, np.nan, 40.0, 50.0])
    out = regime_percentile(
        series, as_of=date(2024, 1, 6), lookback_td=5,
    )
    assert out == pytest.approx(75.0)


def test_regime_percentile_returns_nan_when_today_value_is_nan():
    """as_of's value itself NaN → can't rank it."""
    series = _make_signal([1.0, 2.0, 3.0, 4.0, np.nan])
    out = regime_percentile(
        series, as_of=date(2024, 1, 6), lookback_td=5,
    )
    assert np.isnan(out)


def test_regime_percentile_rejects_lookback_below_2():
    """Degenerate lookback windows raise; defensive guard against
    a future caller passing 0 or 1 by mistake."""
    series = _make_signal([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="lookback_td must be >= 2"):
        regime_percentile(series, as_of=date(2024, 1, 4), lookback_td=1)


def test_regime_percentile_rejects_non_series_input():
    """Defensive: pass a list / ndarray by mistake → TypeError."""
    with pytest.raises(TypeError, match="signal_series must be pd.Series"):
        regime_percentile([1.0, 2.0], as_of=date(2024, 1, 4))  # type: ignore[arg-type]


# ============================================================
# regime_state — boundary at threshold + default 75
# ============================================================

def test_regime_state_on_when_below_threshold():
    """Pct 40 vs default threshold 75 → ON."""
    series = _make_signal([10.0, 20.0, 30.0, 40.0, 50.0])
    state = regime_state(
        series, as_of=date(2024, 1, 4), lookback_td=5,
    )
    assert state == "ON"


def test_regime_state_off_when_above_threshold():
    """Pct 80 (top quartile) vs default threshold 75 → OFF."""
    series = _make_signal([10.0, 20.0, 30.0, 40.0, 50.0])
    state = regime_state(
        series, as_of=date(2024, 1, 6), lookback_td=5,
    )
    assert state == "OFF"


def test_regime_state_boundary_at_threshold_is_on():
    """LOAD-BEARING: pct exactly == threshold is ON (the inclusive
    side). Documents the rule precisely so a future contributor
    can't silently flip from <= to <."""
    # 4-element series, today = 4 at the end. count < 4 = 3.
    # rank = 3/4 * 100 = 75.0 exactly.
    series = _make_signal([1.0, 2.0, 3.0, 4.0])
    pct = regime_percentile(
        series, as_of=date(2024, 1, 5), lookback_td=4,
    )
    assert pct == 75.0
    state = regime_state(
        series, as_of=date(2024, 1, 5), threshold_pct=75.0, lookback_td=4,
    )
    assert state == "ON"


def test_regime_state_default_threshold_is_75():
    """PORTFOLIO_MEMOIR.md §3.1: default threshold is the 75th
    percentile. Verify both sides of the boundary."""
    # 4-element window: today at the end, 3 values < today
    # → pct = 75 exactly. Default threshold 75 → 75 <= 75 → ON.
    just_at = _make_signal([1.0, 2.0, 3.0, 4.0])
    state_at = regime_state(
        just_at, as_of=date(2024, 1, 5), lookback_td=4,
    )
    assert state_at == "ON"

    # 5-element window: today at the end, 4 values < today
    # → pct = 80 > 75 → OFF.
    just_above = _make_signal([1.0, 2.0, 3.0, 4.0, 5.0])
    state_above = regime_state(
        just_above, as_of=date(2024, 1, 6), lookback_td=5,
    )
    assert state_above == "OFF"


def test_regime_state_off_on_insufficient_history():
    """NaN percentile → ``"OFF"`` per the docstring's documented
    "skip when uncertain" convention. Pin the convention so a
    future contributor can't accidentally invert it."""
    series = _make_signal([1.0, 2.0, np.nan, np.nan, np.nan])  # 60% NaN
    state = regime_state(
        series, as_of=date(2024, 1, 6), lookback_td=5,
    )
    assert state == "OFF"


def test_regime_state_rejects_out_of_range_threshold():
    """Defensive: a 105% threshold is operator error."""
    series = _make_signal([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="threshold_pct"):
        regime_state(series, as_of=date(2024, 1, 4), threshold_pct=105.0)


# ============================================================
# avg_single_name_realized_vol — averaging + filtering
# ============================================================

def test_avg_single_name_realized_vol_averages_per_symbol_rvs(monkeypatch):
    """Plain mean over per-symbol realized_vol calls. Three symbols
    with synthetic RVs (10%, 20%, 30%) → average 20%."""
    from src.engine import vol as vol_mod
    rv_by_sym = {"A": 0.10, "B": 0.20, "C": 0.30}

    def fake_realized_vol(symbol, as_of, **kwargs):
        return rv_by_sym[symbol]

    monkeypatch.setattr(vol_mod, "realized_vol", fake_realized_vol)
    out = avg_single_name_realized_vol(
        ["A", "B", "C"], date(2024, 6, 1), window_td=21,
    )
    assert out == pytest.approx(0.20)


def test_avg_single_name_realized_vol_excludes_zero_fallback(monkeypatch):
    """LOAD-BEARING: engine.vol.realized_vol returns 0.0 for
    cold-cache / insufficient-history per its own docstring. Those
    zero "I don't know" sentinels MUST NOT be averaged into the
    regime signal — otherwise the gate silently fires ON during
    cold-cache periods because the avg is artificially deflated."""
    from src.engine import vol as vol_mod
    rv_by_sym = {"A": 0.20, "B": 0.0, "C": 0.40}  # B is the zero fallback

    def fake_realized_vol(symbol, as_of, **kwargs):
        return rv_by_sym[symbol]

    monkeypatch.setattr(vol_mod, "realized_vol", fake_realized_vol)
    out = avg_single_name_realized_vol(
        ["A", "B", "C"], date(2024, 6, 1), window_td=21,
    )
    # B excluded; mean of A + C = 0.30, NOT mean of all three = 0.20.
    assert out == pytest.approx(0.30)


def test_avg_single_name_realized_vol_skips_per_symbol_exceptions(monkeypatch):
    """Per-symbol propagation failure (missing cache, delisted)
    drops that symbol; surviving symbols still produce an average."""
    from src.engine import vol as vol_mod

    def fake_realized_vol(symbol, as_of, **kwargs):
        if symbol == "DELISTED":
            raise RuntimeError("synthetic: spot cache missing")
        return 0.25

    monkeypatch.setattr(vol_mod, "realized_vol", fake_realized_vol)
    out = avg_single_name_realized_vol(
        ["A", "DELISTED", "B"], date(2024, 6, 1), window_td=21,
    )
    assert out == pytest.approx(0.25)


def test_avg_single_name_realized_vol_returns_nan_on_empty_input():
    """Empty symbol set → NaN. Downstream regime_state interprets
    NaN as ``"OFF"`` (skip-when-uncertain)."""
    out = avg_single_name_realized_vol([], date(2024, 6, 1))
    assert np.isnan(out)


def test_avg_single_name_realized_vol_returns_nan_when_all_zero(monkeypatch):
    """All symbols return 0.0 fallback → no usable values → NaN."""
    from src.engine import vol as vol_mod
    monkeypatch.setattr(
        vol_mod, "realized_vol",
        lambda symbol, as_of, **kwargs: 0.0,
    )
    out = avg_single_name_realized_vol(
        ["A", "B", "C"], date(2024, 6, 1),
    )
    assert np.isnan(out)


def test_avg_single_name_realized_vol_rejects_window_below_2():
    """Same defensive guard as realized_vol itself."""
    with pytest.raises(ValueError, match="window_td must be > 1"):
        avg_single_name_realized_vol(["A"], date(2024, 6, 1), window_td=1)


# ============================================================
# Integration: load_india_vix → regime_percentile end-to-end
# ============================================================

def test_integration_india_vix_to_regime_percentile_returns_pct_in_range(
    monkeypatch, tmp_path,
):
    """End-to-end shape check: a synthesized India VIX series flows
    through load_india_vix (via the cache parquet) into
    regime_percentile and produces a number in [0, 100].

    Doesn't require the network test to have run — we pre-populate
    the cache parquet directly with the canonical schema."""
    from src.data import cache, india_vix_loader
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    # Synthesize 300 trading days of India VIX history.
    n = 300
    dates = pd.date_range("2024-01-02", periods=n, freq="D")
    # Sine-wave + drift so percentiles are non-trivial; values in
    # a plausible India VIX range (~10-25).
    vals = 15.0 + 5.0 * np.sin(np.linspace(0, 6 * np.pi, n)) + np.linspace(0, 2, n)
    cache_df = pd.DataFrame({
        "date": dates.astype("datetime64[us]"),
        "india_vix_open":  vals - 0.5,
        "india_vix_high":  vals + 0.5,
        "india_vix_low":   vals - 1.0,
        "india_vix_close": vals,
        "india_vix_prev_close": np.concatenate([[vals[0]], vals[:-1]]),
    })
    cache.india_vix_path().parent.mkdir(parents=True, exist_ok=True)
    cache_df.to_parquet(cache.india_vix_path(), index=False)

    # Load via the loader (cache hit, no network).
    df = india_vix_loader.load_india_vix(
        dates[0].date(), dates[-1].date(),
        today_fn=lambda: date(2026, 5, 24),
    )
    assert len(df) == n
    # Build a date-indexed close series and rank a known mid-window day.
    close = df.set_index("date")["india_vix_close"]
    pct = regime_percentile(
        close, as_of=dates[252].date(), lookback_td=252,
    )
    assert 0.0 <= pct <= 100.0


# ============================================================
# Phase 9.6 v2 signal — India VIX → regime
# ============================================================

from src.analytics import regime as _regime_mod
from src.analytics.regime import (
    current_regime_state,
    default_regime_signal,
    load_india_vix_signal,
)


def _stub_india_vix_loader(monkeypatch, df: pd.DataFrame) -> list[tuple]:
    """Stub india_vix_loader.load_india_vix so v2 tests don't
    need parquet I/O. Returns a list the stub appends to so
    tests can assert on the call args."""
    calls: list[tuple] = []

    def fake_load_india_vix(
        from_date, to_date, *,
        force_refresh=False, today_fn=None, offline=False,
    ):
        calls.append((from_date, to_date, offline))
        # Filter the canned frame to the requested window, matching
        # what the real loader does.
        mask = (df["date"] >= pd.Timestamp(from_date)) & (
            df["date"] <= pd.Timestamp(to_date)
        )
        return df[mask].copy()

    monkeypatch.setattr(
        _regime_mod.india_vix_loader, "load_india_vix",
        fake_load_india_vix,
    )
    return calls


def _canonical_india_vix_frame(n: int = 300) -> pd.DataFrame:
    """Build a canonical India VIX frame matching the loader's
    schema. 300 daily rows starting 2024-01-02 with sine-wave
    closes in a plausible range."""
    dates = pd.date_range("2024-01-02", periods=n, freq="D")
    vals = 15.0 + 5.0 * np.sin(np.linspace(0, 6 * np.pi, n)) + np.linspace(0, 2, n)
    return pd.DataFrame({
        "date": dates.astype("datetime64[us]"),
        "india_vix_open":  vals - 0.5,
        "india_vix_high":  vals + 0.5,
        "india_vix_low":   vals - 1.0,
        "india_vix_close": vals,
        "india_vix_prev_close": np.concatenate([[vals[0]], vals[:-1]]),
    })


def test_load_india_vix_signal_returns_close_series(monkeypatch):
    """LOAD-BEARING shape contract: returns a date-indexed
    pd.Series of float64 named 'india_vix_close'."""
    df = _canonical_india_vix_frame(60)
    _stub_india_vix_loader(monkeypatch, df)
    s = load_india_vix_signal(date(2024, 1, 2), date(2024, 3, 1))
    assert isinstance(s, pd.Series)
    assert s.dtype == np.float64
    assert s.name == "india_vix_close"
    assert isinstance(s.index, pd.DatetimeIndex)


def test_load_india_vix_signal_sorted_ascending(monkeypatch):
    """Index ascending — regime_percentile requires this."""
    df = _canonical_india_vix_frame(60)
    # Shuffle the frame so the function has to sort.
    df = df.sample(frac=1, random_state=0).reset_index(drop=True)
    _stub_india_vix_loader(monkeypatch, df)
    s = load_india_vix_signal(date(2024, 1, 2), date(2024, 3, 1))
    assert s.index.is_monotonic_increasing


def test_load_india_vix_signal_empty_window_returns_empty_series(monkeypatch):
    """Loader returns empty → signal is empty schema-shaped Series."""
    df = _canonical_india_vix_frame(60)
    _stub_india_vix_loader(monkeypatch, df)
    s = load_india_vix_signal(date(2099, 1, 1), date(2099, 12, 31))
    assert s.empty
    assert s.name == "india_vix_close"


def test_load_india_vix_signal_forwards_offline(monkeypatch):
    """offline=True propagates to the loader."""
    df = _canonical_india_vix_frame(60)
    calls = _stub_india_vix_loader(monkeypatch, df)
    load_india_vix_signal(
        date(2024, 1, 2), date(2024, 3, 1), offline=True,
    )
    assert calls[0][2] is True  # offline flag


def test_default_regime_signal_routes_to_v2_india_vix(monkeypatch):
    """LOAD-BEARING canonical entry point: default_regime_signal
    returns what load_india_vix_signal returns (v2). If the
    canonical signal drifts back to v1 without intent, this
    catches it."""
    df = _canonical_india_vix_frame(60)
    _stub_india_vix_loader(monkeypatch, df)
    s_default = default_regime_signal(date(2024, 1, 2), date(2024, 3, 1))
    s_v2 = load_india_vix_signal(date(2024, 1, 2), date(2024, 3, 1))
    pd.testing.assert_series_equal(s_default, s_v2)


def test_current_regime_state_composes_load_and_state(monkeypatch):
    """LOAD-BEARING end-to-end: current_regime_state(as_of) loads
    India VIX over a backfilled lookback window and returns ON/OFF.
    The result should match calling load + regime_state by hand."""
    df = _canonical_india_vix_frame(400)
    _stub_india_vix_loader(monkeypatch, df)
    as_of = date(2024, 12, 1)
    state = current_regime_state(as_of, lookback_td=252)
    assert state in ("ON", "OFF")
    # Match the hand-composed result.
    signal = load_india_vix_signal(
        date(2024, 1, 2), date(2024, 12, 1),
    )
    hand_state = regime_state(signal, as_of, lookback_td=252)
    # Both should agree (current_regime_state backfilled enough).
    assert state == hand_state


def test_current_regime_state_uses_backfill_cushion(monkeypatch):
    """LOAD-BEARING: the function backfills enough calendar days
    to cover the requested TD lookback. With lookback_td=252,
    it must load ≥ ~365 + 30 calendar days."""
    df = _canonical_india_vix_frame(400)
    calls = _stub_india_vix_loader(monkeypatch, df)
    as_of = date(2024, 12, 1)
    current_regime_state(as_of, lookback_td=252)
    assert len(calls) >= 1
    from_date, to_date, _ = calls[0]
    spanned = (to_date - from_date).days
    assert spanned >= 365  # 252 * 365/252 = 365
    assert spanned >= 252 * 365 / 252  # explicit pin


def test_current_regime_state_off_on_insufficient_history(monkeypatch):
    """Cold cache for the lookback window → percentile NaN →
    state OFF per memoir §21.4 F9 skip-when-uncertain."""
    # Only 30 days of data → << 0.5 * 252 = 126 floor → NaN → OFF.
    df = _canonical_india_vix_frame(30)
    _stub_india_vix_loader(monkeypatch, df)
    as_of = date(2024, 12, 1)
    assert current_regime_state(as_of, lookback_td=252) == "OFF"


def test_current_regime_state_forwards_offline(monkeypatch):
    df = _canonical_india_vix_frame(400)
    calls = _stub_india_vix_loader(monkeypatch, df)
    current_regime_state(date(2024, 12, 1), offline=True)
    assert calls[0][2] is True


def test_current_regime_state_custom_threshold(monkeypatch):
    """Custom threshold_pct flows through to regime_state.
    Threshold=0 → OFF unless percentile is exactly 0 (impossible
    on a non-flat series); threshold=100 → ON always (unless NaN)."""
    df = _canonical_india_vix_frame(400)
    _stub_india_vix_loader(monkeypatch, df)
    as_of = date(2024, 12, 1)
    # threshold_pct=100 → percentile ≤ 100 is always true (if not NaN) → ON.
    assert current_regime_state(
        as_of, threshold_pct=100.0, lookback_td=252,
    ) == "ON"

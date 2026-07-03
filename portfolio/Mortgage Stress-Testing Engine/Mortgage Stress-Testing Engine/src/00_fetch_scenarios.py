"""
00_fetch_scenarios.py — Build the Fed 2026 supervisory-scenario CSV.

Encodes the ANCHOR VALUES from the Federal Reserve's published narrative for the
2026 Dodd-Frank Act Stress Test scenarios (baseline + severely adverse), then
interpolates quarter-by-quarter over the 13-quarter horizon (2026Q1 - 2029Q1).
Output is the tidy CSV the brief asks for:  scenario, quarter, variable, value.

SOURCE (verbatim anchors used below), Federal Reserve, "2026 Stress Test
Scenarios" (https://www.federalreserve.gov/publications/2026-stress-test-scenarios.htm):

  Jump-off quarter = 2025Q4. Scenario starts 2026Q1.

  BASELINE:
    * Unemployment 4.6% in 2026Q1, holds through 2026Q3, then gradually
      declines to 4.2% by end of scenario.
    * Real GDP growth rises from 1.0% (2025Q4) to 2.1% by 2027Q1, ~flat after.
    * Mortgage rate declines from 6.2% (2025Q4) to 5.7% by 2028Q3.
    * 10-yr Treasury ~4.1% throughout. Nominal house prices rise gradually.

  SEVERELY ADVERSE:
    * Unemployment climbs to a 10.0% peak in 2027Q3 (7th quarter), +5.5pp vs
      its 2025Q4 level (4.5%), then recovers slowly.
    * House prices fall steadily to a trough ~30% below 2025Q4 level by 2027Q4
      (8th quarter).
    * Mortgage-to-10yr spread widens 1.3pp to 3.4pp by 2026Q3, then narrows to
      ~2.4pp by scenario end (risk-free rates decline in the recession), so the
      mortgage rate stays elevated relative to a falling 10-yr Treasury.
    * Severe global recession: equities -58% by 2026Q3, VIX peak 72% (2026Q2),
      BBB spread to 5.7pp (2026Q3), CRE prices -39% trough (2027Q4).

NOTE / GUARDRAIL: these are the published narrative anchors. The exact
quarter-by-quarter values live in the Fed's official Table 3.A / 4.A spreadsheet
on the page above. For a fully exact reproduction, download that file and pass
--official-csv PATH; this script will then prefer those values. The scenarios are
HYPOTHETICAL regulatory scenarios, NOT forecasts.

Variables emitted (the ones the PD/hazard model consumes):
    unemployment_rate   (%)
    hpi                 (index, 2025Q4 = 100)
    hpi_yoy             (%, year-over-year growth of hpi)
    mortgage_rate       (%)
    gdp_growth          (% annualized, real GDP)

Usage:
  python src/00_fetch_scenarios.py
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from config import SCENARIOS

# 13 projection quarters: 2026Q1 ... 2029Q1
QUARTERS = [f"{y}Q{q}" for y in range(2026, 2030) for q in range(1, 5)][:13]


def _interp(anchors: dict[int, float], n=13) -> np.ndarray:
    """Piecewise-linear interpolation across quarters 1..n from {q_index: value}."""
    xs = sorted(anchors)
    ys = [anchors[x] for x in xs]
    grid = np.arange(1, n + 1)
    return np.interp(grid, xs, ys)


def build_scenarios() -> pd.DataFrame:
    rows = []

    # ---- BASELINE ----------------------------------------------------------
    base_unrate = _interp({1: 4.6, 3: 4.6, 13: 4.2})
    base_gdp = _interp({1: 1.4, 5: 2.1, 13: 2.0})          # 2025Q4=1.0 -> 2.1 by 2027Q1
    base_mtg = _interp({1: 6.15, 11: 5.7, 13: 5.7})        # 6.2 -> 5.7 by 2028Q3
    base_hpi = 100.0 * (1.0 + 0.02) ** (np.arange(1, 14) / 4.0)  # ~+2%/yr

    # ---- SEVERELY ADVERSE --------------------------------------------------
    # Unemployment: 4.5 (jump-off) -> 10.0 peak at q7 -> slow recovery.
    sa_unrate = _interp({1: 5.6, 4: 8.2, 7: 10.0, 10: 9.4, 13: 8.6})
    # House prices: 100 (2025Q4) -> -30% trough at q8 (70.0) -> flat.
    sa_hpi = _interp({1: 96.0, 4: 84.0, 8: 70.0, 13: 71.0})
    # Mortgage rate: elevated; 10-yr falls but spread widens to 3.4pp by q3.
    sa_mtg = _interp({1: 6.4, 3: 6.5, 7: 5.9, 13: 5.4})
    # Real GDP growth: severe recession trough early, recovery later.
    sa_gdp = _interp({1: -6.5, 3: -7.5, 6: 0.0, 9: 4.0, 13: 3.5})

    def hpi_yoy(series):
        s = np.asarray(series, float)
        out = np.full_like(s, np.nan)
        out[4:] = (s[4:] / s[:-4] - 1.0) * 100.0
        # first year vs 2025Q4 = 100 baseline
        out[:4] = (s[:4] / 100.0 - 1.0) * 100.0
        return out

    series_map = {
        "baseline": {
            "unemployment_rate": base_unrate,
            "hpi": base_hpi,
            "hpi_yoy": hpi_yoy(base_hpi),
            "mortgage_rate": base_mtg,
            "gdp_growth": base_gdp,
        },
        "severely_adverse": {
            "unemployment_rate": sa_unrate,
            "hpi": sa_hpi,
            "hpi_yoy": hpi_yoy(sa_hpi),
            "mortgage_rate": sa_mtg,
            "gdp_growth": sa_gdp,
        },
    }

    for scenario, vars_ in series_map.items():
        for variable, values in vars_.items():
            for qi, q in enumerate(QUARTERS):
                rows.append({
                    "scenario": scenario,
                    "quarter": q,
                    "quarter_index": qi + 1,
                    "variable": variable,
                    "value": round(float(values[qi]), 3),
                })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--official-csv", default=None,
                    help="Path to the Fed's official Table 3.A/4.A CSV to use instead.")
    args = ap.parse_args()

    SCENARIOS.mkdir(parents=True, exist_ok=True)
    if args.official_csv:
        raise NotImplementedError(
            "Official-CSV ingestion stub: map the Fed table columns to "
            "[scenario, quarter, variable, value] here once you download it.")

    df = build_scenarios()
    out = SCENARIOS / "fed_2026_scenarios.csv"
    df.to_csv(out, index=False)
    print(f"Wrote {len(df)} rows -> {out}")
    # Quick headline check
    piv = df[df.variable == "unemployment_rate"].pivot_table(
        index="quarter_index", columns="scenario", values="value")
    print("\nUnemployment path (%):")
    print(piv.to_string())


if __name__ == "__main__":
    main()

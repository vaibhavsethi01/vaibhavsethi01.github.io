"""
10_powerbi_export.py — Star-schema CSV export for Power BI / Tableau.

Reshapes the projection + segment outputs into a clean fact/dimension model that
imports directly into Power BI Service (browser, Mac-friendly) or Tableau. Lets
you build the dashboard with the "Power BI" toolchain without a Windows VM.

Outputs (dashboard/powerbi/):
  dim_scenario.csv, fact_projection.csv, fact_segment_loss.csv
Usage:  python src/10_powerbi_export.py
"""
from __future__ import annotations
import pandas as pd
from config import OUTPUTS, DASHBOARD

OUT = DASHBOARD / "powerbi"


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    dim_scenario = pd.DataFrame({
        "scenario_id": [1, 2],
        "scenario": ["baseline", "severely_adverse"],
        "scenario_label": ["Baseline", "Severely Adverse"],
        "peak_unemployment_pct": [4.6, 10.0],
        "hpi_trough_pct": [None, -30.0],
    })
    smap = dict(zip(dim_scenario.scenario, dim_scenario.scenario_id))

    proj = pd.read_csv(OUTPUTS / "expected_loss_by_scenario.csv")
    fact_proj = proj[["scenario", "quarter", "quarter_index", "unemployment_rate",
                      "hpi_index", "quarterly_default_rate_pct",
                      "cumulative_default_rate_pct", "cumulative_loss_rate_pct",
                      "expected_loss"]].copy()
    fact_proj.insert(0, "scenario_id", fact_proj["scenario"].map(smap))
    fact_proj.drop(columns="scenario").to_csv(OUT / "fact_projection.csv", index=False)

    seg = pd.read_csv(OUTPUTS / "loss_by_segment.csv")
    seg.insert(0, "scenario_id", seg["scenario"].map(smap))
    seg.drop(columns="scenario").to_csv(OUT / "fact_segment_loss.csv", index=False)

    dim_scenario.to_csv(OUT / "dim_scenario.csv", index=False)
    print(f"Wrote star schema to {OUT}:")
    for f in ["dim_scenario.csv", "fact_projection.csv", "fact_segment_loss.csv"]:
        n = len(pd.read_csv(OUT / f))
        print(f"  {f}: {n} rows")


if __name__ == "__main__":
    main()

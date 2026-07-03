"""
06_stress_project.py — Roll the book forward under the Fed 2026 scenarios (Phase 4).

Takes an "as-of" portfolio (the 2017-2019 origination cohort as the current book),
and projects it quarter-by-quarter under each Fed 2026 scenario's macro path using
the fitted discrete-time DEFAULT and PREPAY hazards from Phase 3. Uses an expected
(fractional-survival) roll-forward — no Monte Carlo:

  for each quarter t:
      current_ltv_t = original_ltv * (HPI_asof / HPI_scenario_t)   # price channel
      h_def = default_hazard(age_t, fico, current_ltv_t, dti, rate, unemployment_t)
      h_pp  = prepay_hazard(...)
      expected_defaults_t = survival * h_def
      survival           *= (1 - h_def - h_pp)      # competing prepayment risk

Outputs (per scenario, per quarter): survival, quarterly + cumulative default
rate, and defaulted UPB (exposure) — consumed by 07_lgd_el.py for Expected Loss.

Assumptions (stated): as-of book = 2017-19 cohort; starting seasoning 6 quarters;
EAD = original UPB (loss RATE is what we report); HPI index = 100 at as-of.

Outputs: outputs/stress_projection.csv
Usage:   python src/06_stress_project.py
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import joblib

from config import OUTPUTS, MODELS, SCENARIOS

ASOF_COHORT = "covid"          # 2017-2019 book stands in for the "current" portfolio
START_AGE_Q = 6                # quarters of seasoning at as-of
HPI_ASOF = 100.0


def load_scenarios():
    df = pd.read_csv(SCENARIOS / "fed_2026_scenarios.csv")
    wide = df.pivot_table(index=["scenario", "quarter_index", "quarter"],
                          columns="variable", values="value").reset_index()
    return wide.sort_values(["scenario", "quarter_index"])


def main():
    feats = pd.read_parquet(OUTPUTS / "features_origination.parquet")
    book = feats[feats.cohort == ASOF_COHORT].copy()
    book = book.dropna(subset=["fico", "oltv", "odti", "orig_rate", "orig_upb"])
    n0 = len(book)
    upb0 = book["orig_upb"].to_numpy(float)
    total_upb0 = upb0.sum()

    hz_def = joblib.load(MODELS / "hazard_default.joblib")
    hz_pp = joblib.load(MODELS / "hazard_prepay.joblib")
    spec = joblib.load(MODELS / "hazard_feature_spec.joblib")

    fico = book["fico"].to_numpy(float)
    oltv = book["oltv"].to_numpy(float)
    odti = book["odti"].to_numpy(float)
    rate = book["orig_rate"].to_numpy(float)

    scen = load_scenarios()
    rows = []
    for scenario, g in scen.groupby("scenario"):
        survival = np.ones(n0)
        cum_def = np.zeros(n0)
        for _, q in g.iterrows():
            t = int(q["quarter_index"])
            age = START_AGE_Q + t
            hpi_t = q["hpi"]
            unemp_t = q["unemployment_rate"]
            mtg_t = q["mortgage_rate"]
            hpi_yoy_t = q["hpi_yoy"]
            current_ltv = np.minimum(oltv * (HPI_ASOF / hpi_t), 250.0)

            d = pd.DataFrame({
                "loan_age_q": age, "loan_age_q_sq": age * age,
                "fico": fico, "current_ltv": current_ltv, "odti": odti,
                "orig_rate": rate, "unemployment_rate": unemp_t,
            })[spec["default"]]
            p = pd.DataFrame({
                "loan_age_q": age, "loan_age_q_sq": age * age,
                "fico": fico, "orig_rate": rate, "unemployment_rate": unemp_t,
                "hpi_yoy": hpi_yoy_t, "mortgage_rate": mtg_t,
            })[spec["prepay"]]

            h_def = hz_def.predict_proba(d)[:, 1]
            h_pp = hz_pp.predict_proba(p)[:, 1]
            exp_def = survival * h_def
            cum_def += exp_def
            survival = survival * np.maximum(1 - h_def - h_pp, 0.0)

            defaulted_upb = float((exp_def * upb0).sum())
            rows.append({
                "scenario": scenario, "quarter_index": t, "quarter": q["quarter"],
                "unemployment_rate": round(unemp_t, 2), "hpi_index": round(hpi_t, 1),
                "surviving_frac": round(float(survival.mean()), 4),
                "quarterly_default_rate_pct": round(100 * float(exp_def.sum() / n0), 4),
                "cumulative_default_rate_pct": round(100 * float(cum_def.sum() / n0), 4),
                "defaulted_upb": defaulted_upb,
                "cumulative_defaulted_upb": None,  # filled below
            })

    out = pd.DataFrame(rows)
    out["cumulative_defaulted_upb"] = (out.groupby("scenario")["defaulted_upb"]
                                       .cumsum().round(0))
    out["portfolio_upb0"] = round(total_upb0, 0)
    out["n_loans"] = n0
    out.to_csv(OUTPUTS / "stress_projection.csv", index=False)

    print(f"As-of book: {n0:,} loans ({ASOF_COHORT} cohort), ${total_upb0/1e9:.1f}B UPB")
    for scenario, g in out.groupby("scenario"):
        last = g.iloc[-1]
        peak_q = g["quarterly_default_rate_pct"].max()
        print(f"  {scenario:18s} cumulative default {last['cumulative_default_rate_pct']:.2f}% "
              f"over {len(g)} quarters | peak quarterly {peak_q:.3f}%")
    base = out[out.scenario == "baseline"]["cumulative_default_rate_pct"].iloc[-1]
    sev = out[out.scenario == "severely_adverse"]["cumulative_default_rate_pct"].iloc[-1]
    print(f"\nHEADLINE: severely-adverse cumulative default {sev:.2f}% vs "
          f"baseline {base:.2f}%  ->  {sev/base:.1f}x")
    print(f"Wrote {OUTPUTS/'stress_projection.csv'}")


if __name__ == "__main__":
    main()

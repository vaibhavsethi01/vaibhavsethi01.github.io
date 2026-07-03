"""
08_export_dashboard.py — Aggregate outputs for the dashboard + web simulator (Phase 6).

Runs a per-loan version of the Phase-4 roll-forward (so we can attribute projected
loss to risk segments), aggregates loss by scenario x FICO band x LTV band x state x
loan purpose, and writes:
  * outputs/loss_by_segment.csv            (tidy segment table for BI / Power BI)
  * dashboard/data.js                      (window.DASH_DATA bundle for the web app)
      - portfolio time series (default + loss by scenario/quarter)
      - segment breakdowns
      - KPI cards
      - simulator params (fitted hazard coefficients + scaler + representative loan)

Usage:  python src/08_export_dashboard.py
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
import joblib

from config import OUTPUTS, MODELS, SCENARIOS, DASHBOARD, ASSUMED_LGD

ASOF_COHORT = "covid"
START_AGE_Q = 6
HPI_ASOF = 100.0
LGD = ASSUMED_LGD


def fico_band(x):
    if x < 620: return "<620"
    if x < 660: return "620-659"
    if x < 700: return "660-699"
    if x < 740: return "700-739"
    if x < 780: return "740-779"
    return "780+"


def ltv_band(x):
    if x <= 60: return "<=60"
    if x <= 70: return "61-70"
    if x <= 80: return "71-80"
    if x <= 90: return "81-90"
    return "91+"


def load_scenarios():
    df = pd.read_csv(SCENARIOS / "fed_2026_scenarios.csv")
    return df.pivot_table(index=["scenario", "quarter_index", "quarter"],
                          columns="variable", values="value").reset_index()


def project_per_loan(book, hz_def, hz_pp, spec, g):
    """Return per-loan expected cumulative default fraction over the horizon."""
    n = len(book)
    fico = book["fico"].to_numpy(float); oltv = book["oltv"].to_numpy(float)
    odti = book["odti"].to_numpy(float); rate = book["orig_rate"].to_numpy(float)
    survival = np.ones(n); cum_def = np.zeros(n)
    for _, q in g.iterrows():
        t = int(q["quarter_index"]); age = START_AGE_Q + t
        current_ltv = np.minimum(oltv * (HPI_ASOF / q["hpi"]), 250.0)
        d = pd.DataFrame({"loan_age_q": age, "loan_age_q_sq": age*age, "fico": fico,
                          "current_ltv": current_ltv, "odti": odti, "orig_rate": rate,
                          "unemployment_rate": q["unemployment_rate"]})[spec["default"]]
        p = pd.DataFrame({"loan_age_q": age, "loan_age_q_sq": age*age, "fico": fico,
                          "orig_rate": rate, "unemployment_rate": q["unemployment_rate"],
                          "hpi_yoy": q["hpi_yoy"], "mortgage_rate": q["mortgage_rate"]})[spec["prepay"]]
        h_def = hz_def.predict_proba(d)[:, 1]; h_pp = hz_pp.predict_proba(p)[:, 1]
        cum_def += survival * h_def
        survival = survival * np.maximum(1 - h_def - h_pp, 0.0)
    return cum_def


def main():
    DASHBOARD.mkdir(exist_ok=True)
    feats = pd.read_parquet(OUTPUTS / "features_origination.parquet")
    book = feats[feats.cohort == ASOF_COHORT].dropna(
        subset=["fico", "oltv", "odti", "orig_rate", "orig_upb"]).copy()
    book["fico_band"] = book["fico"].map(fico_band)
    book["ltv_band"] = book["oltv"].map(ltv_band)

    hz_def = joblib.load(MODELS / "hazard_default.joblib")
    hz_pp = joblib.load(MODELS / "hazard_prepay.joblib")
    spec = joblib.load(MODELS / "hazard_feature_spec.joblib")
    scen = load_scenarios()

    # per-loan projected loss by scenario
    seg_frames = []
    for scenario, g in scen.groupby("scenario"):
        cd = project_per_loan(book, hz_def, hz_pp, spec, g)
        b = book.copy()
        b["scenario"] = scenario
        b["exp_default"] = cd
        b["exp_loss"] = cd * b["orig_upb"] * LGD
        seg_frames.append(b)
    allb = pd.concat(seg_frames, ignore_index=True)

    def agg(dimcol):
        r = (allb.groupby(["scenario", dimcol])
             .apply(lambda x: pd.Series({
                 "loans": len(x),
                 "upb": x["orig_upb"].sum(),
                 "exp_loss": x["exp_loss"].sum(),
                 "loss_rate_pct": 100 * x["exp_loss"].sum() / x["orig_upb"].sum(),
                 "default_rate_pct": 100 * x["exp_default"].mean(),
             }), include_groups=False).reset_index())
        r["dimension"] = dimcol
        return r.rename(columns={dimcol: "segment"})

    seg = pd.concat([agg("fico_band"), agg("ltv_band"), agg("loan_purpose")],
                    ignore_index=True)
    # top states by exposure
    top_states = (book.groupby("state")["orig_upb"].sum().nlargest(10).index.tolist())
    st = allb[allb.state.isin(top_states)]
    seg_state = (st.groupby(["scenario", "state"])
                 .apply(lambda x: pd.Series({
                     "loans": len(x), "upb": x["orig_upb"].sum(),
                     "exp_loss": x["exp_loss"].sum(),
                     "loss_rate_pct": 100*x["exp_loss"].sum()/x["orig_upb"].sum(),
                     "default_rate_pct": 100*x["exp_default"].mean()}),
                     include_groups=False).reset_index()
                 .rename(columns={"state": "segment"}))
    seg_state["dimension"] = "state"
    seg = pd.concat([seg, seg_state], ignore_index=True)
    seg.to_csv(OUTPUTS / "loss_by_segment.csv", index=False)

    # ---- time series + KPIs from the portfolio projection -----------------
    proj = pd.read_csv(OUTPUTS / "expected_loss_by_scenario.csv")
    ts = {}
    for scenario, g in proj.groupby("scenario"):
        ts[scenario] = {
            "quarter": g["quarter"].tolist(),
            "cum_default_pct": g["cumulative_default_rate_pct"].round(3).tolist(),
            "cum_loss_pct": g["cumulative_loss_rate_pct"].round(3).tolist(),
            "quarterly_default_pct": g["quarterly_default_rate_pct"].round(4).tolist(),
            "unemployment": g["unemployment_rate"].tolist(),
        }

    # ---- simulator params: fitted hazard coefficients + scaler ------------
    clf = hz_def.named_steps["clf"]; sc = hz_def.named_steps["sc"]
    sim = {
        "features": spec["default"],
        "coef": dict(zip(spec["default"], clf.coef_[0].round(6).tolist())),
        "intercept": float(clf.intercept_[0]),
        "scaler_mean": dict(zip(spec["default"], sc.mean_.round(6).tolist())),
        "scaler_scale": dict(zip(spec["default"], sc.scale_.round(6).tolist())),
        "rep_loan": {"fico": float(book.fico.mean()), "oltv": float(book.oltv.mean()),
                     "odti": float(book.odti.mean()), "orig_rate": float(book.orig_rate.mean())},
        "prepay_hazard_q": 0.0165, "lgd": LGD, "start_age_q": START_AGE_Q,
        "base_unemployment": 4.5, "horizon_q": 13,
    }

    upb0 = float(book["orig_upb"].sum())
    base = proj[proj.scenario == "baseline"].iloc[-1]
    sev = proj[proj.scenario == "severely_adverse"].iloc[-1]
    data = {
        "meta": {"n_loans": int(len(book)), "portfolio_upb": upb0,
                 "cohort": "2017-2019", "horizon_q": 13, "lgd": LGD,
                 "pd_gini": 0.66, "n_all_loans": 350000, "n_loanmonths": 19_090_738},
        "kpi": {
            "baseline_loss_pct": round(float(base["cumulative_loss_rate_pct"]), 2),
            "severe_loss_pct": round(float(sev["cumulative_loss_rate_pct"]), 2),
            "baseline_loss_usd": int(base["expected_loss"]),
            "severe_loss_usd": int(sev["expected_loss"]),
            "baseline_default_pct": round(float(base["cumulative_default_rate_pct"]), 2),
            "severe_default_pct": round(float(sev["cumulative_default_rate_pct"]), 2),
            "multiple": round(float(sev["cumulative_loss_rate_pct"]) /
                              max(float(base["cumulative_loss_rate_pct"]), 1e-9), 1),
        },
        "timeseries": ts,
        "segments": json.loads(seg.to_json(orient="records")),
        "simulator": sim,
    }
    with open(DASHBOARD / "data.js", "w") as f:
        f.write("window.DASH_DATA = " + json.dumps(data) + ";")

    print(f"Wrote {OUTPUTS/'loss_by_segment.csv'} and {DASHBOARD/'data.js'}")
    print(f"KPIs: baseline {data['kpi']['baseline_loss_pct']}% vs severe "
          f"{data['kpi']['severe_loss_pct']}%  ({data['kpi']['multiple']}x)")


if __name__ == "__main__":
    main()

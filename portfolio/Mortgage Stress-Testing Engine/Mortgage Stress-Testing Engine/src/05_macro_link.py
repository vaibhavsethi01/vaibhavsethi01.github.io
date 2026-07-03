"""
05_macro_link.py — Discrete-time hazard with macroeconomic covariates (Phase 3).

Builds a loan-QUARTER person-period panel from the monthly performance data,
joins the FRED macro series by calendar quarter, and fits two discrete-time
hazard models (logistic):
  * DEFAULT hazard  — P(enter 180+ DPD / credit event this quarter | survived)
  * PREPAY  hazard  — competing risk P(prepay this quarter | survived)

Design note on HPI: the DEFAULT hazard uses CUMULATIVE HPI change SINCE EACH
LOAN'S ORIGINATION (a mark-to-market equity / current-LTV proxy) rather than
contemporaneous national YoY growth. Because different vintages experience
different cumulative price paths at the same calendar date, this gives real
cross-sectional variation and breaks the unemployment/HPI collinearity that
otherwise flips the HPI sign. Falling prices -> less equity -> higher default,
which is exactly the channel the Fed's -30% house-price shock needs to hit.

Outputs:
  models/hazard_default.joblib, models/hazard_prepay.joblib, models/hazard_feature_spec.joblib
  outputs/hazard_coefficients.csv, outputs/default_rate_vs_unemployment.png

Usage:  python src/05_macro_link.py
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import duckdb

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression

from config import DB_PATH, MACRO, OUTPUTS, MODELS, RANDOM_STATE

AGE_FEATURES = ["loan_age_q", "loan_age_q_sq"]
# DEFAULT hazard uses CURRENT (mark-to-market) LTV = original LTV scaled by
# cumulative HPI change since origination. This is the standard way to inject the
# house-price channel: prices fall -> current LTV rises -> default rises, with a
# reliably-signed coefficient (unlike a separate, collinear HPI term).
DEFAULT_FEATURES = AGE_FEATURES + ["fico", "current_ltv", "odti", "orig_rate",
                                   "unemployment_rate"]
PREPAY_FEATURES = AGE_FEATURES + ["fico", "orig_rate",
                                  "unemployment_rate", "hpi_yoy", "mortgage_rate"]


def build_panel(con, loan_sample_pct=40):
    macro = pd.read_csv(MACRO / "macro_quarterly.csv")
    con.register("macro", macro)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE lq AS
        SELECT
            loan_sequence_number,
            (monthly_reporting_period // 100)              AS cal_year,
            ((monthly_reporting_period % 100) - 1) / 3 + 1 AS cal_q,
            MAX(TRY_CAST(current_delinquency_status AS INTEGER)) AS max_dq,
            MAX(CASE WHEN zero_balance_code IN ('02','03','09','15') THEN 1 ELSE 0 END) AS ce,
            MAX(CASE WHEN zero_balance_code = '01' THEN 1 ELSE 0 END) AS pp,
            MIN(loan_age) AS age_m
        FROM performance
        WHERE (hash(loan_sequence_number) % 100) < {loan_sample_pct}
        GROUP BY 1,2,3
    """)

    panel = con.execute("""
        WITH k AS (
            SELECT *,
                cal_year*4 + (cal_q-1) AS qkey,
                CASE WHEN max_dq >= 6 OR ce = 1 THEN 1 ELSE 0 END AS is_def,
                CASE WHEN pp = 1 THEN 1 ELSE 0 END                AS is_pp,
                2000 + CAST(SUBSTR(loan_sequence_number,2,2) AS INT) AS orig_year,
                CAST(SUBSTR(loan_sequence_number,5,1) AS INT)        AS orig_q
            FROM lq
        ),
        agg AS (
            SELECT loan_sequence_number,
                MIN(CASE WHEN is_def=1 THEN qkey END) AS def_q,
                MIN(CASE WHEN is_pp=1  THEN qkey END) AS pp_q,
                MAX(qkey) AS last_q
            FROM k GROUP BY 1
        ),
        stop AS (
            SELECT loan_sequence_number,
                LEAST(COALESCE(def_q,999999), COALESCE(pp_q,999999), last_q) AS stop_q,
                def_q, pp_q
            FROM agg
        )
        SELECT
            k.loan_sequence_number, k.cal_year, k.cal_q, k.qkey,
            k.age_m / 3.0                    AS loan_age_q,
            (k.age_m/3.0)*(k.age_m/3.0)      AS loan_age_q_sq,
            CASE WHEN k.qkey = s.def_q THEN 1 ELSE 0 END AS default_event,
            CASE WHEN k.qkey = s.pp_q  THEN 1 ELSE 0 END AS prepay_event,
            f.fico, f.oltv, f.odti, f.orig_rate,
            m.unemployment_rate, m.hpi_yoy, m.mortgage_rate,
            (m.hpi / mo.hpi - 1.0) * 100.0   AS hpi_growth_since_orig,
            LEAST(f.oltv * (mo.hpi / m.hpi), 250.0) AS current_ltv
        FROM k
        JOIN stop s USING (loan_sequence_number)
        JOIN features_origination f USING (loan_sequence_number)
        JOIN macro m  ON (k.cal_year = CAST(SUBSTR(m.quarter,1,4) AS INT)
                      AND k.cal_q   = CAST(SUBSTR(m.quarter,6,1) AS INT))
        JOIN macro mo ON (k.orig_year = CAST(SUBSTR(mo.quarter,1,4) AS INT)
                      AND k.orig_q    = CAST(SUBSTR(mo.quarter,6,1) AS INT))
        WHERE k.qkey <= s.stop_q
    """).fetchdf()
    return panel


def fit_hazard(panel, target, features):
    pipe = Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("sc", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, C=1.0)),
    ])
    pipe.fit(panel[features], panel[target].astype(int))
    coefs = pd.Series(pipe.named_steps["clf"].coef_[0], index=features)
    return pipe, coefs


def main():
    MODELS.mkdir(exist_ok=True); OUTPUTS.mkdir(exist_ok=True)
    con = duckdb.connect(str(DB_PATH))

    print("Building loan-quarter panel...")
    panel = build_panel(con)
    print(f"panel rows: {len(panel):,}  loans: {panel.loan_sequence_number.nunique():,}")
    print(f"raw quarterly default hazard {panel.default_event.mean():.4%}  "
          f"prepay {panel.prepay_event.mean():.4%}")

    hz_def, cdef = fit_hazard(panel, "default_event", DEFAULT_FEATURES)
    hz_pp, cpp = fit_hazard(panel, "prepay_event", PREPAY_FEATURES)

    cdef.to_csv(OUTPUTS / "hazard_coefficients.csv", header=["default_hazard"])
    print("\nDefault-hazard standardized coefficients (log-odds):")
    print(cdef.round(3).to_string())
    print("\nSign check [expect unemployment>0, current_ltv>0, fico<0, odti>0]:")
    print(f"  unemployment={cdef['unemployment_rate']:.3f}  "
          f"current_ltv={cdef['current_ltv']:.3f}  "
          f"fico={cdef['fico']:.3f}  odti={cdef['odti']:.3f}  orig_rate={cdef['orig_rate']:.3f}")

    ts = (panel.groupby(["cal_year", "cal_q"])
          .agg(def_rate=("default_event", "mean"),
               unemp=("unemployment_rate", "mean")).reset_index())
    ts["t"] = ts.cal_year + (ts.cal_q - 1) / 4
    ts = ts.sort_values("t")
    fig, ax1 = plt.subplots(figsize=(9, 5))
    ax1.plot(ts.t, ts.def_rate * 100, "b-o", ms=3, label="Quarterly default rate (%)")
    ax1.set_ylabel("Quarterly default rate (%)", color="b"); ax1.set_xlabel("Year")
    ax2 = ax1.twinx()
    ax2.plot(ts.t, ts.unemp, "r--", label="Unemployment (%)")
    ax2.set_ylabel("Unemployment rate (%)", color="r")
    plt.title("Default hazard tracks unemployment (real Freddie data)")
    fig.tight_layout(); plt.savefig(OUTPUTS / "default_rate_vs_unemployment.png", dpi=120); plt.close()

    joblib.dump(hz_def, MODELS / "hazard_default.joblib")
    joblib.dump(hz_pp, MODELS / "hazard_prepay.joblib")
    joblib.dump({"default": DEFAULT_FEATURES, "prepay": PREPAY_FEATURES},
                MODELS / "hazard_feature_spec.joblib")
    con.close()
    print(f"\nSaved hazards to {MODELS}, plot + coefs to {OUTPUTS}")


if __name__ == "__main__":
    main()

"""
generate_synthetic.py — Create SYNTHETIC Freddie-Mac-schema loan data.

WHY THIS EXISTS
---------------
The real Freddie Mac Single-Family Loan-Level Dataset requires a (free) account
login and cannot be redistributed. This script produces synthetic origination
and performance files that match the EXACT Freddie file layout (pipe-delimited,
no header, same column order as config.ORIGINATION_COLUMNS / PERFORMANCE_COLUMNS)
so the entire downstream pipeline (DuckDB load -> default flag -> PD model ->
macro link -> stress projection) runs end-to-end today.

The synthetic data is generated with REALISTIC structure:
  * FICO, LTV, DTI, rate, UPB distributions differ sensibly by vintage.
  * Monthly default/prepay hazards depend on loan risk drivers AND on a stylized
    macro backdrop (unemployment + HPI), so 2005-2008 "crisis" vintages take
    heavy losses through 2009-2012 and 2017-2019 vintages see a mild 2020 bump.
This means the fitted model recovers sensible signs (low FICO / high LTV / rising
unemployment -> higher default), which is the point of the demonstration.

SWAPPING IN REAL DATA: download the real Freddie files (see docs/DATA_GUIDE.md),
drop them in data/raw/, and run 01_load_duckdb.py with --source real. No model
code changes — the schema is identical.

Outputs (data/raw/):
  historical_data_YYYYQn.txt          (origination, one row per loan)
  historical_data_time_YYYYQn.txt     (performance, one row per loan per month)

Usage:
  python src/generate_synthetic.py --loans-per-quarter 1500
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from config import (
    RAW, RANDOM_STATE, SAMPLE_VINTAGES, ORIGINATION_COLUMNS, PERFORMANCE_COLUMNS,
    CREDIT_EVENT_ZB_CODES, PREPAY_ZB_CODE,
)

# Stylized US macro backdrop by calendar year (approximate real history) ------
# Annual avg unemployment rate (~UNRATE) and national HPI YoY % (~FMHPI).
MACRO_UNRATE = {
    2005: 5.1, 2006: 4.6, 2007: 4.6, 2008: 5.8, 2009: 9.3, 2010: 9.6,
    2011: 8.9, 2012: 8.1, 2013: 7.4, 2014: 6.2, 2015: 5.3, 2016: 4.9,
    2017: 4.4, 2018: 3.9, 2019: 3.7, 2020: 8.1, 2021: 5.4, 2022: 3.6,
    2023: 3.6, 2024: 4.0, 2025: 4.2,
}
MACRO_HPI_YOY = {
    2005: 10.0, 2006: 4.0, 2007: -3.0, 2008: -12.0, 2009: -6.0, 2010: -4.0,
    2011: -4.0, 2012: 5.0, 2013: 9.0, 2014: 5.0, 2015: 6.0, 2016: 6.0,
    2017: 6.0, 2018: 5.0, 2019: 4.0, 2020: 8.0, 2021: 18.0, 2022: 6.0,
    2023: -1.0, 2024: 5.0, 2025: 4.0,
}
LAST_OBS_YEAR = 2021  # stop performance tracking here (keeps files compact)

STATES = ["CA", "TX", "FL", "NY", "IL", "PA", "OH", "GA", "NC", "MI",
          "NJ", "VA", "WA", "AZ", "MA", "CO", "NV", "OR", "MN", "WI"]
STATE_WEIGHTS = np.array([0.13, 0.09, 0.08, 0.07, 0.05, 0.05, 0.04, 0.04, 0.04,
                          0.04, 0.04, 0.04, 0.04, 0.04, 0.03, 0.03, 0.03, 0.03,
                          0.03, 0.03])
STATE_WEIGHTS = STATE_WEIGHTS / STATE_WEIGHTS.sum()


def _quarters_for(vintage: int):
    return [f"{vintage}Q{q}" for q in (1, 2, 3, 4)]


def _gen_origination(rng, vintage, quarter_idx, n, seq_prefix):
    """Generate n origination rows for one quarter as a DataFrame."""
    # Crisis vintages: looser underwriting (lower FICO, higher LTV/DTI).
    crisis = vintage <= 2008
    fico_mean = 705 if crisis else 745
    ltv_mean = 78 if crisis else 73
    dti_mean = 39 if crisis else 35

    credit_score = np.clip(rng.normal(fico_mean, 50, n), 300, 850).round().astype(int)
    oltv = np.clip(rng.normal(ltv_mean, 12, n), 6, 97).round().astype(int)
    # CLTV >= LTV
    ocltv = np.clip(oltv + rng.exponential(3, n), oltv, 105).round().astype(int)
    odti = np.clip(rng.normal(dti_mean, 9, n), 1, 65).round().astype(int)
    orig_upb = np.clip(rng.lognormal(12.1, 0.45, n), 20000, 1_000_000)
    orig_upb = (orig_upb / 1000).round() * 1000  # Freddie rounds UPB to nearest $1000
    base_rate = {2005: 5.9, 2006: 6.4, 2007: 6.3, 2008: 6.0, 2017: 4.0,
                 2018: 4.5, 2019: 3.9}.get(vintage, 5.0)
    orig_interest_rate = np.clip(rng.normal(base_rate, 0.5, n)
                                 - (credit_score - 720) / 200.0, 2.0, 9.5).round(3)

    first_pay_month = quarter_idx * 3 + 2  # rough first-payment month within year
    first_pay_year = vintage
    if first_pay_month > 12:
        first_pay_month -= 12
        first_pay_year += 1
    first_payment_date = f"{first_pay_year}{first_pay_month:02d}"
    orig_loan_term = rng.choice([360, 180, 240], n, p=[0.85, 0.10, 0.05])
    mat_year = first_pay_year + (orig_loan_term // 12)
    maturity_date = [f"{mat_year[i]}{first_pay_month:02d}" for i in range(n)]

    states = rng.choice(STATES, n, p=STATE_WEIGHTS)
    seq = [f"{seq_prefix}{i:07d}" for i in range(1, n + 1)]

    df = pd.DataFrame({
        "credit_score": credit_score,
        "first_payment_date": first_payment_date,
        "first_time_homebuyer_flag": rng.choice(["Y", "N"], n, p=[0.2, 0.8]),
        "maturity_date": maturity_date,
        "msa": rng.choice(["", "31080", "35620", "16980", "19100", "12060"], n),
        "mi_pct": np.where(oltv > 80, rng.choice([12, 25, 30, 35], n), 0),
        "num_units": rng.choice([1, 2, 3, 4], n, p=[0.94, 0.04, 0.01, 0.01]),
        "occupancy_status": rng.choice(["P", "I", "S"], n, p=[0.88, 0.08, 0.04]),
        "ocltv": ocltv,
        "odti": odti,
        "orig_upb": orig_upb.astype(int),
        "oltv": oltv,
        "orig_interest_rate": orig_interest_rate,
        "channel": rng.choice(["R", "C", "B", "T"], n, p=[0.5, 0.3, 0.15, 0.05]),
        "ppm_flag": "N",
        "amortization_type": "FRM",
        "property_state": states,
        "property_type": rng.choice(["SF", "PU", "CO", "MH"], n, p=[0.7, 0.18, 0.1, 0.02]),
        "postal_code": rng.integers(100, 999, n).astype(str) + "00",
        "loan_sequence_number": seq,
        "loan_purpose": rng.choice(["P", "C", "N"], n, p=[0.5, 0.2, 0.3]),
        "orig_loan_term": orig_loan_term,
        "num_borrowers": rng.choice([1, 2, 3], n, p=[0.45, 0.5, 0.05]),
        "seller_name": "Other sellers",
        "servicer_name": "Other servicers",
        "super_conforming_flag": "",
        "pre_harp_loan_seq_number": "",
        "program_indicator": "9",
        "harp_indicator": "",
        "property_valuation_method": rng.choice([1, 2, 3], n).astype(str),
        "interest_only_flag": "N",
        "mi_cancellation_flag": rng.choice(["N", "9"], n, p=[0.9, 0.1]),
    })
    return df[ORIGINATION_COLUMNS]


def _simulate_performance(rng, orig, vintage):
    """Vectorized monthly simulation of the performance panel for one quarter.

    Returns a DataFrame in PERFORMANCE_COLUMNS order. Default = ever 180+ DPD or
    a credit-event zero-balance code; prepayment is a competing risk.
    """
    n = len(orig)
    fpd = int(orig["first_payment_date"].iloc[0])
    start_year, start_month = fpd // 100, fpd % 100

    # Per-loan static risk score driving the monthly default hazard logit.
    fico = orig["credit_score"].to_numpy()
    ltv = orig["oltv"].to_numpy()
    dti = orig["odti"].to_numpy()
    rate = orig["orig_interest_rate"].to_numpy()
    risk = (-(fico - 700) / 60.0
            + (ltv - 80) / 12.0
            + (dti - 35) / 12.0
            + (rate - 5.0) / 1.5)

    upb0 = orig["orig_upb"].to_numpy().astype(float)
    term = orig["orig_loan_term"].to_numpy()
    seq = orig["loan_sequence_number"].to_numpy()

    active = np.ones(n, dtype=bool)
    cur_upb = upb0.copy()
    ever_180 = np.zeros(n, dtype=bool)
    dq_status = np.zeros(n, dtype=int)  # consecutive months delinquent

    rows = []
    max_months = min((LAST_OBS_YEAR - start_year) * 12 + (12 - start_month) + 1, 120)

    for age in range(1, max_months + 1):
        if not active.any():
            break
        cal_month = start_month + age - 1
        cal_year = start_year + (cal_month - 1) // 12
        cal_month = (cal_month - 1) % 12 + 1
        if cal_year > LAST_OBS_YEAR:
            break
        period = cal_year * 100 + cal_month

        unrate = MACRO_UNRATE.get(cal_year, 5.0)
        hpi_yoy = MACRO_HPI_YOY.get(cal_year, 4.0)
        macro = 0.45 * (unrate - 5.0) - 0.10 * hpi_yoy

        idx = np.where(active)[0]
        # Monthly default hazard (logistic). Seasoning hump around 2-4 yrs.
        # Tuned so prime-conforming crisis vintages peak at realistic ~10-16%
        # cumulative serious-delinquency, COVID vintages ~1-3%.
        age_eff = -1.3 + 0.62 * np.log1p(age) - 0.0010 * age
        logit_d = -9.0 + 0.50 * risk[idx] + 0.45 * macro + age_eff
        h_default = 1.0 / (1.0 + np.exp(-logit_d))
        # Monthly prepayment hazard (competing risk): higher when rates fall / HPI rises.
        logit_p = -5.2 - 0.25 * risk[idx] + 0.03 * hpi_yoy + 0.004 * age
        h_prepay = 1.0 / (1.0 + np.exp(-logit_p))

        u = rng.random(len(idx))
        is_default = u < h_default
        is_prepay = (~is_default) & (u < h_default + h_prepay)

        # Amortize UPB on survivors (simple straight-ish paydown).
        cur_upb[idx] *= (1.0 - 1.0 / np.maximum(term[idx] - age + 1, 1))
        cur_upb[idx] = np.clip(cur_upb[idx], 0, None)

        # Delinquency bookkeeping for defaulters: ramp to 6 (180+ DPD).
        dq_status[idx[is_default]] += 1
        ever_180[idx[is_default]] = True

        for j_local, j in enumerate(idx):
            terminated = is_default[j_local] or is_prepay[j_local]
            zb_code = ""
            zb_eff = ""
            dstat = "0"
            actual_loss = ""
            net_sales = ""
            zb_removal_upb = ""
            if is_default[j_local]:
                zb_code = rng.choice(CREDIT_EVENT_ZB_CODES)
                zb_eff = f"{period}"
                dstat = "6"  # 180+ DPD at termination
                # Loss severity ~ depends on HPI; EAD = current UPB.
                sev = np.clip(rng.normal(0.32 - 0.004 * hpi_yoy, 0.08), 0.05, 0.75)
                loss = cur_upb[j] * sev
                actual_loss = f"{loss:.2f}"
                net_sales = f"{cur_upb[j] * (1 - sev):.2f}"
                zb_removal_upb = f"{cur_upb[j]:.2f}"
            elif is_prepay[j_local]:
                zb_code = PREPAY_ZB_CODE
                zb_eff = f"{period}"
                zb_removal_upb = f"{cur_upb[j]:.2f}"

            rows.append((
                seq[j], period, f"{cur_upb[j]:.2f}", dstat, age,
                max(term[j] - age, 0), "", "", zb_code, zb_eff,
                f"{rate[j]:.3f}", "0.00", "", "", net_sales, "", "", "", "", "",
                "", actual_loss, "", "", "", "", zb_removal_upb, "", "", "", "0.00",
                f"{cur_upb[j]:.2f}",
            ))
            if terminated:
                active[j] = False

    perf = pd.DataFrame(rows, columns=PERFORMANCE_COLUMNS)
    return perf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loans-per-quarter", type=int, default=1200,
                    help="Synthetic loans per origination quarter.")
    ap.add_argument("--seed", type=int, default=RANDOM_STATE)
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    total_loans = 0
    total_perf = 0
    for vintage in SAMPLE_VINTAGES:
        for qi, quarter in enumerate(_quarters_for(vintage)):
            n = args.loans_per_quarter
            # F=Freddie, last 2 digits of year, Q, quarter number
            seq_prefix = f"F{str(vintage)[2:]}Q{qi + 1}"
            orig = _gen_origination(rng, vintage, qi, n, seq_prefix)
            perf = _simulate_performance(rng, orig, vintage)

            orig_path = RAW / f"historical_data_{quarter}.txt"
            perf_path = RAW / f"historical_data_time_{quarter}.txt"
            orig.to_csv(orig_path, sep="|", header=False, index=False)
            perf.to_csv(perf_path, sep="|", header=False, index=False)
            total_loans += len(orig)
            total_perf += len(perf)
            print(f"  {quarter}: {len(orig):>6,} loans | {len(perf):>8,} perf rows")

    print(f"\nDONE. {total_loans:,} loans, {total_perf:,} performance rows -> {RAW}")
    print("These files are SYNTHETIC. Replace with real Freddie files for final results.")


if __name__ == "__main__":
    main()

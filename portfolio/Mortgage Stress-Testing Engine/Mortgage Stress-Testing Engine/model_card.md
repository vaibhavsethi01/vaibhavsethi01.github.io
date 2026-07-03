# Model Card — Severely Adverse PD / Stress-Testing Engine

*A governance document in the spirit of SR 11-7 (model risk management). Metric
fields marked **[TBD]** are populated automatically once Phase 2–4 run on the
chosen dataset.*

## Model overview

- **Name / version:** Severely Adverse PD + discrete-time hazard, v0.1
- **Owner:** Vaibhav Sethi
- **Purpose / intended use:** Estimate mortgage probability of default and project
  portfolio default and loss over a 9-quarter horizon under the Federal Reserve's
  2026 baseline and severely-adverse supervisory scenarios (CCAR/DFAST-style).
  Intended as a portfolio analytics / educational demonstration — **not** a
  deployed credit-decisioning system and not used to make lending decisions.
- **Model type:** (a) Binary PD — logistic regression benchmark + XGBoost
  challenger; (b) Discrete-time survival/hazard — logistic hazard on a loan-month
  panel with macro covariates.

## Data

- **Source:** Freddie Mac Single-Family Loan-Level Dataset (real) — currently
  synthetic, schema-identical, pending the user's data download.
- **Training window / cohorts:** 2005–2008 (crisis) and 2017–2019 (COVID)
  origination vintages, 5% loan-level sample.
- **Target:** Default = ever 180+ DPD (delinquency status ≥ 6) or credit-event
  zero-balance code (02/03/09/15). Prepayment (ZB 01) is a competing risk.
- **Macro covariates:** unemployment rate, HPI growth, 30-yr mortgage rate
  (FRED); state-level joins optional.

## Features

FICO, original LTV / CLTV / DTI, original interest rate, original UPB, loan
purpose, occupancy, property type, number of units, number of borrowers,
first-time-homebuyer flag, channel, property state, origination vintage. Sentinel
codes (9999 FICO, 999 LTV/DTI, etc.) handled explicitly. Hazard track adds loan
age and calendar-quarter macro values.

## Evaluation (out-of-time, by vintage)

Credit-risk metrics, not accuracy:

Out-of-time test = 2007/2008/2019 vintages (train = 2005/2006/2017/2018);
350,000 loans, 19M loan-month records. Credit-risk metrics, not accuracy:

| Metric | Logistic (OOT) | XGBoost (OOT) | XGBoost calibrated |
|---|---|---|---|
| ROC AUC | 0.829 | 0.830 | 0.830 |
| Gini (2·AUC−1) | 0.657 | 0.660 | 0.660 |
| KS statistic | 0.504 | 0.504 | 0.503 |
| PR-AUC (base rate 8.1%) | 0.330 | 0.337 | 0.335 |
| Brier | — | 0.175 | 0.064 |

Overfit check: XGBoost in-sample AUC 0.858 vs out-of-time 0.830 — modest,
healthy. Probabilities calibrated via isotonic regression (Brier 0.175 → 0.064);
reliability plot in `outputs/calibration_curve.png`.

## Explainability

SHAP global importance (TreeSHAP). Top drivers: FICO, property state, original
rate, DTI, LTV/CLTV. Sign check **confirmed** — correlation between feature and
its SHAP value: FICO −0.97 (lower score → higher risk), OLTV +0.92, OCLTV +0.86,
ODTI +0.91, original rate +0.90. All economically correct. See
`outputs/shap_importance.png`.

## Stress-projection results

As-of book = 2017-2019 cohort (147,609 loans, $35.4B UPB); 13-quarter horizon;
discrete-time hazard rolled forward under Fed 2026 macro paths; LGD 30%.

| Scenario | Cumulative default rate | Portfolio loss rate | Expected Loss |
|---|---|---|---|
| Baseline | 0.61% | 0.18% | $65M |
| Severely adverse | 3.28% | 0.99% | $352M |

Severely-adverse losses = **5.5× baseline**. Peak quarterly default 0.38% (severe)
vs 0.05% (baseline). Drivers: unemployment 4.5%→10% and house prices −30% raise
the mark-to-market-LTV and unemployment terms in the hazard. See
`outputs/stress_loss_curve.png`.

**LGD note:** the 50k-loan annual sample under-populates final-disposition loss
fields (only ~257 defaults with a clean realized loss), so a documented ~30%
mortgage LGD is used rather than an unreliable empirical estimate; re-estimate on
the full Standard dataset.

## Limitations & failure modes

- Trained on Freddie **conforming** loans — does **not** represent subprime,
  jumbo, or non-QM books; results don't generalize to those.
- Freddie data has **no protected-class fields**; no fair-lending (ECOA) audit is
  claimed. A real audit would require joining HMDA demographics (future work).
- Macro link is reduced-form; it captures unemployment/HPI/rate sensitivity, not
  every channel (e.g., credit-spread or CRE shocks in the 2026 scenario).
- Scenarios are **hypothetical regulatory scenarios, not forecasts.**
- The portfolio web simulator is **illustrative**, driven by the fitted
  relationship — not a deployed model.
- Synthetic-data results demonstrate the pipeline; headline numbers are only
  valid once real Freddie data is loaded.

## Reproducibility

`random_state=42` throughout; pinned `requirements.txt`; deterministic loan
sampling by hashed Loan Sequence Number.

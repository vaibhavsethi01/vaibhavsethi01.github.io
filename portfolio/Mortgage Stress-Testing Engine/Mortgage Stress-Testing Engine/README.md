# Severely Adverse — A Loan-Level Mortgage Stress-Testing Engine

**Probability-of-default modelling on millions of mortgages, projected forward
under the Federal Reserve's official 2026 recession scenarios — the same
CCAR/DFAST exercise large banks run for their regulator.**

> **Headline result (real Freddie data, Fed 2026 scenarios):**
> On a **$35.4B, 147,609-loan** book, projected 13-quarter portfolio loss =
> **0.18% baseline ($65M)** vs **0.99% severely adverse ($352M)** — severely-adverse
> losses run **5.5× baseline**. Cumulative default rate 0.61% → 3.28%.
> *(LGD 30% assumption; PD from a Gini-0.66 out-of-time model.)*

---

## Why this project

Banks subject to the Dodd-Frank Act Stress Test (DFAST) must show their regulator
how their loan book would perform under a hypothetical severe recession. This
project reproduces that workflow end-to-end on real public mortgage data: build a
calibrated PD model, link it to macroeconomic drivers, and roll the book forward
quarter-by-quarter under the Fed's published 2026 baseline and severely-adverse
scenarios — reporting the result in **dollars and loss-rate**, the way a risk
committee would read it.

It is the quantitative-risk companion to my
[Banking Risk Platform](https://github.com/vaibhavsethi01/banking-risk-platform)
(credit scoring + expected loss), scaled up to regulated stress testing.

## What's in the box

| Deliverable | Where |
|---|---|
| Reproducible pipeline (data → model → projection) | `src/` |
| Calibrated PD model (logistic benchmark + XGBoost challenger) | `src/04_pd_model.py` |
| Discrete-time hazard with macro covariates | `src/05_macro_link.py` |
| Stress projection: baseline vs severely-adverse over 9 quarters | `src/06_stress_project.py` |
| LGD estimate + portfolio Expected Loss | `src/07_lgd_el.py` |
| Interactive web dashboard + stress simulator | `dashboard/index.html` |
| Unsupervised risk segmentation (PCA + K-Means) | `src/09_segmentation.py` |
| Model card (governance) | `model_card.md` |

## Multi-tool implementations (same analysis, five toolchains)

To show tool breadth, the core credit-risk workflow is reproduced across the
stacks a bank actually uses:

| Tool | Artifact | What it shows |
|---|---|---|
| **SQL** | `sql/analytics.sql` | Window functions, CTEs, vintage seasoning curves, cohort & segment analysis on 19M rows |
| **SAS** | `sas/pd_model.sas` | `PROC LOGISTIC` PD model + AUC/Gini/KS, `PROC SQL` (runs free on SAS OnDemand) |
| **R** | `R/glm_crosscheck.R` | `glm()` logistic + `pROC` validation, cross-checked vs Python |
| **Excel** | `excel/Stress_Test_Results.xlsx` | Formatted results, conditional formatting, and a formula-driven live stress calculator |
| **Power BI** | `dashboard/powerbi/` | Star-schema export + build guide for Power BI Service |

## Data (all free, all real)

- **Loans:** Freddie Mac Single-Family Loan-Level Dataset (~55M mortgages,
  1999–2025). Cohorts chosen to contain a downturn: **2005–2008 crisis** and
  **2017–2019 COVID**, sampled to a laptop-friendly 5% by loan.
- **Macro:** FRED — `UNRATE`, `MORTGAGE30US`, `GDPC1`, plus an HPI series.
- **Shock:** Federal Reserve [2026 DFAST supervisory scenarios](https://www.federalreserve.gov/publications/2026-stress-test-scenarios.htm)
  (baseline + severely adverse). The 2026 severely-adverse path takes unemployment
  to a **10% peak in 2027Q3** and house prices to a **~30% trough by 2027Q4**.

See [`docs/DATA_GUIDE.md`](docs/DATA_GUIDE.md) to put the real data in place.
Freddie's license prohibits redistributing raw data, so `data/raw/` is gitignored;
only code, aggregates, and charts are committed.

> **Reproducibility:** `random_state=42` everywhere. The pipeline currently runs
> on **synthetic, schema-identical** loan data so it is fully demonstrable today;
> swapping in the real Freddie files requires no code changes (see DATA_GUIDE).
> The Fed scenarios are **real**. The stress scenarios are *hypothetical
> regulatory scenarios, not forecasts.*

## Method (how it works)

1. **Data engineering (DuckDB).** Raw pipe-delimited files are queried directly
   in DuckDB — tens of millions of rows on a laptop, never loaded whole into
   pandas. `default` = ever 180+ days delinquent **or** terminated via a
   credit-event zero-balance code (`02/03/09/15`); **prepayment is a competing
   risk**, not a default.
2. **PD model.** Logistic regression (interpretable benchmark) vs XGBoost
   (challenger), validated **out-of-time by vintage**, scored on **Gini / KS /
   PR-AUC** (not accuracy), calibrated (Platt/isotonic), explained with **SHAP**.
3. **Macro linkage.** A discrete-time hazard model on the loan-month panel where
   the per-quarter default hazard depends on loan age, loan features, and macro
   covariates (unemployment, HPI growth, mortgage rate).
4. **Stress projection.** Roll the hazard forward 9 quarters under each Fed
   scenario's macro path, accounting for competing prepayment → quarterly and
   cumulative default rates and portfolio loss.
5. **LGD & Expected Loss.** LGD from realized losses on disposed loans (or a
   stated ~30% assumption); EAD = current UPB at default; EL = PD × LGD × EAD.

## Tech stack

**Python** 3.11 · **SQL** (DuckDB — window functions, CTEs) · **SAS**
(PROC LOGISTIC) · **R** (glm, pROC) · **Excel** (formula model) · **Power BI**
(star schema) · pandas/NumPy · scikit-learn · statsmodels · XGBoost · SHAP ·
PCA/K-Means · matplotlib/plotly · Git. Dashboard built as an **interactive web
app** (Mac-native, embeds in my portfolio); aggregates also export to Power BI /
Tableau.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1) data
python src/generate_synthetic.py          # synthetic loans (or add real files per DATA_GUIDE)
python src/00_fetch_macro.py              # macro (bootstrap; --mode fred for exact)
python src/00_fetch_scenarios.py          # Fed 2026 scenarios

# 2) Phase 1: load + target
python src/01_load_duckdb.py --sample-frac 1.0
duckdb data/severely_adverse.duckdb < src/02_default_flag.sql
```

## Project status

- [x] Phase 0 — repo, pinned env, gitignore
- [x] Phase 1 — DuckDB load + default/competing-risk target on **real Freddie
      data**: 350K loans, 19M loan-month rows; 2007 vintage defaults 13.6%,
      COVID cohort ~3.3% — realistic contrast
- [x] Data — real Freddie SFLLD (2005–08, 2017–19) + Fed 2026 scenarios (real)
      + macro (bootstrap)
- [x] Phase 2 — PD model (logistic + XGBoost), out-of-time **Gini 0.66, KS 0.50,
      PR-AUC 0.34**, isotonic-calibrated (Brier 0.175→0.064), SHAP sign-checked
- [x] Phase 3 — macro-sensitive discrete-time hazard (unemployment +0.58,
      current-LTV +0.35, FICO −0.43 — all signs correct)
- [x] Phase 4 — stress projection: **0.61% → 3.28%** cumulative default
      (baseline → severely adverse) over 13 quarters
- [x] Phase 5 — LGD (30%) + Expected Loss: **0.18% → 0.99%** loss ($65M → $352M)
- [x] Phase 6 — interactive web dashboard + Power BI star-schema export
- [x] Multi-tool — SQL / SAS / R / Excel implementations + PCA/K-Means segmentation
- [x] Phase 7 — model card (metrics + stress results filled in)
- [x] Phase 8 — web stress simulator (in `dashboard/index.html`)
- [ ] Deploy — push to GitHub + enable GitHub Pages (final step; you drive auth)

*Built by Vaibhav Sethi — UBC B.Sc. Statistics & Physics.*

# Deploy to GitHub + go live (2 minutes)

Everything is committed and ready. You just run the push from your Mac, where
you're logged into GitHub. Recommended repo name: **`mortgage-stress-testing-engine`**.

## Fastest path — the script

```bash
cd "~/Desktop/Severely Adverse Project/severely-adverse"
bash deploy_github.sh
```

If you have the GitHub CLI (`brew install gh` then `gh auth login`) the script
creates the repo, pushes, and turns on GitHub Pages automatically, then prints
your two links.

## Manual path (no GitHub CLI)

```bash
cd "~/Desktop/Severely Adverse Project/severely-adverse"
rm -rf .git
git init -b main
git add -A
git commit -m "Mortgage stress-testing engine: loan-level PD + Fed 2026 DFAST scenarios"
# create an EMPTY public repo named mortgage-stress-testing-engine at github.com/new, then:
git remote add origin https://github.com/vaibhavsethi01/mortgage-stress-testing-engine.git
git push -u origin main
```
Then on GitHub: **Settings → Pages → Source: `main` / `/ (root)` → Save.**

## Your links (once pushed)

- **Repo (recruiters read this):** `https://github.com/vaibhavsethi01/mortgage-stress-testing-engine`
- **Live dashboard (recruiters click this):** `https://vaibhavsethi01.github.io/mortgage-stress-testing-engine/`
- Add both to your résumé and to `vaibhavsethi01.github.io`.

## What gets published (and what doesn't)

- **Published:** all code (Python/SQL/SAS/R), the web dashboard + simulator,
  charts, aggregate CSVs, model card, README, Excel workbook.
- **Not published (gitignored, per Freddie's license):** the raw loan-level data
  (`data/raw/`), the DuckDB file, and the large derived CSV. This is required —
  Freddie prohibits redistributing the raw data.

## Résumé bullets (real numbers)

> **Mortgage Stress-Testing Engine — Credit Risk under Fed Scenarios** · Python · SQL · SAS · R · DuckDB · XGBoost · SHAP · Power BI
> - Built a loan-level PD model on **350K+ real Freddie Mac mortgages** (19M loan-month records engineered in DuckDB); validated **out-of-time** at **Gini 0.66 / KS 0.50 / PR-AUC 0.34** and isotonic-calibrated (Brier 0.175→0.064), with SHAP reason codes.
> - Fit a **discrete-time hazard model with macro covariates** and projected 13-quarter portfolio Expected Loss under the **Federal Reserve's 2026 baseline vs severely-adverse (CCAR/DFAST)** scenarios — severely-adverse loss **0.99% vs 0.18%** baseline (**5.5×**, $352M vs $65M on a $35B book).
> - Shipped an **interactive web dashboard + stress simulator** and a Power BI star-schema, plus a **model card** for governance; reproduced the PD model in **SAS (PROC LOGISTIC)** and **R (glm)**.

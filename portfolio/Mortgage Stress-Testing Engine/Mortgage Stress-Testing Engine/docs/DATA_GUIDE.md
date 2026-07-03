# Data Guide — getting the real data in place

The pipeline runs **today on synthetic data** (schema-identical to Freddie). To
produce the final, résumé-ready numbers, swap in the real data as below. Nothing
in `src/` changes — only the contents of `data/`.

## 1. Freddie Mac Single-Family Loan-Level Dataset (the loan data)

This is the only step that needs your own (free) account — credentials should
never be shared with anyone, including automated tools.

1. Go to the Freddie Mac Single-Family Loan-Level Dataset portal (search
   "Freddie Mac Single-Family Loan-Level Dataset" → the Clarity Data
   Intelligence site).
2. Register for a **free** account and accept the license. The license permits
   analysis but **prohibits redistributing the raw data** — that is why
   `data/raw/` is gitignored.
3. Download the **standard** dataset (not the "sample"). Start small — the brief
   says build on one quarter first:
   - **Crisis cohort:** `historical_data_2007Q1.zip` (origination + performance)
   - Then add `2005Q1`–`2008Q4` for the full crisis cohort.
   - **COVID cohort:** `2017Q1`–`2019Q4`.
4. Unzip. Each quarter gives two pipe-delimited, header-less files:
   - `historical_data_YYYYQn.txt` (origination — one row per loan)
   - `historical_data_time_YYYYQn.txt` (performance — one row per loan-month)
5. Drop all `.txt` files into **`data/raw/`**.
6. **Verify the column layout** in the current Freddie *User Guide* against
   `src/config.py` (`ORIGINATION_COLUMNS` / `PERFORMANCE_COLUMNS`). Freddie
   changes field order between releases — this is the #1 source of silent bugs.
7. Run the pipeline pointing at real data with a 5% sample:
   ```bash
   python src/01_load_duckdb.py --sample-frac 0.05
   duckdb data/severely_adverse.duckdb < src/02_default_flag.sql
   ```

The full set is hundreds of GB — **do not download all 55M loans.** The cohort +
5% loan-level sample keeps it laptop-friendly while keeping each sampled loan's
full monthly history intact.

## 2. FRED macro series

Free, no login needed for the bootstrap; an API key gives exact values.

```bash
# Bootstrap (approximate, runs now):
python src/00_fetch_macro.py

# Exact (recommended for final): get a free key at
# https://fred.stlouisfed.org/docs/api/api_key.html
export FRED_API_KEY=xxxxxxxx
python src/00_fetch_macro.py --mode fred
```

For HPI, the brief prefers Freddie's **FMHPI** (matches the loan data). Download
the national + state FMHPI CSV from FreddieMac.com, save as
`data/macro/fmhpi.csv`, and wire it into `00_fetch_macro.py` (`--hpi fmhpi`).

## 3. Fed 2026 stress scenarios

Already built into `data/scenarios/fed_2026_scenarios.csv` from the Fed's
published 2026 narrative (see `src/00_fetch_scenarios.py` header for the exact
anchors and source URL). For an exact reproduction, download the Fed's official
Table 3.A / 4.A spreadsheet from the
[2026 Stress Test Scenarios page](https://www.federalreserve.gov/publications/2026-stress-test-scenarios.htm)
and pass `--official-csv`.

## What's synthetic vs. real right now

| Data | Status |
|------|--------|
| Loan-level (origination + performance) | **Synthetic** — schema-identical; replace per §1 |
| FRED macro history | **Bootstrap** (approx. annual averages) — replace per §2 |
| Fed 2026 scenarios | **Real** — built from the Fed's published 2026 narrative |

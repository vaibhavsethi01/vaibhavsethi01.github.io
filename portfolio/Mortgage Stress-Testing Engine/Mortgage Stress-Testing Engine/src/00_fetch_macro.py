"""
00_fetch_macro.py — Acquire FRED macro series for the macro-link phase.

Two modes:
  1. EXACT (recommended for final results): set a free FRED API key and pull the
     real series via fredapi. Get a key at https://fred.stlouisfed.org/docs/api/api_key.html
         export FRED_API_KEY=xxxxxxxx
         python src/00_fetch_macro.py --mode fred
  2. BOOTSTRAP (default, no key needed): writes an approximate quarterly macro
     history (2005Q1-2021Q4) built from published annual averages, so the rest of
     the pipeline runs immediately. Clearly labelled approximate — REPLACE with
     the exact FRED pull before reporting final numbers.

Series pulled in --mode fred:
    UNRATE        US unemployment rate (monthly -> quarterly avg)
    MORTGAGE30US  30-yr fixed mortgage rate (weekly -> quarterly avg)
    GDPC1         real GDP (quarterly; we compute annualized growth)
    CSUSHPISA     Case-Shiller national HPI (monthly -> quarterly). NOTE: the
                  brief prefers Freddie's FMHPI (matches the loan data); FMHPI is
                  a manual CSV download from FreddieMac.com — drop it in
                  data/macro/fmhpi.csv and set --hpi fmhpi to use it instead.

Output (tidy, quarterly):  data/macro/macro_quarterly.csv
    columns: quarter, unemployment_rate, mortgage_rate, gdp_growth, hpi, hpi_yoy
"""
from __future__ import annotations
import argparse
import os
import numpy as np
import pandas as pd

from config import MACRO

# Published annual averages (real history) used for the BOOTSTRAP series. -----
# Sources: BLS (UNRATE), Freddie PMMS (MORTGAGE30US), BEA (GDP), FHFA/Case-Shiller
# style HPI growth. These are ANNUAL approximations for bootstrapping only.
ANN_UNRATE = {2005: 5.1, 2006: 4.6, 2007: 4.6, 2008: 5.8, 2009: 9.3, 2010: 9.6,
              2011: 8.9, 2012: 8.1, 2013: 7.4, 2014: 6.2, 2015: 5.3, 2016: 4.9,
              2017: 4.4, 2018: 3.9, 2019: 3.7, 2020: 8.1, 2021: 5.4}
ANN_MORTGAGE = {2005: 5.9, 2006: 6.4, 2007: 6.3, 2008: 6.0, 2009: 5.0, 2010: 4.7,
                2011: 4.5, 2012: 3.7, 2013: 4.0, 2014: 4.2, 2015: 3.9, 2016: 3.7,
                2017: 4.0, 2018: 4.5, 2019: 3.9, 2020: 3.1, 2021: 3.0}
ANN_HPI_YOY = {2005: 10.0, 2006: 4.0, 2007: -3.0, 2008: -12.0, 2009: -6.0,
               2010: -4.0, 2011: -4.0, 2012: 5.0, 2013: 9.0, 2014: 5.0,
               2015: 6.0, 2016: 6.0, 2017: 6.0, 2018: 5.0, 2019: 4.0,
               2020: 8.0, 2021: 18.0}
ANN_GDP = {2005: 3.5, 2006: 2.8, 2007: 2.0, 2008: 0.1, 2009: -2.6, 2010: 2.7,
           2011: 1.6, 2012: 2.3, 2013: 2.1, 2014: 2.5, 2015: 2.9, 2016: 1.8,
           2017: 2.5, 2018: 3.0, 2019: 2.3, 2020: -2.2, 2021: 5.9}


def _bootstrap() -> pd.DataFrame:
    years = sorted(ANN_UNRATE)
    rows = []
    hpi = 100.0
    for y in years:
        for q in range(1, 5):
            # smooth within-year jitter so quarterly isn't perfectly flat
            adj = (q - 2.5) * 0.05
            hpi *= (1.0 + ANN_HPI_YOY[y] / 100.0) ** 0.25
            rows.append({
                "quarter": f"{y}Q{q}",
                "year": y,
                "unemployment_rate": round(ANN_UNRATE[y] + adj, 2),
                "mortgage_rate": round(ANN_MORTGAGE[y], 2),
                "gdp_growth": round(ANN_GDP[y], 2),
                "hpi": round(hpi, 2),
                "hpi_yoy": ANN_HPI_YOY[y],
            })
    df = pd.DataFrame(rows)
    df["hpi_yoy"] = (df["hpi"] / df["hpi"].shift(4) - 1.0) * 100.0
    df["hpi_yoy"] = df["hpi_yoy"].fillna(df["year"].map(ANN_HPI_YOY))
    return df.drop(columns="year")


def _from_fred() -> pd.DataFrame:
    from fredapi import Fred
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise SystemExit("Set FRED_API_KEY (free) or use default --mode bootstrap.")
    fred = Fred(api_key=key)

    def q(series, how="mean"):
        s = fred.get_series(series)
        s.index = pd.PeriodIndex(s.index, freq="Q")
        return s.groupby(level=0).agg(how)

    unrate = q("UNRATE").rename("unemployment_rate")
    mtg = q("MORTGAGE30US").rename("mortgage_rate")
    hpi = q("CSUSHPISA").rename("hpi")
    gdp = fred.get_series("GDPC1")
    gdp.index = pd.PeriodIndex(gdp.index, freq="Q")
    gdp_growth = (gdp.pct_change() * 400).rename("gdp_growth")  # annualized %

    df = pd.concat([unrate, mtg, gdp_growth, hpi], axis=1).dropna(how="all")
    df["hpi_yoy"] = (df["hpi"] / df["hpi"].shift(4) - 1.0) * 100.0
    df = df.reset_index().rename(columns={"index": "quarter"})
    df["quarter"] = df["quarter"].astype(str).str.replace(r"(\d{4})Q(\d)", r"\1Q\2", regex=True)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["bootstrap", "fred"], default="bootstrap")
    args = ap.parse_args()

    MACRO.mkdir(parents=True, exist_ok=True)
    df = _from_fred() if args.mode == "fred" else _bootstrap()
    out = MACRO / "macro_quarterly.csv"
    df.to_csv(out, index=False)
    tag = "EXACT (FRED)" if args.mode == "fred" else "BOOTSTRAP (approximate)"
    print(f"[{tag}] wrote {len(df)} quarters -> {out}")
    print(df.head(8).to_string(index=False))


if __name__ == "__main__":
    main()

"""
01_load_duckdb.py — Build DuckDB tables from raw Freddie (or synthetic) files.

Reads the pipe-delimited, header-less origination and performance files directly
with DuckDB (which scales to tens of millions of rows on a laptop — we never load
full files into pandas), assigns the documented column names, casts key numeric
types, filters to the sampled cohort, and applies a deterministic loan-level
sample by Loan Sequence Number.

Works identically on synthetic or real data — the schema is the same.

Usage:
  python src/01_load_duckdb.py                 # default: all files in data/raw
  python src/01_load_duckdb.py --sample-frac 0.05
"""
from __future__ import annotations
import argparse
import duckdb

from config import (
    RAW, DB_PATH, ORIGINATION_COLUMNS, PERFORMANCE_COLUMNS,
    LOAN_SAMPLE_FRACTION, RANDOM_STATE,
)


def _names_clause(cols):
    return "{" + ", ".join(f"'{c}': 'VARCHAR'" for c in cols) + "}"


# Recognized file-naming conventions -> (origination glob, performance glob).
# Freddie's SFLLD download uses different names for the annual "sample" files vs
# the quarterly "standard" files; our synthetic generator mimics the standard
# quarterly names. All share the same 32/32 column layout.
SOURCE_GLOBS = {
    # Real SFLLD 50k-loan annual sample files (sample_orig_YYYY / sample_svcg_YYYY)
    "sample":    ("sample_orig_[0-9]*.txt",       "sample_svcg_[0-9]*.txt"),
    # Real SFLLD standard files (annual or quarterly: historical_data_YYYY[Qn])
    "standard":  ("historical_data_[0-9][0-9][0-9][0-9]*.txt", "historical_data_time_[0-9]*.txt"),
    # Our synthetic quarterly files
    "synthetic": ("historical_data_[0-9]*Q[0-9].txt", "historical_data_time_[0-9]*Q[0-9].txt"),
}


def _autodetect_source():
    """Pick the naming convention based on which files are present in RAW."""
    if list(RAW.glob("sample_orig_*.txt")):
        return "sample"
    if list(RAW.glob("historical_data_time_*Q*.txt")):
        return "synthetic"
    if list(RAW.glob("historical_data_time_*.txt")):
        return "standard"
    return "synthetic"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample-frac", type=float, default=LOAN_SAMPLE_FRACTION,
                    help="Fraction of loans to keep, sampled by Loan Sequence Number.")
    ap.add_argument("--source", choices=["auto", "sample", "standard", "synthetic"],
                    default="auto",
                    help="Raw file-naming convention. 'auto' detects it from data/raw.")
    args = ap.parse_args()

    source = _autodetect_source() if args.source == "auto" else args.source
    orig_pat, perf_pat = SOURCE_GLOBS[source]
    orig_glob = str(RAW / orig_pat)
    perf_glob = str(RAW / perf_pat)
    print(f"Source convention: {source}")

    con = duckdb.connect(str(DB_PATH))
    con.execute(f"SET threads TO 4;")

    print(f"Loading origination files: {orig_glob}")
    con.execute(f"""
        CREATE OR REPLACE TABLE origination_raw AS
        SELECT * FROM read_csv('{orig_glob}', delim='|', header=false,
                               columns={_names_clause(ORIGINATION_COLUMNS)},
                               ignore_errors=true);
    """)

    print(f"Loading performance files: {perf_glob}")
    con.execute(f"""
        CREATE OR REPLACE TABLE performance_raw AS
        SELECT * FROM read_csv('{perf_glob}', delim='|', header=false,
                               columns={_names_clause(PERFORMANCE_COLUMNS)},
                               ignore_errors=true);
    """)

    # Deterministic loan-level sample: hash the sequence number, keep a fraction.
    # (Sampling by loan keeps each sampled loan's full monthly history intact.)
    frac_pct = args.sample_frac
    print(f"Applying deterministic {frac_pct:.0%} loan sample (seed={RANDOM_STATE})...")
    con.execute(f"""
        CREATE OR REPLACE TABLE sampled_loans AS
        SELECT loan_sequence_number
        FROM origination_raw
        WHERE (hash(loan_sequence_number || '{RANDOM_STATE}') % 1000000) / 1000000.0
              < {frac_pct};
    """)

    # Typed origination table, filtered to the sample.
    con.execute("""
        CREATE OR REPLACE TABLE origination AS
        SELECT
            o.loan_sequence_number,
            TRY_CAST(o.credit_score AS INTEGER)        AS credit_score,
            o.first_payment_date,
            o.first_time_homebuyer_flag,
            o.maturity_date,
            o.msa,
            TRY_CAST(o.mi_pct AS INTEGER)              AS mi_pct,
            TRY_CAST(o.num_units AS INTEGER)           AS num_units,
            o.occupancy_status,
            TRY_CAST(o.ocltv AS INTEGER)               AS ocltv,
            TRY_CAST(o.odti AS INTEGER)                AS odti,
            TRY_CAST(o.orig_upb AS DOUBLE)             AS orig_upb,
            TRY_CAST(o.oltv AS INTEGER)                AS oltv,
            TRY_CAST(o.orig_interest_rate AS DOUBLE)   AS orig_interest_rate,
            o.channel,
            o.amortization_type,
            o.property_state,
            o.property_type,
            o.loan_purpose,
            TRY_CAST(o.orig_loan_term AS INTEGER)      AS orig_loan_term,
            TRY_CAST(o.num_borrowers AS INTEGER)       AS num_borrowers,
            o.occupancy_status                         AS occupancy,
            CAST(SUBSTR(o.first_payment_date, 1, 4) AS INTEGER) AS vintage_year,
            o.interest_only_flag
        FROM origination_raw o
        SEMI JOIN sampled_loans s USING (loan_sequence_number);
    """)

    # Typed performance table, filtered to the sample.
    con.execute("""
        CREATE OR REPLACE TABLE performance AS
        SELECT
            p.loan_sequence_number,
            TRY_CAST(p.monthly_reporting_period AS INTEGER) AS monthly_reporting_period,
            TRY_CAST(p.current_actual_upb AS DOUBLE)        AS current_actual_upb,
            p.current_delinquency_status,
            TRY_CAST(p.loan_age AS INTEGER)                 AS loan_age,
            p.zero_balance_code,
            TRY_CAST(p.zero_balance_effective_date AS INTEGER) AS zero_balance_effective_date,
            TRY_CAST(p.actual_loss_calculation AS DOUBLE)   AS actual_loss_calculation,
            TRY_CAST(p.net_sales_proceeds AS DOUBLE)        AS net_sales_proceeds,
            TRY_CAST(p.zero_balance_removal_upb AS DOUBLE)  AS zero_balance_removal_upb
        FROM performance_raw p
        SEMI JOIN sampled_loans s USING (loan_sequence_number);
    """)

    n_orig = con.execute("SELECT COUNT(*) FROM origination").fetchone()[0]
    n_perf = con.execute("SELECT COUNT(*) FROM performance").fetchone()[0]
    n_all = con.execute("SELECT COUNT(*) FROM origination_raw").fetchone()[0]
    vintages = con.execute(
        "SELECT vintage_year, COUNT(*) n FROM origination GROUP BY 1 ORDER BY 1"
    ).fetchall()

    con.close()
    print(f"\nLoaded {n_all:,} total loans -> sampled to {n_orig:,} loans "
          f"({n_perf:,} performance rows).")
    print("By vintage:", ", ".join(f"{y}:{n:,}" for y, n in vintages))
    print(f"DuckDB written to {DB_PATH}")


if __name__ == "__main__":
    main()

"""
03_features.py — Assemble the loan-level modelling feature table.

Reads the Phase-1 DuckDB tables (`origination`, `loan_target`), cleans sentinel
codes, derives the origination vintage from the Loan Sequence Number (robust to
first-payment-date roll-over), builds an out-of-time train/test split by vintage,
and writes a tidy modelling table to DuckDB (`features_origination`) and to
outputs/features_origination.parquet for the model script.

Target (Track A, MVP): lifetime `default_flag` (ever 180+ DPD or credit-event
termination) — fully observed on the crisis cohort, which is tracked through the
post-2008 stress window.

Usage:
  python src/03_features.py
"""
from __future__ import annotations
import duckdb

from config import DB_PATH, OUTPUTS, SAMPLE_VINTAGES

# Out-of-time validation split (train on some vintages, test on later ones).
TRAIN_VINTAGES = [2005, 2006, 2017, 2018]
TEST_VINTAGES = [2007, 2008, 2019]


def main():
    OUTPUTS.mkdir(exist_ok=True)
    con = duckdb.connect(str(DB_PATH))

    train_list = ",".join(map(str, TRAIN_VINTAGES))
    test_list = ",".join(map(str, TEST_VINTAGES))

    con.execute(f"""
        CREATE OR REPLACE TABLE features_origination AS
        WITH base AS (
            SELECT
                o.loan_sequence_number,
                -- vintage from the sequence number (F<YY>Q<q>...) is robust to
                -- first-payment roll-over across a calendar year boundary.
                2000 + TRY_CAST(SUBSTR(o.loan_sequence_number, 2, 2) AS INTEGER) AS vintage,
                -- sentinel handling
                CASE WHEN o.credit_score BETWEEN 300 AND 850 THEN o.credit_score END AS fico,
                CASE WHEN o.oltv  BETWEEN 1 AND 998 THEN o.oltv  END AS oltv,
                CASE WHEN o.ocltv BETWEEN 1 AND 998 THEN o.ocltv END AS ocltv,
                CASE WHEN o.odti  BETWEEN 1 AND 65  THEN o.odti  END AS odti,
                o.orig_upb,
                o.orig_interest_rate AS orig_rate,
                CASE WHEN o.mi_pct BETWEEN 0 AND 55 THEN o.mi_pct ELSE 0 END AS mi_pct,
                CASE WHEN o.num_units BETWEEN 1 AND 4 THEN o.num_units END AS num_units,
                CASE WHEN o.num_borrowers BETWEEN 1 AND 10 THEN o.num_borrowers END AS num_borrowers,
                o.first_time_homebuyer_flag AS fthb,
                o.loan_purpose,
                o.occupancy_status AS occupancy,
                o.property_type,
                o.channel,
                o.property_state AS state,
                o.orig_loan_term AS loan_term,
                t.default_flag,
                t.prepaid_flag,
                t.months_to_event,
                t.ead_upb
            FROM origination o
            JOIN loan_target t USING (loan_sequence_number)
        )
        SELECT *,
            CASE WHEN vintage <= 2009 THEN 'crisis' ELSE 'covid' END AS cohort,
            CASE
                WHEN vintage IN ({train_list}) THEN 'train'
                WHEN vintage IN ({test_list})  THEN 'test'
                ELSE 'other'
            END AS split
        FROM base
        WHERE vintage IN ({train_list},{test_list});
    """)

    n = con.execute("SELECT COUNT(*) FROM features_origination").fetchone()[0]
    split = con.execute("""
        SELECT split, COUNT(*) n, SUM(default_flag) n_default,
               ROUND(100.0*AVG(default_flag),2) dflt_pct,
               ROUND(100.0*AVG(CASE WHEN fico IS NULL THEN 1 ELSE 0 END),2) fico_missing_pct
        FROM features_origination GROUP BY 1 ORDER BY 1
    """).fetchdf()

    out = OUTPUTS / "features_origination.parquet"
    con.execute(f"COPY features_origination TO '{out}' (FORMAT PARQUET);")

    print(f"features_origination: {n:,} loans")
    print(split.to_string(index=False))
    print(f"\nTrain vintages {TRAIN_VINTAGES}  ->  Test (out-of-time) {TEST_VINTAGES}")
    print(f"Wrote {out}")
    con.close()


if __name__ == "__main__":
    main()

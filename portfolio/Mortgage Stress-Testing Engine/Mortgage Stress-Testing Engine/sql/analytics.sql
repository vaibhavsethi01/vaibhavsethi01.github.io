-- ============================================================================
-- analytics.sql — Credit-risk analytical SQL pack (DuckDB dialect; largely ANSI,
-- portable to Postgres/BigQuery/Snowflake with minor tweaks).
--
-- Demonstrates: CTEs, window functions, cohort/vintage analysis, conditional
-- aggregation, percentiles, and segment pivots on ~350K loans / 19M loan-month
-- rows. Run after 01_load_duckdb.py + 02_default_flag.sql + 03_features.py:
--     duckdb /tmp/sa_real.duckdb < sql/analytics.sql
-- (tables: origination, performance, loan_target, features_origination)
-- ============================================================================

-- 1) PORTFOLIO SNAPSHOT --------------------------------------------------------
--    Headline counts, default/prepay rates, avg risk drivers.
SELECT
    COUNT(*)                                              AS loans,
    ROUND(100.0 * AVG(t.default_flag), 2)                AS default_rate_pct,
    ROUND(100.0 * AVG(t.prepaid_flag), 2)               AS prepay_rate_pct,
    ROUND(AVG(f.fico))                                   AS avg_fico,
    ROUND(AVG(f.oltv), 1)                                AS avg_oltv,
    ROUND(AVG(f.odti), 1)                                AS avg_dti
FROM loan_target t
JOIN features_origination f USING (loan_sequence_number);

-- 2) VINTAGE DEFAULT TABLE -----------------------------------------------------
--    Classic credit-risk cut: performance by origination vintage.
SELECT
    vintage                                              AS vintage,
    COUNT(*)                                             AS loans,
    SUM(default_flag)                                    AS n_default,
    ROUND(100.0 * AVG(default_flag), 2)                 AS default_rate_pct,
    ROUND(100.0 * AVG(prepaid_flag), 2)                 AS prepay_rate_pct
FROM features_origination
GROUP BY vintage
ORDER BY vintage;

-- 3) RISK RANKING BY FICO x LTV BAND (conditional aggregation + CASE bands) -----
WITH banded AS (
    SELECT
        CASE WHEN fico < 620 THEN '1:<620'
             WHEN fico < 660 THEN '2:620-659'
             WHEN fico < 700 THEN '3:660-699'
             WHEN fico < 740 THEN '4:700-739'
             WHEN fico < 780 THEN '5:740-779'
             ELSE '6:780+' END                           AS fico_band,
        CASE WHEN oltv <= 60 THEN '1:<=60'
             WHEN oltv <= 80 THEN '2:61-80'
             WHEN oltv <= 90 THEN '3:81-90'
             ELSE '4:91+' END                            AS ltv_band,
        default_flag
    FROM features_origination
)
SELECT fico_band, ltv_band,
       COUNT(*)                             AS loans,
       ROUND(100.0*AVG(default_flag), 2)    AS default_rate_pct
FROM banded
GROUP BY fico_band, ltv_band
ORDER BY fico_band, ltv_band;

-- 4) VINTAGE SEASONING CURVES (WINDOW FUNCTION) --------------------------------
--    Cumulative default rate by loan age quarter, per vintage — the curve every
--    credit analyst plots. Uses a running SUM window over loan age.
WITH first_def AS (           -- age (quarters) at first 180+ DPD or credit event
    SELECT
        p.loan_sequence_number,
        CAST(FLOOR(MIN(CASE WHEN TRY_CAST(p.current_delinquency_status AS INT) >= 6
                  OR p.zero_balance_code IN ('02','03','09','15')
                 THEN p.loan_age END) / 3.0) AS INT) AS def_age_q
    FROM performance p
    GROUP BY 1
),
by_age AS (
    SELECT f.vintage, fd.def_age_q AS age_q, COUNT(*) AS n_def
    FROM first_def fd
    JOIN features_origination f USING (loan_sequence_number)
    WHERE fd.def_age_q IS NOT NULL
    GROUP BY 1,2
),
vintage_n AS (
    SELECT vintage, COUNT(*) AS loans FROM features_origination GROUP BY 1
)
SELECT
    b.vintage, b.age_q,
    b.n_def,
    ROUND(100.0 * SUM(b.n_def) OVER (PARTITION BY b.vintage ORDER BY b.age_q)
          / v.loans, 3)                                  AS cum_default_pct
FROM by_age b
JOIN vintage_n v USING (vintage)
WHERE b.age_q BETWEEN 0 AND 20
ORDER BY b.vintage, b.age_q;

-- 5) TOP STATES BY DEFAULT RATE (rank window) ----------------------------------
SELECT state, loans, default_rate_pct,
       RANK() OVER (ORDER BY default_rate_pct DESC) AS risk_rank
FROM (
    SELECT state, COUNT(*) loans, ROUND(100.0*AVG(default_flag),2) default_rate_pct
    FROM features_origination
    GROUP BY state
    HAVING COUNT(*) >= 1000
) s
ORDER BY risk_rank
LIMIT 15;

-- 6) DELINQUENCY MIGRATION SNAPSHOT (performance table, 19M rows) ---------------
--    Distribution of the worst delinquency status ever reached per loan.
WITH worst AS (
    SELECT loan_sequence_number,
           MAX(TRY_CAST(current_delinquency_status AS INT)) AS max_dq
    FROM performance GROUP BY 1
)
SELECT
    CASE WHEN max_dq = 0 THEN '0: current'
         WHEN max_dq BETWEEN 1 AND 2 THEN '1: 30-60 dpd'
         WHEN max_dq BETWEEN 3 AND 5 THEN '2: 90-150 dpd'
         WHEN max_dq >= 6 THEN '3: 180+ dpd (default)'
         ELSE '4: unknown' END                           AS worst_status,
    COUNT(*)                                             AS loans,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)  AS pct_of_book
FROM worst
GROUP BY worst_status
ORDER BY worst_status;

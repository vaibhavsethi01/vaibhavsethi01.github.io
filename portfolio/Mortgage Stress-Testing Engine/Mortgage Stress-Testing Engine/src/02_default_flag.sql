-- 02_default_flag.sql — Define the modelling target + competing risks.
--
-- DEFAULT (credit event) is defined as a loan that EITHER:
--   (a) ever reaches 180+ days delinquent  (Current Loan Delinquency Status >= 6
--       monthly cycles), OR
--   (b) terminates via a credit-event Zero Balance Code:
--          02 = third-party sale, 03 = short sale / charge-off,
--          09 = REO disposition,  15 = note sale.
-- PREPAYMENT (Zero Balance Code 01) is a COMPETING RISK — NOT a default.
--
-- Verify delinquency coding and ZB codes against the current Freddie User Guide
-- before each release. Real-data delinquency status can be non-numeric
-- ('R' = REO, 'XX' = unknown, 'RA' ...); TRY_CAST handles that by yielding NULL.
--
-- Produces one row per loan: default_flag, terminated flag, the calendar quarter
-- and loan age at default-or-censor, and months_to_event for survival framing.

-- Per-loan summary of performance history -----------------------------------
CREATE OR REPLACE TABLE loan_perf_summary AS
WITH dq AS (
    SELECT
        loan_sequence_number,
        MAX(TRY_CAST(current_delinquency_status AS INTEGER)) AS max_dq,
        MAX(loan_age)                                        AS last_age,
        -- credit-event termination
        MAX(CASE WHEN zero_balance_code IN ('02','03','09','15') THEN 1 ELSE 0 END) AS credit_event_zb,
        -- prepayment termination (competing risk)
        MAX(CASE WHEN zero_balance_code = '01' THEN 1 ELSE 0 END)                   AS prepay_zb,
        -- any termination at all
        MAX(CASE WHEN zero_balance_code IS NOT NULL AND zero_balance_code <> ''
                 THEN 1 ELSE 0 END)                                                AS any_termination,
        -- age + period at the terminating (zero-balance) row, if any
        MAX(CASE WHEN zero_balance_code IS NOT NULL AND zero_balance_code <> ''
                 THEN loan_age END)                                                AS term_age,
        MAX(CASE WHEN zero_balance_code IS NOT NULL AND zero_balance_code <> ''
                 THEN zero_balance_effective_date END)                             AS term_period,
        -- first age at which the loan was 180+ DPD
        MIN(CASE WHEN TRY_CAST(current_delinquency_status AS INTEGER) >= 6
                 THEN loan_age END)                                                AS first_180_age,
        -- EAD components: UPB at the terminating row
        MAX(zero_balance_removal_upb)                                              AS ead_upb,
        MAX(actual_loss_calculation)                                              AS actual_loss
    FROM performance
    GROUP BY loan_sequence_number
)
SELECT
    loan_sequence_number,
    max_dq,
    last_age,
    credit_event_zb,
    prepay_zb,
    any_termination,
    term_age,
    term_period,
    first_180_age,
    ead_upb,
    actual_loss,
    -- DEFAULT FLAG: 180+ DPD ever, OR credit-event termination.
    CASE WHEN COALESCE(max_dq, 0) >= 6 OR credit_event_zb = 1 THEN 1 ELSE 0 END AS default_flag
FROM dq;

-- Final target table: one row per loan with target + survival fields ---------
CREATE OR REPLACE TABLE loan_target AS
SELECT
    o.loan_sequence_number,
    o.vintage_year,
    o.first_payment_date,
    s.default_flag,
    s.prepay_zb                                  AS prepaid_flag,
    -- competing-risk outcome label
    CASE
        WHEN s.default_flag = 1 THEN 'default'
        WHEN s.prepay_zb = 1   THEN 'prepaid'
        ELSE 'active_or_censored'
    END                                          AS outcome,
    -- age (months) at the event or at censoring (last observed age)
    COALESCE(s.first_180_age, s.term_age, s.last_age) AS months_to_event,
    s.last_age,
    s.ead_upb,
    s.actual_loss
FROM origination o
LEFT JOIN loan_perf_summary s USING (loan_sequence_number);

-- Quick sanity counts (printed by the runner).
SELECT
    COUNT(*)                                    AS loans,
    SUM(default_flag)                           AS defaults,
    ROUND(100.0 * AVG(default_flag), 2)         AS default_rate_pct,
    SUM(prepaid_flag)                           AS prepaid,
    ROUND(100.0 * AVG(prepaid_flag), 2)         AS prepay_rate_pct
FROM loan_target;

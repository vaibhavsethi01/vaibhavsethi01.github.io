"""
config.py — Central configuration for the Severely Adverse stress-testing engine.

Holds the Freddie Mac Single-Family Loan-Level Dataset column layouts, project
paths, the sampled cohort definition, and modelling constants.

IMPORTANT: Freddie Mac changes its file layout between releases. The column lists
below match the standard dataset layout documented in the User Guide as of the
2024-2025 release (32 origination fields, 32 performance fields). Before trusting
a freshly downloaded vintage, re-verify field order against the current
"File Layout" section of the official User Guide.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"            # Freddie pipe-delimited files (gitignored)
MACRO = DATA / "macro"        # FRED CSVs
SCENARIOS = DATA / "scenarios"  # Fed 2026 supervisory scenarios
MODELS = ROOT / "models"
OUTPUTS = ROOT / "outputs"
DASHBOARD = ROOT / "dashboard"
# DuckDB file. Override with SA_DB_PATH to point at fast local disk (recommended
# if data/ lives on a network/synced drive).
DB_PATH = Path(os.environ.get("SA_DB_PATH", DATA / "severely_adverse.duckdb"))

# Reproducibility — set everywhere.
RANDOM_STATE = 42

# ---------------------------------------------------------------------------
# Sampling / cohort scope  (see PROJECT BRIEF §3a)
# ---------------------------------------------------------------------------
# Crisis cohort: originated 2005-2008, stressed through the 2008-2012 housing
# crash. COVID cohort: originated 2017-2019, stressed through the 2020 shock.
CRISIS_VINTAGES = [2005, 2006, 2007, 2008]
COVID_VINTAGES = [2017, 2018, 2019]
SAMPLE_VINTAGES = CRISIS_VINTAGES + COVID_VINTAGES
# Fraction of loans (by Loan Sequence Number) to keep — keeps it laptop-friendly.
LOAN_SAMPLE_FRACTION = 0.05

# ---------------------------------------------------------------------------
# Freddie Mac ORIGINATION file layout: historical_data_YYYYQn.txt
# pipe-delimited, NO header row. One row per loan.
# ---------------------------------------------------------------------------
ORIGINATION_COLUMNS = [
    "credit_score",                 # 1  FICO at origination (300-850; 9999 = unknown)
    "first_payment_date",           # 2  YYYYMM
    "first_time_homebuyer_flag",    # 3  Y / N / 9
    "maturity_date",                # 4  YYYYMM
    "msa",                          # 5  Metropolitan Statistical Area
    "mi_pct",                       # 6  Mortgage Insurance % (0-55; 999 = N/A)
    "num_units",                    # 7  1-4 (99 = unknown)
    "occupancy_status",             # 8  P / I / S
    "ocltv",                        # 9  Original Combined LTV (999 = unknown)
    "odti",                         # 10 Original DTI ratio (999 = unknown)
    "orig_upb",                     # 11 Original UPB
    "oltv",                         # 12 Original LTV (999 = unknown)
    "orig_interest_rate",           # 13 Original note rate
    "channel",                      # 14 R(etail) / B(roker) / C(orrespondent) / T / 9
    "ppm_flag",                     # 15 Prepayment Penalty Mortgage flag
    "amortization_type",            # 16 FRM / ARM (Product Type)
    "property_state",               # 17 Two-letter state
    "property_type",                # 18 SF / PU / CO / CP / MH / LH
    "postal_code",                  # 19 3-digit prefix + 00
    "loan_sequence_number",         # 20 JOIN KEY  (e.g. F05Q10000001)
    "loan_purpose",                 # 21 P(urchase) / C(ash-out refi) / N(o cash-out refi)
    "orig_loan_term",               # 22 months
    "num_borrowers",                # 23 1-10 (99 = unknown)
    "seller_name",                  # 24
    "servicer_name",                # 25
    "super_conforming_flag",        # 26
    "pre_harp_loan_seq_number",     # 27 Pre-Relief Refinance Loan Sequence Number
    "program_indicator",            # 28 H / F / R / 9
    "harp_indicator",               # 29 Relief Refinance indicator (Y / blank)
    "property_valuation_method",    # 30 1-4 / 9
    "interest_only_flag",           # 31 Y / N
    "mi_cancellation_flag",         # 32 Y / N / 7 / 9
]

# ---------------------------------------------------------------------------
# Freddie Mac PERFORMANCE file layout: historical_data_time_YYYYQn.txt
# pipe-delimited, NO header row. One row per loan per month.
# ---------------------------------------------------------------------------
PERFORMANCE_COLUMNS = [
    "loan_sequence_number",         # 1  JOIN KEY
    "monthly_reporting_period",     # 2  YYYYMM
    "current_actual_upb",           # 3
    "current_delinquency_status",   # 4  0,1,2,...,'RA'; 'R'=REO; XX=unknown
    "loan_age",                     # 5  months since first payment
    "remaining_months_to_maturity", # 6
    "defect_settlement_date",       # 7
    "modification_flag",            # 8  Y / P / blank
    "zero_balance_code",            # 9  01 prepaid, 02 3rd-party sale, 03 short sale,
                                    #    06 repurchase, 09 REO, 15 note sale, 96, 97, 98...
    "zero_balance_effective_date",  # 10 YYYYMM
    "current_interest_rate",        # 11
    "current_deferred_upb",         # 12
    "ddlpi",                        # 13 Due Date of Last Paid Installment
    "mi_recoveries",                # 14 } actual-loss components on disposed loans
    "net_sales_proceeds",           # 15 }
    "non_mi_recoveries",            # 16 }
    "expenses",                     # 17 }
    "legal_costs",                  # 18 }
    "maintenance_preservation_costs",  # 19 }
    "taxes_and_insurance",          # 20 }
    "miscellaneous_expenses",       # 21 }
    "actual_loss_calculation",      # 22 Freddie's computed actual loss
    "modification_cost",            # 23
    "step_modification_flag",       # 24
    "deferred_payment_plan",        # 25
    "estimated_ltv",                # 26 ELTV
    "zero_balance_removal_upb",     # 27
    "delinquent_accrued_interest",  # 28
    "delinquency_due_to_disaster",  # 29 Y / blank
    "borrower_assistance_status",   # 30 F / R / T / blank
    "current_month_modification_cost",  # 31
    "interest_bearing_upb",         # 32
]

# ---------------------------------------------------------------------------
# Default / competing-risk definition  (see PROJECT BRIEF §5 Phase 1.2)
# ---------------------------------------------------------------------------
# Default = ever 180+ days delinquent (status >= 6) OR terminated via a
# credit-event Zero Balance Code. Prepayment (ZB 01) is a COMPETING RISK.
# Verify these codes against the current User Guide before each release.
DEFAULT_DELINQUENCY_THRESHOLD = 6          # 6 monthly cycles = 180+ DPD
CREDIT_EVENT_ZB_CODES = ["02", "03", "09", "15"]  # 3rd-party sale, short sale, REO, note sale
PREPAY_ZB_CODE = "01"                       # competing risk, NOT a default

# Sentinel / missing-value codes used across Freddie fields.
SENTINELS = {
    "credit_score": [9999],
    "mi_pct": [999],
    "num_units": [99],
    "ocltv": [999],
    "odti": [999],
    "oltv": [999],
    "num_borrowers": [99],
}

# Modelling
DEFAULT_HORIZON_MONTHS = 24   # Track A: P(default within 24 months of origination)
PROJECTION_QUARTERS = 9       # Stress horizon (Fed projection window)
ASSUMED_LGD = 0.30            # Fallback LGD if empirical estimate unavailable (§5 Phase 5)

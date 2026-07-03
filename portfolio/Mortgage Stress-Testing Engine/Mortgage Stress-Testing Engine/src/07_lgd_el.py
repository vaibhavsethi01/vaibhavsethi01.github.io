"""
07_lgd_el.py — Loss Given Default + portfolio Expected Loss (Phase 5).

1. Estimate LGD empirically from realized losses on disposed/defaulted loans:
       LGD = total realized loss / total exposure-at-default (UPB at default).
   Falls back to a stated ~30% assumption if the sample's loss fields are sparse.
2. Combine with the Phase-4 stress projection:
       Expected Loss = projected defaulted UPB (EAD) x LGD
       loss rate     = Expected Loss / portfolio UPB at as-of
   under the Fed 2026 baseline vs severely-adverse scenarios.

Outputs: outputs/expected_loss_by_scenario.csv, outputs/stress_loss_headline.json,
         outputs/stress_loss_curve.png
Usage:   python src/07_lgd_el.py
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import DB_PATH, OUTPUTS, ASSUMED_LGD


def estimate_lgd(con):
    """Portfolio LGD from realized losses on defaulted loans; fallback to assumed."""
    row = con.execute("""
        SELECT
            SUM(CASE WHEN actual_loss > 0 THEN actual_loss ELSE 0 END) AS tot_loss,
            SUM(CASE WHEN actual_loss > 0 THEN ead_upb END)            AS tot_ead,
            COUNT(*) FILTER (WHERE default_flag = 1 AND actual_loss > 0) AS n_loss
        FROM loan_target
        WHERE default_flag = 1
    """).fetchone()
    tot_loss, tot_ead, n_loss = row
    lgd_emp = float(tot_loss / tot_ead) if (tot_ead and tot_ead > 0) else None
    # Trust the empirical LGD only with enough disposed loans AND a plausible
    # mortgage severity (>=12%). The 50k-loan annual samples under-populate final
    # disposition/loss fields, so we fall back to the documented ~30% assumption.
    if n_loss and n_loss >= 1000 and lgd_emp and 0.12 <= lgd_emp <= 0.80:
        return lgd_emp, {"method": "empirical", "n_disposed_with_loss": int(n_loss),
                         "lgd": round(lgd_emp, 4)}
    return ASSUMED_LGD, {"method": "assumed_30pct", "lgd": ASSUMED_LGD,
                         "empirical_lgd_unreliable": round(lgd_emp, 4) if lgd_emp else None,
                         "n_disposed_with_loss": int(n_loss or 0),
                         "note": ("realized-loss fields too sparse in the 50k annual "
                                  "sample (<1000 disposed-with-loss); using documented "
                                  "~30% mortgage LGD. Re-estimate on the full Standard "
                                  "dataset for an empirical figure.")}





def main():
    con = duckdb.connect(str(DB_PATH))
    lgd, lgd_info = estimate_lgd(con)
    con.close()
    print(f"LGD ({lgd_info['method']}): {lgd:.1%}")

    proj = pd.read_csv(OUTPUTS / "stress_projection.csv")
    upb0 = proj["portfolio_upb0"].iloc[0]
    proj["expected_loss"] = proj["cumulative_defaulted_upb"] * lgd
    proj["cumulative_loss_rate_pct"] = 100 * proj["expected_loss"] / upb0
    proj.to_csv(OUTPUTS / "expected_loss_by_scenario.csv", index=False)

    summ = {}
    for scenario, g in proj.groupby("scenario"):
        last = g.iloc[-1]
        summ[scenario] = {
            "cumulative_default_rate_pct": round(float(last["cumulative_default_rate_pct"]), 2),
            "cumulative_loss_rate_pct": round(float(last["cumulative_loss_rate_pct"]), 2),
            "expected_loss_usd": int(last["expected_loss"]),
        }
    base = summ["baseline"]; sev = summ["severely_adverse"]
    headline = {
        "portfolio_upb_usd": int(upb0),
        "lgd": lgd_info,
        "horizon_quarters": int(proj["quarter_index"].max()),
        "baseline": base, "severely_adverse": sev,
        "loss_multiple_severe_vs_base": round(sev["cumulative_loss_rate_pct"]
                                              / max(base["cumulative_loss_rate_pct"], 1e-9), 1),
    }
    with open(OUTPUTS / "stress_loss_headline.json", "w") as f:
        json.dump(headline, f, indent=2)

    # ---- cumulative loss-rate curve ---------------------------------------
    plt.figure(figsize=(8, 5))
    for scenario, g in proj.groupby("scenario"):
        label = "Severely adverse" if scenario == "severely_adverse" else "Baseline"
        style = "r-o" if scenario == "severely_adverse" else "b-o"
        plt.plot(g["quarter_index"], g["cumulative_loss_rate_pct"], style, ms=4, label=label)
    plt.xlabel("Projection quarter"); plt.ylabel("Cumulative portfolio loss rate (%)")
    plt.title(f"Projected 13-qtr loss — Fed 2026 scenarios (LGD {lgd:.0%})")
    plt.legend(); plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig(OUTPUTS / "stress_loss_curve.png", dpi=120); plt.close()

    print(f"\nPortfolio ${upb0/1e9:.1f}B | horizon {headline['horizon_quarters']} quarters")
    print(f"  Baseline         default {base['cumulative_default_rate_pct']}%  "
          f"loss {base['cumulative_loss_rate_pct']}%  (${base['expected_loss_usd']/1e6:.0f}M)")
    print(f"  Severely adverse default {sev['cumulative_default_rate_pct']}%  "
          f"loss {sev['cumulative_loss_rate_pct']}%  (${sev['expected_loss_usd']/1e6:.0f}M)")
    print(f"  => severely-adverse loss {headline['loss_multiple_severe_vs_base']}x baseline")


if __name__ == "__main__":
    main()

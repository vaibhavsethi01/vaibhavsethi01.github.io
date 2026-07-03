# Power BI dashboard — build guide

The engine exports a clean **star schema** so you can build the dashboard in
**Power BI** without a Windows machine (Power BI Service runs in the browser).

## Files (this folder)

| File | Grain | Key columns |
|------|-------|-------------|
| `dim_scenario.csv` | 1 row / scenario | `scenario_id`, `scenario_label`, `peak_unemployment_pct`, `hpi_trough_pct` |
| `fact_projection.csv` | scenario × quarter | `scenario_id`, `quarter`, `cumulative_loss_rate_pct`, `cumulative_default_rate_pct`, `expected_loss`, `unemployment_rate` |
| `fact_segment_loss.csv` | scenario × segment | `scenario_id`, `dimension` (fico_band/ltv_band/state/loan_purpose), `segment`, `loss_rate_pct`, `exp_loss`, `upb` |

Regenerate with `python src/10_powerbi_export.py`.

## Build steps

1. **Power BI Service** (app.powerbi.com, free) → *New → Upload* the three CSVs,
   or open **Power BI Desktop** (Windows) → *Get Data → Text/CSV*.
2. **Model view** → relate both fact tables to `dim_scenario` on `scenario_id`
   (one-to-many, single direction).
3. **Measures** (DAX):
   ```DAX
   Loss Rate % = AVERAGE(fact_projection[cumulative_loss_rate_pct])
   Expected Loss = SUM(fact_projection[expected_loss])
   Severe vs Base = 
       DIVIDE(
         CALCULATE([Loss Rate %], dim_scenario[scenario]="severely_adverse"),
         CALCULATE([Loss Rate %], dim_scenario[scenario]="baseline"))
   ```
4. **Report page:**
   - KPI cards: baseline vs severely-adverse loss rate, `Severe vs Base` multiple.
   - Line chart: `quarter` (axis) × `cumulative_loss_rate_pct`, legend =
     `scenario_label`.
   - Bar charts: `fact_segment_loss` filtered to `dimension = "fico_band"` and
     `"ltv_band"`, value = `loss_rate_pct`, slicer on `scenario_label`.
   - Map: `dimension = "state"`, bubble size = `exp_loss`.
5. Add a **scenario slicer** (`dim_scenario[scenario_label]`) so the whole page
   toggles baseline ↔ severely adverse.

The web dashboard (`../index.html`) is the primary, Mac-native deliverable; this
Power BI build is the enterprise-BI equivalent for the résumé keyword.

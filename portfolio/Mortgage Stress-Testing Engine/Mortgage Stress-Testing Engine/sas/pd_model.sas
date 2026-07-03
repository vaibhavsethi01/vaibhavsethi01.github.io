/* ============================================================================
   pd_model.sas — Probability-of-Default model in SAS (credit-risk workflow).

   Reproduces the Python Track-A PD model in SAS: cohort profiling, out-of-time
   logistic regression, and credit-risk validation (c-statistic -> Gini, KS).

   RUN IT FREE: SAS OnDemand for Academics (https://www.sas.com/en_us/software/
   on-demand-for-academics.html) — free for students. Upload
   data/features_origination.csv, adjust the LIBNAME/path, and submit.

   Demonstrates: PROC IMPORT, PROC SQL, PROC FREQ/MEANS, PROC LOGISTIC (with
   out-of-time SCORE + OUTROC), and KS via the ROC output.
   ============================================================================ */

/* ---- 1. Load the modelling table ---------------------------------------- */
proc import datafile="/home/&sysuserid/features_origination.csv"
    out=work.loans dbms=csv replace;
    guessingrows=max;
run;

/* ---- 2. Portfolio profiling (PROC SQL + PROC FREQ) ---------------------- */
proc sql;
    title "Portfolio snapshot";
    select count(*)                          as loans     format=comma10.,
           mean(default_flag)*100            as dflt_pct  format=6.2,
           mean(fico)                        as avg_fico  format=5.0,
           mean(oltv)                        as avg_oltv  format=5.1,
           mean(odti)                        as avg_dti   format=5.1
    from work.loans;
quit;

proc freq data=work.loans;
    title "Default rate by origination vintage";
    tables vintage*default_flag / nocol nopercent;
run;

/* ---- 3. Out-of-time split (train vs later vintages) --------------------- */
data train test;
    set work.loans;
    if split = "train" then output train;
    else if split = "test" then output test;
run;

/* ---- 4. Logistic PD model (interpretable benchmark) -------------------- */
proc logistic data=train outmodel=work.pdmodel;
    class fthb loan_purpose occupancy property_type channel / param=ref;
    model default_flag(event='1') =
          fico oltv ocltv odti orig_rate mi_pct num_units num_borrowers loan_term
          fthb loan_purpose occupancy property_type channel;
    /* score the OUT-OF-TIME test set; OUTROC gives the ROC points for KS */
    score data=test out=work.scored outroc=work.roc_test;
    title "PROC LOGISTIC — PD model (trained on 2005/06/17/18 vintages)";
run;

/* ---- 5. Out-of-time validation: c-statistic (AUC), Gini, KS ------------ */
proc logistic data=test;
    class fthb loan_purpose occupancy property_type channel / param=ref;
    model default_flag(event='1') =
          fico oltv ocltv odti orig_rate mi_pct num_units num_borrowers loan_term
          fthb loan_purpose occupancy property_type channel;
    roc;                       /* prints the c-statistic (AUC); Gini = 2*AUC - 1 */
    ods output ROCAssociation=work.auc_oot;
    title "Out-of-time discrimination (AUC -> Gini = 2*AUC-1)";
run;

/* KS statistic = max( cumulative TPR - cumulative FPR ) from the ROC curve.
   OUTROC gives _SENSIT_ (TPR) and _1MSPEC_ (FPR) at each cutoff.            */
proc sql;
    title "Out-of-time KS statistic";
    select max(_SENSIT_ - _1MSPEC_) as KS_statistic format=6.4
    from work.roc_test;
quit;

/* ---- 6. Score distribution / gains-style deciles ----------------------- */
proc rank data=work.scored out=work.deciles groups=10 descending;
    var P_1;                    /* predicted PD */
    ranks pd_decile;
run;
proc sql;
    title "Default rate by predicted-PD decile (rank ordering check)";
    select pd_decile,
           count(*)               as loans    format=comma8.,
           mean(default_flag)*100 as dflt_pct format=6.2
    from work.deciles
    group by pd_decile
    order by pd_decile;
quit;

"""
04_pd_model.py — Train, evaluate, calibrate, and explain the PD model.

Track A (MVP, binary): P(lifetime default) from origination features.
  * Logistic regression  = interpretable benchmark
  * XGBoost              = challenger
Validated OUT-OF-TIME by vintage (train 2005/06/17/18, test 2007/08/19).
Scored on credit-risk metrics (ROC AUC, Gini, KS, PR-AUC) — not accuracy.
Challenger is isotonic-calibrated; a reliability plot + SHAP explanations saved.

Outputs:
  models/pd_logistic.joblib, models/pd_xgb.joblib, models/pd_xgb_calibrated.joblib
  outputs/pd_metrics.json
  outputs/calibration_curve.png
  outputs/shap_summary.png, outputs/shap_importance.png

Usage:
  python src/04_pd_model.py
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.metrics import roc_auc_score, average_precision_score, roc_curve, brier_score_loss
import xgboost as xgb

from config import OUTPUTS, MODELS, RANDOM_STATE

NUMERIC = ["fico", "oltv", "ocltv", "odti", "orig_upb", "orig_rate",
           "mi_pct", "num_units", "num_borrowers", "loan_term"]
CATEGORICAL = ["fthb", "loan_purpose", "occupancy", "property_type", "channel", "state"]
FEATURES = NUMERIC + CATEGORICAL
TARGET = "default_flag"


def ks_statistic(y_true, y_score):
    fpr, tpr, _ = roc_curve(y_true, y_score)
    return float(np.max(tpr - fpr))


def metrics(y_true, y_score):
    auc = roc_auc_score(y_true, y_score)
    return {
        "roc_auc": round(float(auc), 4),
        "gini": round(2 * auc - 1, 4),
        "ks": round(ks_statistic(y_true, y_score), 4),
        "pr_auc": round(float(average_precision_score(y_true, y_score)), 4),
        "base_rate": round(float(np.mean(y_true)), 4),
    }


def main():
    MODELS.mkdir(exist_ok=True)
    OUTPUTS.mkdir(exist_ok=True)
    df = pd.read_parquet(OUTPUTS / "features_origination.parquet")
    for c in CATEGORICAL:
        df[c] = df[c].fillna("missing").astype(str)

    tr = df[df.split == "train"]
    te = df[df.split == "test"]
    Xtr, ytr = tr[FEATURES], tr[TARGET].astype(int)
    Xte, yte = te[FEATURES], te[TARGET].astype(int)
    print(f"train {len(tr):,} (default {ytr.mean():.2%}) | "
          f"test {len(te):,} (default {yte.mean():.2%})")

    # ---- Logistic benchmark ------------------------------------------------
    pre = ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                          ("sc", StandardScaler())]), NUMERIC),
        ("cat", Pipeline([("imp", SimpleImputer(strategy="constant", fill_value="missing")),
                          ("oh", OneHotEncoder(handle_unknown="ignore", min_frequency=50))]),
         CATEGORICAL),
    ])
    logit = Pipeline([("pre", pre),
                      ("clf", LogisticRegression(max_iter=2000, class_weight="balanced"))])
    logit.fit(Xtr, ytr)
    p_logit = logit.predict_proba(Xte)[:, 1]

    # ---- XGBoost challenger (handles NaN + categoricals natively) -----------
    Xtr_x = Xtr.copy(); Xte_x = Xte.copy()
    for c in CATEGORICAL:
        Xtr_x[c] = Xtr_x[c].astype("category")
        Xte_x[c] = Xte_x[c].astype("category")
    scale_pos = (ytr == 0).sum() / max((ytr == 1).sum(), 1)
    xgb_clf = xgb.XGBClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        reg_lambda=1.0, scale_pos_weight=scale_pos,
        enable_categorical=True, tree_method="hist",
        eval_metric="aucpr", random_state=RANDOM_STATE, n_jobs=4)
    xgb_clf.fit(Xtr_x, ytr)
    p_xgb = xgb_clf.predict_proba(Xte_x)[:, 1]

    # in-sample (train) metrics for overfit check
    p_xgb_tr = xgb_clf.predict_proba(Xtr_x)[:, 1]

    # ---- Isotonic calibration of the challenger ----------------------------
    calib = CalibratedClassifierCV(xgb_clf, method="isotonic", cv=3)
    calib.fit(Xtr_x, ytr)
    p_cal = calib.predict_proba(Xte_x)[:, 1]

    results = {
        "logistic_test_oot": metrics(yte, p_logit),
        "xgboost_train_insample": metrics(ytr, p_xgb_tr),
        "xgboost_test_oot": metrics(yte, p_xgb),
        "xgboost_calibrated_test_oot": metrics(yte, p_cal),
        "brier_uncalibrated": round(float(brier_score_loss(yte, p_xgb)), 5),
        "brier_calibrated": round(float(brier_score_loss(yte, p_cal)), 5),
        "n_train": int(len(tr)), "n_test": int(len(te)),
    }
    with open(OUTPUTS / "pd_metrics.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\n=== OUT-OF-TIME METRICS (test = 2007/08/19) ===")
    for k in ["logistic_test_oot", "xgboost_test_oot", "xgboost_calibrated_test_oot"]:
        m = results[k]
        print(f"{k:32s} AUC={m['roc_auc']}  Gini={m['gini']}  KS={m['ks']}  PR-AUC={m['pr_auc']}")
    print(f"XGB in-sample AUC={results['xgboost_train_insample']['roc_auc']} "
          f"(vs OOT {results['xgboost_test_oot']['roc_auc']} — overfit check)")
    print(f"Brier: {results['brier_uncalibrated']} -> {results['brier_calibrated']} (calibrated)")

    # ---- Calibration / reliability plot ------------------------------------
    frac_pos, mean_pred = calibration_curve(yte, p_cal, n_bins=10, strategy="quantile")
    fu, mu = calibration_curve(yte, p_xgb, n_bins=10, strategy="quantile")
    plt.figure(figsize=(6, 6))
    plt.plot([0, 1], [0, 1], "k--", label="Perfect")
    plt.plot(mu, fu, "o-", alpha=0.6, label="XGB uncalibrated")
    plt.plot(mean_pred, frac_pos, "s-", label="XGB isotonic-calibrated")
    plt.xlabel("Mean predicted PD"); plt.ylabel("Observed default rate")
    plt.title("Calibration (out-of-time test)"); plt.legend(); plt.tight_layout()
    plt.savefig(OUTPUTS / "calibration_curve.png", dpi=120); plt.close()

    # ---- SHAP explainability (XGBoost native pred_contribs) ----------------
    # Use XGBoost's built-in TreeSHAP via pred_contribs — robust to the
    # categorical-dtype clash in the standalone shap library.
    try:
        samp = Xte_x.sample(min(3000, len(Xte_x)), random_state=RANDOM_STATE)
        dm = xgb.DMatrix(samp, enable_categorical=True)
        contribs = xgb_clf.get_booster().predict(dm, pred_contribs=True)
        # last column is the bias term
        sv = contribs[:, :-1]
        feat_names = list(samp.columns)
        mean_abs = np.abs(sv).mean(axis=0)
        order = np.argsort(mean_abs)[::-1]

        # global importance bar chart
        top = order[:15][::-1]
        plt.figure(figsize=(7, 6))
        plt.barh([feat_names[i] for i in top], mean_abs[top], color="#2b6cb0")
        plt.xlabel("Mean |SHAP value|  (log-odds impact on PD)")
        plt.title("PD model — global feature importance (TreeSHAP)")
        plt.tight_layout(); plt.savefig(OUTPUTS / "shap_importance.png", dpi=120); plt.close()

        # sign check: correlation between numeric feature value and its SHAP value
        print("\nTop SHAP features:", ", ".join(feat_names[i] for i in order[:8]))
        signs = {}
        for f in ["fico", "oltv", "ocltv", "odti", "orig_rate"]:
            j = feat_names.index(f)
            vals = pd.to_numeric(samp[f], errors="coerce").to_numpy()
            m = ~np.isnan(vals)
            if m.sum() > 10:
                signs[f] = round(float(np.corrcoef(vals[m], sv[m, j])[0, 1]), 3)
        print("Sign check corr(feature, SHAP)  [expect fico<0; oltv/ocltv/odti/rate>0]:")
        print("  " + "  ".join(f"{k}={v}" for k, v in signs.items()))
        results["shap_sign_check"] = signs
        with open(OUTPUTS / "pd_metrics.json", "w") as f:
            json.dump(results, f, indent=2)
    except Exception as e:
        print(f"SHAP step skipped: {e}")

    joblib.dump(logit, MODELS / "pd_logistic.joblib")
    joblib.dump(xgb_clf, MODELS / "pd_xgb.joblib")
    joblib.dump(calib, MODELS / "pd_xgb_calibrated.joblib")
    print(f"\nSaved models to {MODELS} and metrics/plots to {OUTPUTS}")


if __name__ == "__main__":
    main()

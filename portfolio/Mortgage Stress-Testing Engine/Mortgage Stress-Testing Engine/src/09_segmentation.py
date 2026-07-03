"""
09_segmentation.py — Unsupervised risk segmentation (PCA + K-Means).

Reduces the origination feature space with PCA and clusters the book into
data-driven risk segments with K-Means, then profiles each segment by its
realized default rate. Complements the supervised PD model with an interpretable,
unsupervised view of the portfolio (ties to PCA & clustering coursework).

Outputs:
  outputs/segment_profiles.csv
  outputs/risk_segments.png        (PCA scatter coloured by cluster)
Usage:  python src/09_segmentation.py
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans

from config import OUTPUTS, RANDOM_STATE

NUM = ["fico", "oltv", "ocltv", "odti", "orig_rate", "orig_upb", "loan_term"]
K = 5


def main():
    df = pd.read_parquet(OUTPUTS / "features_origination.parquet")
    X = df[NUM]
    Xi = SimpleImputer(strategy="median").fit_transform(X)
    Xs = StandardScaler().fit_transform(Xi)

    pca = PCA(n_components=3, random_state=RANDOM_STATE)
    pcs = pca.fit_transform(Xs)
    evr = pca.explained_variance_ratio_

    km = KMeans(n_clusters=K, random_state=RANDOM_STATE, n_init=10)
    lab = km.fit_predict(Xs)
    df = df.assign(cluster=lab, pc1=pcs[:, 0], pc2=pcs[:, 1])

    prof = (df.groupby("cluster")
            .agg(loans=("cluster", "size"),
                 avg_fico=("fico", "mean"), avg_oltv=("oltv", "mean"),
                 avg_dti=("odti", "mean"), avg_rate=("orig_rate", "mean"),
                 default_rate_pct=("default_flag", lambda s: 100 * s.mean()))
            .round(2).sort_values("default_rate_pct", ascending=False).reset_index())
    # rank labels from riskiest to safest
    prof["risk_rank"] = range(1, len(prof) + 1)
    prof.to_csv(OUTPUTS / "segment_profiles.csv", index=False)

    print(f"PCA explained variance: PC1 {evr[0]:.1%}, PC2 {evr[1]:.1%}, PC3 {evr[2]:.1%} "
          f"(cum {evr[:3].sum():.1%})")
    print(prof.to_string(index=False))

    # scatter (sample for legibility), coloured by cluster, sized by default rate
    s = df.sample(min(6000, len(df)), random_state=RANDOM_STATE)
    plt.figure(figsize=(8, 6))
    sc = plt.scatter(s.pc1, s.pc2, c=s.cluster, cmap="viridis", s=8, alpha=0.5)
    plt.colorbar(sc, label="Cluster")
    plt.xlabel(f"PC1 ({evr[0]:.0%} var)"); plt.ylabel(f"PC2 ({evr[1]:.0%} var)")
    plt.title("Unsupervised risk segments (PCA + K-Means, k=5)")
    plt.tight_layout(); plt.savefig(OUTPUTS / "risk_segments.png", dpi=120); plt.close()
    print(f"\nWrote {OUTPUTS/'segment_profiles.csv'} and risk_segments.png")


if __name__ == "__main__":
    main()

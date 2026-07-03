# ============================================================================
# glm_crosscheck.R — R cross-check of the Python PD model.
#
# Fits the same out-of-time logistic PD model in R (base glm), validates with
# credit-risk metrics (AUC/Gini via pROC, KS), and checks calibration. Confirms
# the Python and R models agree — a standard model-validation practice.
#
# Run in RStudio:  install.packages(c("pROC")) ; source("R/glm_crosscheck.R")
# ============================================================================

suppressWarnings(suppressMessages({
  have_proc <- requireNamespace("pROC", quietly = TRUE)
}))

d <- read.csv("data/features_origination.csv", stringsAsFactors = TRUE)

# ---- out-of-time split ------------------------------------------------------
train <- d[d$split == "train", ]
test  <- d[d$split == "test",  ]
cat(sprintf("train %d (default %.2f%%) | test %d (default %.2f%%)\n",
            nrow(train), 100*mean(train$default_flag),
            nrow(test),  100*mean(test$default_flag)))

# ---- logistic PD model ------------------------------------------------------
form <- default_flag ~ fico + oltv + ocltv + odti + orig_rate + mi_pct +
                       num_units + num_borrowers + loan_term +
                       fthb + loan_purpose + occupancy + property_type + channel
m <- glm(form, data = train, family = binomial(link = "logit"))
cat("\n--- coefficient signs (key drivers) ---\n")
print(round(coef(m)[c("fico","oltv","ocltv","odti","orig_rate")], 5))

p <- predict(m, newdata = test, type = "response")
y <- test$default_flag

# ---- credit-risk metrics ----------------------------------------------------
ks <- {
  o  <- order(p, decreasing = TRUE)
  cy <- cumsum(y[o]) / sum(y)
  cn <- cumsum(1 - y[o]) / sum(1 - y)
  max(cy - cn)
}

if (have_proc) {
  roc_obj <- pROC::roc(y, p, quiet = TRUE)
  auc <- as.numeric(pROC::auc(roc_obj))
} else {
  # AUC via Mann-Whitney U if pROC unavailable
  r <- rank(p); n1 <- sum(y == 1); n0 <- sum(y == 0)
  auc <- (sum(r[y == 1]) - n1*(n1+1)/2) / (n1*n0)
}

cat(sprintf("\nOut-of-time:  AUC = %.4f | Gini = %.4f | KS = %.4f\n",
            auc, 2*auc - 1, ks))

# ---- calibration (decile reliability) --------------------------------------
dec <- cut(p, quantile(p, probs = seq(0, 1, 0.1)), include.lowest = TRUE)
cal <- aggregate(cbind(pred = p, obs = y), by = list(decile = dec), FUN = mean)
cat("\n--- calibration by predicted-PD decile ---\n")
print(round(cal[, c("pred", "obs")], 4))

cat("\nCompare AUC/Gini above to outputs/pd_metrics.json (Python) — they should match.\n")

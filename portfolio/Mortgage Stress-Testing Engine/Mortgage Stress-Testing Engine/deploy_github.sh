#!/usr/bin/env bash
# ============================================================================
# deploy_github.sh — push this project to the (already-created) GitHub repo.
# Repo: https://github.com/vaibhavsethi01/mortgage-stress-testing-engine
#
# Run on YOUR Mac (folder name with spaces is fine — this cd's to itself):
#     cd ~/Desktop/"Mortgage Stress-Testing Engine"/"Mortgage Stress-Testing Engine"
#     bash deploy_github.sh
#
# The push will ask you to authenticate (GitHub login / token) — that's yours.
# After it finishes: repo Settings -> Pages -> Branch: main / (root) -> Save.
# ============================================================================
set -e
cd "$(dirname "$0")"
REMOTE="https://github.com/vaibhavsethi01/mortgage-stress-testing-engine.git"

rm -rf .git                       # clear the stale partial repo
git init -b main -q
git config user.name  "Vaibhav Sethi"
git config user.email "vbhvsethi@gmail.com"
git add -A
git commit -q -m "Mortgage stress-testing engine: loan-level PD + Fed 2026 DFAST scenarios"
git remote add origin "$REMOTE" 2>/dev/null || git remote set-url origin "$REMOTE"
echo "Pushing $(git ls-files | wc -l | tr -d ' ') files to $REMOTE ..."
git push -u origin main

echo ""
echo "DONE — pushed."
echo "  Repo:  https://github.com/vaibhavsethi01/mortgage-stress-testing-engine"
echo "  Next:  Settings -> Pages -> Source: 'main' / '(root)' -> Save"
echo "  Live:  https://vaibhavsethi01.github.io/mortgage-stress-testing-engine/  (~1 min after Pages)"

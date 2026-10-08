#!/usr/bin/env bash
# Build f1fantasy-eb.zip for Elastic Beanstalk from the last commit.
# `git archive` puts the repo CONTENTS at the zip root (application.py, Procfile, ...),
# never a parent folder, and skips .venv/.env/caches because they are not committed.
# Works in Git Bash on Windows (no `zip` needed).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [ -n "$(git status --porcelain)" ]; then
  echo "WARNING: uncommitted changes are NOT included in the bundle. Commit first if you need them."
fi

OUT=f1fantasy-eb.zip
rm -f "$OUT"
git archive --format=zip -o "$OUT" HEAD

PY=$(command -v python || command -v python3)
"$PY" - "$OUT" <<'EOF'
import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
missing = [f for f in ("application.py", "Procfile", "requirements.txt", ".ebextensions/01_health.config") if f not in names]
assert not missing, f"missing at zip root: {missing}"
print(f"OK: {sys.argv[1]} has {len(names)} entries; application.py, Procfile, requirements.txt at root")
EOF

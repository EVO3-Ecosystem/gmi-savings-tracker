#!/usr/bin/env bash
# One-time GitHub setup after the repo exists: labels, milestones (one per phase) and an issue per phase.
# Usage: OWNER=<github user or org> ./scripts/bootstrap_github.sh   (needs the gh CLI, logged in)
set -euo pipefail
REPO="${OWNER:?set OWNER}/gmi-savings-tracker"
for l in "phase:5319e7" "data:d93f0b" "dashboard:0e8a16" "analytics:1d76db" "infra:cccccc"; do
  gh label create "${l%%:*}" --color "${l##*:}" --repo "$REPO" --force
done
while IFS='|' read -r title gate; do
  gh api "repos/$REPO/milestones" -f title="$title" -f description="Gate: $gate" >/dev/null || true
  gh issue create --repo "$REPO" --title "$title" --label phase --milestone "$title" --body "**Gate:** $gate

See docs/roadmap.md."
done <<'PHASES'
Phase 2 — Database|Every check passes; yearly totals tie to the portal
Phase 3 — Reference data|Match rates at or above the dashboard's master list quality
Phase 4 — Marts & dashboard|Every dashboard file reproduced, or each difference explained
Phase 5 — Analytics|Outputs match the dashboard
Phase 6 — Automate & document|Two clean scheduled runs with no manual steps
PHASES
echo "Done: $REPO"

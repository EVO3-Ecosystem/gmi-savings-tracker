#!/usr/bin/env bash
# One-time GitHub setup: labels, a milestone per remaining phase and an issue per phase (REST API only).
# Already run for EVO3-Ecosystem/gmi-savings-tracker on Oct 29, 2026; safe to re-run (skips what exists).
# Usage: OWNER=EVO3-Ecosystem ./scripts/bootstrap_github.sh   (needs the gh CLI, logged in)
set -uo pipefail
R="repos/${OWNER:?set OWNER}/gmi-savings-tracker"
for l in "phase:5319e7" "data:d93f0b" "dashboard:0e8a16" "analytics:1d76db" "infra:cccccc"; do
  gh api "$R/labels" -f name="${l%%:*}" -f color="${l##*:}" --silent 2>/dev/null || true
done
while IFS='|' read -r title gate; do
  [ -n "$(gh api "$R/issues?state=all&labels=phase" --jq ".[]|select(.title==\"$title\")|.number")" ] && continue
  m=$(gh api "$R/milestones?state=all" --jq ".[]|select(.title==\"$title\")|.number")
  [ -z "$m" ] && m=$(gh api "$R/milestones" -f title="$title" -f description="Gate: $gate" --jq .number)
  gh api "$R/issues" -f title="$title" -f body="**Gate:** $gate

See docs/roadmap.md." -F milestone="$m" -f "labels[]=phase" --jq '"created #\(.number) \(.title)"'
done <<'PHASES'
Phase 2 — Database|Every check passes; yearly totals tie to the portal
Phase 3 — Reference data|Match rates at or above the dashboard's master list quality
Phase 4 — Marts & dashboard|Every dashboard file reproduced, or each difference explained
Phase 5 — Analytics|Outputs match the dashboard
Phase 6 — Automate & document|Two clean scheduled runs with no manual steps
PHASES

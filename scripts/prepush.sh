#!/usr/bin/env bash
# Pre-push check: the same gates as CI (.github/workflows), run locally before every push.
# Each gate's exit code is checked explicitly; output is never piped, so a failure cannot be
# hidden by a pager or a filter. Exit status 0 only if every gate passed.
#
#   bash scripts/prepush.sh            # all gates (as CI)
#   bash scripts/prepush.sh && git push
set -u
cd "$(dirname "$0")/.." || exit 2
# shellcheck source=/dev/null
source scripts/parkiq-env.sh

failed=()
gate() {
  local name="$1"
  shift
  echo "=== $name: $*"
  "$@"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "=== $name FAILED (exit $rc)"
    failed+=("$name")
  else
    echo "=== $name ok"
  fi
}

gate "ruff check" ruff check .
gate "ruff format" ruff format --check .
gate "mypy" mypy --strict parkiq
gate "pytest" python -m pytest -q -m "not network and not arcpy"

if [ "${#failed[@]}" -ne 0 ]; then
  echo "PRE-PUSH CHECK FAILED: ${failed[*]} — do not push"
  exit 1
fi
echo "PRE-PUSH CHECK PASSED"
exit 0

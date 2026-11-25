#!/bin/sh
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: Apache-2.0
#
# Inside the runner container: provision the live systems, then do one thing.
#
#   agenticharvest-run order_fulfillment [--agent] [--keep]
#   agenticharvest-run hire_to_onboard   [--agent] [--keep]
#   agenticharvest-run check             provision and report what each app exposes
#   agenticharvest-run test  [pytest args]   the live-system tests
#   agenticharvest-run shell             a shell with everything installed
set -eu

cd /app
mkdir -p /state/specs /state/out

command="${1:-help}"
[ "$#" -gt 0 ] && shift

case "$command" in
  help|-h|--help)
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  shell)
    exec /bin/sh
    ;;
esac

echo "Provisioning the live systems (examples/systems/setup.py)..."
python examples/systems/setup.py

case "$command" in
  check)
    ;;
  test)
    exec python -m pytest -m live -q -rs "$@"
    ;;
  order_fulfillment|hire_to_onboard)
    # Print the folder as the user sees it on their machine, not the
    # container's /state/out mount (run.sh passes it as AGENTICHARVEST_HOST_OUT).
    host_out="${AGENTICHARVEST_HOST_OUT:-out}/$command"
    # sh has no pipefail: carry the example's exit code past the pipe in a file.
    # "|| code=$?" keeps set -e from ending the group before it is recorded.
    status_file="$(mktemp)"
    { code=0
      python "examples/$command/run.py" --out "/state/out/$command" "$@" 2>&1 || code=$?
      echo "$code" > "$status_file"; } | sed -u "s#/state/out/$command#$host_out#g"
    status="$(cat "$status_file")"
    rm -f "$status_file"
    echo
    echo "Output files (event logs, the mined process model, the agent prompt) are in"
    echo "  $host_out/"
    exit "$status"
    ;;
  *)
    echo "Unknown command '$command'. Try: order_fulfillment, hire_to_onboard, check, test, shell." >&2
    exit 2
    ;;
esac

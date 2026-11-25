#!/bin/sh
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: Apache-2.0
#
# Run an AgenticHarvest cross-system example with nothing installed but Podman or Docker.
#
#   ./run.sh hire_to_onboard [--agent] [--keep]
#   ./run.sh order_fulfillment [--agent] [--keep]
#   ./run.sh check        start and provision the systems, report what they expose
#   ./run.sh test         the live-system tests, inside the runner
#   ./run.sh shell        a shell in the runner, everything installed
#   ./run.sh stop         stop the systems (data is kept)
#   ./run.sh reset        stop and delete all data
#
# --agent needs an OpenAI-compatible endpoint: export API_BASE, API_KEY, and
# MODEL first, or put them in a .env file next to this script or in the repo root.
set -eu

here="$(cd "$(dirname "$0")" && pwd)"

# Find the agenticharvest source. Inside an agenticharvest checkout this folder is
# examples/systems. Cloned on its own, this repo fetches agenticharvest (with the
# examples and this stack as its submodules) into ./.agenticharvest and runs from
# there. AGENTICHARVEST_REPO and AGENTICHARVEST_REF choose what is fetched.
is_agenticharvest() { [ -f "$1/pyproject.toml" ] && grep -q '^name = "agenticharvest"' "$1/pyproject.toml"; }
if is_agenticharvest "$here/../.."; then
  root="$(cd "$here/../.." && pwd)"
else
  root="$here/.agenticharvest"
  if ! is_agenticharvest "$root"; then
    command -v git >/dev/null 2>&1 || { echo "git is needed to fetch agenticharvest." >&2; exit 1; }
    repo="${AGENTICHARVEST_REPO:-https://github.com/IBM/agenticharvest.git}"
    echo "Fetching agenticharvest ($repo, ${AGENTICHARVEST_REF:-main}) into $root ..."
    git clone --depth 1 --recurse-submodules --shallow-submodules \
      --branch "${AGENTICHARVEST_REF:-main}" "$repo" "$root"
  fi
fi
export AGENTICHARVEST_ROOT="$root"
# Always use the stack definition inside that checkout, so the source and the
# compose file match.
here="$root/examples/systems"

# Podman or Docker, whichever is here.
if command -v podman >/dev/null 2>&1; then
  engine=podman
elif command -v docker >/dev/null 2>&1; then
  engine=docker
else
  cat >&2 <<'EOF'
Neither Podman nor Docker is installed. Install one, then run this again:
  macOS    https://podman.io/docs/installation   (then: podman machine init && podman machine start)
  Windows  https://podman.io/docs/installation   (or Docker Desktop)
  Linux    sudo apt install podman   /   sudo dnf install podman
EOF
  exit 1
fi
if ! $engine info >/dev/null 2>&1; then
  echo "$engine is installed but not running." >&2
  [ "$engine" = podman ] && echo "Start it with: podman machine start" >&2
  exit 1
fi
compose() { $engine compose -f "$here/compose.yaml" "$@"; }

# LLM settings for --agent: the environment wins, then a .env in the folder the
# user ran from (an example's own run.sh passes it as AGENTICHARVEST_CALLER_DIR), next
# to this script, or in the agenticharvest root.
for file in "${AGENTICHARVEST_CALLER_DIR:-$PWD}/.env" "$here/.env" "$root/.env"; do
  [ -f "$file" ] || continue
  for key in API_BASE API_KEY MODEL; do
    eval "current=\${$key:-}"
    if [ -z "$current" ]; then
      value="$(sed -n "s/^$key=//p" "$file" | tail -n 1 | sed 's/^["'\'']//; s/["'\'']$//')"
      [ -n "$value" ] && export "$key=$value"
    fi
  done
done

command="${1:-help}"
[ "$#" -gt 0 ] && shift

case "$command" in
  help|-h|--help)
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  stop)
    compose --profile runner stop
    exit 0
    ;;
  reset)
    compose --profile runner down -v
    exit 0
    ;;
esac

# The examples' output goes to ./out next to the run.sh the user ran.
export AGENTICHARVEST_OUT="${AGENTICHARVEST_OUT:-${AGENTICHARVEST_CALLER_DIR:-$PWD}/out}"
mkdir -p "$AGENTICHARVEST_OUT"

echo "Starting the live systems with $engine (the first start pulls ~2 GB and takes a few minutes)..."
compose up -d directus keycloak odoo-db odoo
compose --profile runner build runner
exec $engine compose -f "$here/compose.yaml" --profile runner run --rm runner "$command" "$@"

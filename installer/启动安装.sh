#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MATERIAL_MATCHER_BUNDLE_ROOT="${MATERIAL_MATCHER_BUNDLE_ROOT:-$SCRIPT_DIR}"
exec "$SCRIPT_DIR/install_wizard.sh"

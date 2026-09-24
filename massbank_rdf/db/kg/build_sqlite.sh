#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

cd "${APP_ROOT}"

python massbank_rdf/db/kg/build_sqlite.py --batch-size 5 --resume "$@"

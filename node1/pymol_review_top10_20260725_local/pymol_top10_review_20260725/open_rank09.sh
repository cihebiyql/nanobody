#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec pymol "pymol/review_rank09.pml"

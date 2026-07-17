#!/usr/bin/env bash
set -Eeuo pipefail
umask 022
readonly ROOT=/data1/qlyu/projects/pvrig_candidate7087_node1_fastqc_census_v1_20260716
readonly WORKER="$ROOT/run_candidate7087_fastqc_census_node1.py"
readonly FREEZE="$ROOT/IMPLEMENTATION_FREEZE.json"
readonly PREREG="$ROOT/inputs/phase2_candidate7087_node1_fastqc_census_v1_preregistration.json"
readonly RUNTIME_MANIFEST=/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716/runtime_closure/RUNTIME_MANIFEST.json
readonly PYTHON=/data1/qlyu/software/envs/vhh-eval/bin/python
readonly EXPECTED_WORKER_SHA=f9d85634d957a2df4fc660b6acd175a26d4ab82613eeb65ce30f87fb224f7b3b
readonly EXPECTED_FREEZE_SHA=3d5068041180756cb5fde721418ac05047883b8c55352ebfd156cdcc579423cd
readonly EXPECTED_PREREG_SHA=0112cd909702d85f760ebef92b7bc1ab5db83705c5c8546e45cdfe21b08c175b
readonly EXPECTED_FASTA_SHA=82d89ca0b35f38e87a26b9ccca9ed97ce64255db33250ddb694fe2a072494b88
readonly EXPECTED_LINEAGE_SHA=2000415243a044131e1e12704d3a1e0f31b5b84d790d14fdeee4af4db5aea777
readonly EXPECTED_RUNTIME_SHA=603985f4af78151bbdb0b8ed8a3f2de8448f3bca57b011bbc2585a4754a6cc5d
mkdir -p "$ROOT/status" "$ROOT/logs"
exec 9>"$ROOT/status/census.lock"
flock -n 9 || { echo '7087 census already active' >&2; exit 75; }
[[ $(sha256sum "$WORKER" | awk '{print $1}') == "$EXPECTED_WORKER_SHA" ]]
[[ $(sha256sum "$FREEZE" | awk '{print $1}') == "$EXPECTED_FREEZE_SHA" ]]
[[ $(sha256sum "$PREREG" | awk '{print $1}') == "$EXPECTED_PREREG_SHA" ]]
[[ $(sha256sum "$ROOT/inputs/candidate7087.fasta" | awk '{print $1}') == "$EXPECTED_FASTA_SHA" ]]
[[ $(sha256sum "$ROOT/inputs/candidate7087_lineage.tsv" | awk '{print $1}') == "$EXPECTED_LINEAGE_SHA" ]]
[[ $(sha256sum "$RUNTIME_MANIFEST" | awk '{print $1}') == "$EXPECTED_RUNTIME_SHA" ]]
echo $$ >"$ROOT/status/launcher.pid"
set +e
"$PYTHON" "$WORKER" >>"$ROOT/logs/census.log" 2>&1
rc=$?
set -e
rm -f "$ROOT/status/launcher.pid"
exit "$rc"

#!/usr/bin/env bash
set -Eeuo pipefail

# Build target-conditioned sequence-only binding priors on node1.
# Usage: run_binding_prior_prefilter_node1.sh candidates.fasta pvrig.fasta outdir
# The output table is intended for vhh-large-scale-screen --binder-summary.

CANDIDATES="${1:?candidate FASTA is required}"
ANTIGEN="${2:?single-record PVRIG FASTA is required}"
OUTDIR="${3:?output directory is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEEPNANO_ROOT="${DEEPNANO_ROOT:-/data/qlyu/software/DeepNano}"
NANOBIND_ROOT="${NANOBIND_ROOT:-/data1/qlyu/software/NanoBind}"
DEEPNANO_GPU="${DEEPNANO_GPU:-1}"
NANOBIND_GPU="${NANOBIND_GPU:-2}"
AFFINITY_GPU="${AFFINITY_GPU:-3}"
RUN_AFFINITY="${RUN_AFFINITY:-0}"
NABP_BERT_CSV="${NABP_BERT_CSV:-}"

mkdir -p "$OUTDIR/prepared" "$OUTDIR/logs"
CANDIDATES="$(readlink -f "$CANDIDATES")"
ANTIGEN="$(readlink -f "$ANTIGEN")"
OUTDIR="$(readlink -f "$OUTDIR")"

python3 - "$CANDIDATES" "$ANTIGEN" "$OUTDIR/prepared" <<'PY'
import sys
from pathlib import Path

def read_fasta(path):
    records=[]; name=None; parts=[]
    for raw in Path(path).read_text().splitlines():
        line=raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if name is not None:
                records.append((name, "".join(parts)))
            name=line[1:].split()[0]; parts=[]
        else:
            parts.append(line)
    if name is not None:
        records.append((name, "".join(parts)))
    return records

candidates=read_fasta(sys.argv[1])
antigens=read_fasta(sys.argv[2])
if not candidates:
    raise SystemExit("candidate FASTA is empty")
if len(antigens) != 1:
    raise SystemExit(f"expected exactly one antigen record, found {len(antigens)}")
if len({name for name, _ in candidates}) != len(candidates):
    raise SystemExit("candidate FASTA contains duplicate IDs")
ag_id, ag_seq=antigens[0]
out=Path(sys.argv[3]); out.mkdir(parents=True, exist_ok=True)

deep_lines=[]
for name, seq in candidates:
    deep_lines += [f">{name}", seq]
deep_lines += [f">{ag_id}", ag_seq]
(out/"deepnano_input.fasta").write_text("\n".join(deep_lines)+"\n")
(out/"deepnano_pairs.tsv").write_text(
    "Nanobody-ID\tAntigen-ID\n" +
    "".join(f"{name}\t{ag_id}\n" for name, _ in candidates)
)

nb_lines=[]; ag_lines=[]
for name, seq in candidates:
    nb_lines += [f">{name}", seq]
    ag_lines += [f">{ag_id}", ag_seq]
(out/"nanobind_nanobodies.fasta").write_text("\n".join(nb_lines)+"\n")
(out/"nanobind_antigens.fasta").write_text("\n".join(ag_lines)+"\n")
print(f"prepared_candidates={len(candidates)} antigen_id={ag_id}")
PY

run_deepnano() {
  cd "$DEEPNANO_ROOT"
  /usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' \
    -o "$OUTDIR/logs/deepnano.time" \
    env GPU="$DEEPNANO_GPU" MODEL=1 ESM2=8M \
    ./run_deepnano_predict.sh \
      "$OUTDIR/prepared/deepnano_input.fasta" \
      "$OUTDIR/prepared/deepnano_pairs.tsv" \
      "$OUTDIR/deepnano_binding.csv" \
      >"$OUTDIR/logs/deepnano.stdout" 2>"$OUTDIR/logs/deepnano.stderr"
}

run_nanobind_seq() {
  cd "$NANOBIND_ROOT"
  /usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' \
    -o "$OUTDIR/logs/nanobind_seq.time" \
    env GPU="$NANOBIND_GPU" MODE=seq \
    ./run_nanobind_predict.sh \
      "$OUTDIR/prepared/nanobind_nanobodies.fasta" \
      "$OUTDIR/prepared/nanobind_antigens.fasta" \
      "$OUTDIR/nanobind_binding.csv" \
      >"$OUTDIR/logs/nanobind_seq.stdout" 2>"$OUTDIR/logs/nanobind_seq.stderr"
}

run_deepnano & deepnano_pid=$!
run_nanobind_seq & nanobind_pid=$!
deepnano_rc=0; nanobind_rc=0
wait "$deepnano_pid" || deepnano_rc=$?
wait "$nanobind_pid" || nanobind_rc=$?
if (( deepnano_rc != 0 || nanobind_rc != 0 )); then
  echo "binding model failure: DeepNano=$deepnano_rc NanoBind=$nanobind_rc" >&2
  exit 1
fi

affinity_args=()
if [[ "$RUN_AFFINITY" == "1" ]]; then
  cd "$NANOBIND_ROOT"
  /usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' \
    -o "$OUTDIR/logs/nanobind_affinity.time" \
    env GPU="$AFFINITY_GPU" MODE=affi \
    ./run_nanobind_predict.sh \
      "$OUTDIR/prepared/nanobind_nanobodies.fasta" \
      "$OUTDIR/prepared/nanobind_antigens.fasta" \
      "$OUTDIR/nanobind_affinity.csv" \
      >"$OUTDIR/logs/nanobind_affinity.stdout" \
      2>"$OUTDIR/logs/nanobind_affinity.stderr"
  affinity_args=(--nanobind-affinity "$OUTDIR/nanobind_affinity.csv")
fi

nabp_args=()
if [[ -n "$NABP_BERT_CSV" ]]; then
  nabp_args=(--nabp-bert "$NABP_BERT_CSV")
fi

python3 "$SCRIPT_DIR/build_binding_prior_table.py" \
  "$CANDIDATES" \
  -o "$OUTDIR/binding_prior_table.tsv" \
  --deepnano "$OUTDIR/deepnano_binding.csv" \
  --nanobind-seq "$OUTDIR/nanobind_binding.csv" \
  "${affinity_args[@]}" \
  "${nabp_args[@]}"

python3 - "$CANDIDATES" "$ANTIGEN" "$OUTDIR" "$RUN_AFFINITY" <<'PY'
import csv, hashlib, json, sys, time
from pathlib import Path

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

candidates, antigen, outdir, run_affinity=sys.argv[1:]
out=Path(outdir)
with (out/"binding_prior_table.tsv").open() as handle:
    rows=list(csv.DictReader(handle, delimiter="\t"))
payload={
    "schema_version": 1,
    "created_epoch": time.time(),
    "status": "PASS",
    "candidate_fasta": candidates,
    "candidate_fasta_sha256": sha(candidates),
    "antigen_fasta": antigen,
    "antigen_fasta_sha256": sha(antigen),
    "candidate_count": len(rows),
    "deepnano_available": sum(bool(r["deepnano_binding_prior"]) for r in rows),
    "nanobind_available": sum(bool(r["nanobind_binding_prior"]) for r in rows),
    "nanobind_affinity_available": sum(bool(r["nanobind_affinity_range"]) for r in rows),
    "run_affinity": run_affinity == "1",
    "scientific_boundary": "weak binding priors only; not Kd, IC50, or blocking evidence",
}
(out/"RUN_RECEIPT.json").write_text(json.dumps(payload, indent=2, sort_keys=True)+"\n")
print(json.dumps(payload, sort_keys=True))
PY

echo "Wrote $OUTDIR/binding_prior_table.tsv"

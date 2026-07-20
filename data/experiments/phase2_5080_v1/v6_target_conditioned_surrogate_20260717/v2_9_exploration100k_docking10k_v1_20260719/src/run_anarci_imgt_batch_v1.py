#!/usr/bin/env python3
"""Run ANARCI/IMGT in parallel chunks and emit a candidate-complete ledger."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pandas as pd


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def clean_position(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    return "" if text in {"", "-", ".", "nan"} else text


def cdr_from_row(row: pd.Series, lo: int, hi: int) -> str:
    # ANARCI emits residue columns in biological sequence order, including
    # insertion codes. Re-sorting column names lexicographically corrupts
    # insertion-rich CDRs (for example, 111, 111A, ...).
    values = []
    for column in row.index:
        text = str(column)
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            continue
        position = int(digits)
        if lo <= position <= hi:
            values.append(clean_position(row[column]))
    return "".join(values)


def run_chunk(index: int, frame: pd.DataFrame, root: Path, python: Path, script: Path, env_bin: Path) -> dict[str, object]:
    chunk = root / f"chunk_{index:04d}"
    chunk.mkdir(parents=True, exist_ok=False)
    fasta = chunk / "input.fasta"
    with fasta.open("w") as handle:
        for row in frame.itertuples(): handle.write(f">{row.candidate_id}\n{row.sequence}\n")
    output_prefix = chunk / "anarci"
    log = chunk / "anarci.log"
    env = dict(os.environ); env["PATH"] = f"{env_bin}:{env.get('PATH','')}"
    with log.open("w") as handle:
        completed = subprocess.run([str(python), str(script), "-i", str(fasta), "-o", str(output_prefix), "--scheme", "imgt", "--csv"], stdout=handle, stderr=subprocess.STDOUT, env=env)
    output = chunk / "anarci_H.csv"
    return {"index": index, "returncode": completed.returncode, "input_rows": len(frame), "output": str(output), "log": str(log)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-tsv", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--anarci-python", type=Path, required=True)
    ap.add_argument("--anarci-script", type=Path, required=True)
    ap.add_argument("--env-bin", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--chunk-size", type=int, default=625)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    table = pd.read_csv(args.input_tsv, sep="\t", usecols=["candidate_id", "sequence"], dtype=str)
    if table.candidate_id.duplicated().any(): raise RuntimeError("duplicate_candidate_id")
    chunks = [table.iloc[i : i + args.chunk_size].copy() for i in range(0, len(table), args.chunk_size)]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_chunk, i, frame, args.output_dir, args.anarci_python, args.anarci_script, args.env_bin) for i, frame in enumerate(chunks)]
        for future in concurrent.futures.as_completed(futures): results.append(future.result())
    (args.output_dir / "chunk_results.json").write_text(json.dumps(sorted(results, key=lambda x: x["index"]), indent=2) + "\n")

    observed: dict[str, dict[str, object]] = {}
    for result in results:
        output = Path(result["output"])
        if result["returncode"] != 0 or not output.is_file():
            continue
        frame = pd.read_csv(output)
        for _, row in frame.iterrows():
            candidate = str(row["Id"])
            if candidate in observed: raise RuntimeError(f"duplicate_anarci_result:{candidate}")
            cdr1, cdr2, cdr3 = cdr_from_row(row, 27, 38), cdr_from_row(row, 56, 65), cdr_from_row(row, 105, 117)
            pos1, pos128 = clean_position(row.get("1", "")), clean_position(row.get("128", ""))
            chain = str(row.get("chain_type", ""))
            passed = chain == "H" and bool(pos1) and bool(pos128) and bool(cdr1 and cdr2 and cdr3)
            observed[candidate] = {
                "candidate_id": candidate, "anarci_imgt_pass": str(passed).lower(),
                "anarci_chain_type": chain, "anarci_hmm_species": row.get("hmm_species", ""),
                "anarci_e_value": row.get("e-value", ""), "anarci_score": row.get("score", ""),
                "anarci_position1_present": str(bool(pos1)).lower(), "anarci_position128_present": str(bool(pos128)).lower(),
                "anarci_cdr1": cdr1, "anarci_cdr2": cdr2, "anarci_cdr3": cdr3,
                "anarci_failure_reason": "" if passed else "chain_or_imgt_boundary_or_cdr_incomplete",
            }
    ledger = []
    for candidate in table.candidate_id:
        ledger.append(observed.get(candidate, {
            "candidate_id": candidate, "anarci_imgt_pass": "false", "anarci_chain_type": "", "anarci_hmm_species": "",
            "anarci_e_value": "", "anarci_score": "", "anarci_position1_present": "false", "anarci_position128_present": "false",
            "anarci_cdr1": "", "anarci_cdr2": "", "anarci_cdr3": "", "anarci_failure_reason": "no_anarci_H_result",
        }))
    ledger_frame = pd.DataFrame(ledger)
    ledger_path = args.output_dir / "anarci_imgt_ledger.tsv"
    ledger_frame.to_csv(ledger_path, sep="\t", index=False)
    summary = {
        "schema_version": "pvrig_v2_9_anarci_imgt_batch_v1", "status": "PASS_BATCH_COMPLETE",
        "input_rows": len(table), "result_rows": len(ledger_frame),
        "anarci_imgt_pass": int((ledger_frame.anarci_imgt_pass == "true").sum()),
        "anarci_imgt_fail": int((ledger_frame.anarci_imgt_pass != "true").sum()),
        "input_sha256": sha_file(args.input_tsv), "ledger_sha256": sha_file(ledger_path),
        "chunks": len(chunks), "workers": args.workers,
    }
    (args.output_dir / "ANARCI_SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

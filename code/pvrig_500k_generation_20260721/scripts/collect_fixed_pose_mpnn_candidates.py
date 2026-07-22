#!/usr/bin/env python3
"""Collect, fast-QC, exact-deduplicate and balance fixed-pose ProteinMPNN outputs."""

from __future__ import annotations

import argparse
import csv
import functools
import gzip
import hashlib
import importlib.util
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("cpu_generator", HERE / "generate_local_cpu_routes.py")
GEN = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(GEN)

AA3 = {
    "ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q","GLU":"E","GLY":"G",
    "HIS":"H","ILE":"I","LEU":"L","LYS":"K","MET":"M","PHE":"F","PRO":"P","SER":"S",
    "THR":"T","TRP":"W","TYR":"Y","VAL":"V",
}
TAG_RE = re.compile(r"(.+)_dldesign_(\d+)\.pdb$")


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_fasta(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    name = ""; chunks: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            if name: records[name] = "".join(chunks)
            name=line[1:].split()[0]; chunks=[]
        else: chunks.append(line.strip())
    if name: records[name] = "".join(chunks)
    return records


def parse_pdb(path: Path) -> tuple[str, dict[str, str], list[str]]:
    residues: dict[tuple[int, str], str] = {}
    labels: dict[str, set[int]] = {"H1":set(),"H2":set(),"H3":set()}
    errors: list[str] = []
    for line in path.read_text(encoding="ascii", errors="replace").splitlines():
        if line.startswith("ATOM") and len(line)>=27 and line[21]=="H" and line[12:16].strip()=="CA":
            if line[16] not in (" ","A"): continue
            try: number=int(line[22:26])
            except ValueError: errors.append("malformed_residue_number"); continue
            insertion=line[26].strip()
            aa=AA3.get(line[17:20].strip())
            if aa is None: errors.append("unsupported_residue")
            else: residues.setdefault((number,insertion),aa)
        elif line.startswith("REMARK PDBinfo-LABEL:"):
            parts=line.split()
            if len(parts)>=4 and parts[-1] in labels:
                try: labels[parts[-1]].add(int(parts[-2]))
                except ValueError: errors.append("malformed_cdr_label")
    sequence="".join(residues[key] for key in sorted(residues))
    cdrs={
        name:"".join(residues[key] for key in sorted(residues) if key[0] in numbers)
        for name,numbers in labels.items()
    }
    if not 95<=len(sequence)<=160: errors.append("sequence_length_outside_95_160")
    if any(not cdr for cdr in cdrs.values()): errors.append("missing_cdr_label")
    if any(cdr and sequence.count(cdr)!=1 for cdr in cdrs.values()): errors.append("cdr_not_unique_in_H_sequence")
    return sequence,cdrs,sorted(set(errors))


def write_gzip_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with gzip.open(path,"wt",encoding="utf-8",newline="",compresslevel=1) as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""): digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root",type=Path,required=True)
    parser.add_argument("--target",type=int,default=75_000)
    args=parser.parse_args()
    root=args.run_root.resolve(); tasks=read_tsv(root/"inputs/fixed_pose_mpnn_tasks.tsv")
    task_by_pose={row["pose_id"]:row for row in tasks}
    positive_cdr_rows=read_tsv(root/"inputs/positive11_cdr_imgt.tsv")
    positives={row["record_id"]:{"cdr1":row["cdr1"],"cdr2":row["cdr2"],"cdr3":row["cdr3"]} for row in positive_cdr_rows}
    positive_sequences=read_fasta(root/"inputs/positive11.fasta")
    parent_sequence={pose:positive_sequences[row["source_candidate_id"]] for pose,row in task_by_pose.items()}
    rows: list[dict[str,object]]=[]
    outputs=sorted(root.glob("generation/workers/*/outputs/*_dldesign_*.pdb"))
    expected=sum(int(row["seqs_per_pose"]) for row in tasks)
    if len(outputs)!=expected: raise ValueError(f"expected {expected} outputs, found {len(outputs)}")
    output_counts: Counter[str]=Counter()
    for path in outputs:
        match=TAG_RE.fullmatch(path.name)
        if match is None: raise ValueError(f"unknown output tag: {path}")
        output_counts[match.group(1)]+=1
    for task in tasks:
        if output_counts[task["pose_id"]]!=int(task["seqs_per_pose"]):
            raise ValueError(
                f"{task['pose_id']}: expected {task['seqs_per_pose']} outputs, found {output_counts[task['pose_id']]}"
            )
    for path in outputs:
        match=TAG_RE.fullmatch(path.name)
        if match is None or match.group(1) not in task_by_pose: raise ValueError(f"unknown output tag: {path}")
        pose_id,index=match.group(1),int(match.group(2)); task=task_by_pose[pose_id]
        sequence,cdr_labels,errors=parse_pdb(path)
        cdrs={"cdr1":cdr_labels["H1"],"cdr2":cdr_labels["H2"],"cdr3":cdr_labels["H3"]}
        qc=GEN.fast_qc(sequence,cdrs,parent_sequence[pose_id],positives) if not errors else {
            "fast_qc_status":"FAIL","fast_qc_reasons":"|".join(errors)
        }
        digest=hashlib.sha256(sequence.encode()).hexdigest()
        rows.append({
            "raw_instance_id":f"{pose_id}__mpnn{index:04d}",
            "candidate_id":f"P500K__FIXED_POSE_MPNN__{digest[:16].upper()}",
            "route_id":"fixed_pose_mpnn","design_method":"RFantibody_ProteinMPNN_fixed_positive_pose",
            "generator":"rfantibody_proteinmpnn_interface_design","generator_version":"local_20260721",
            "pose_id":pose_id,"source_candidate_id":task["source_candidate_id"],
            "source_molecule_name":task["source_molecule_name"],"source_pose_rank":task["source_pose_rank"],
            "normalized_pose_relpath":task["normalized_pose_relpath"],
            "normalized_pose_sha256":task["normalized_pose_sha256"],"mpnn_index":index,
            "temperature":task["temperature"],"designed_regions":"cdr1,cdr2,cdr3",
            "target_patch":"positive_pose_conditioned_mixed","sequence":sequence,"sequence_sha256":digest,
            "parent_id":task["source_candidate_id"],"parent_sequence":parent_sequence[pose_id],
            "cdr1_after":cdrs["cdr1"],"cdr2_after":cdrs["cdr2"],"cdr3_after":cdrs["cdr3"],
            "output_pdb":str(path),"parse_errors":"|".join(errors),**qc,
        })
    fields=[]
    for row in rows:
        for key in row:
            if key not in fields: fields.append(key)
    seen_all:set[str]=set(); seen_pass:set[str]=set(); by_pose:dict[str,list[dict[str,object]]]=defaultdict(list)
    for row in rows:
        sequence=str(row["sequence"])
        row["exact_duplicate_global"]="true" if sequence in seen_all else "false"
        seen_all.add(sequence)
        if row["fast_qc_status"]=="PASS" and sequence not in seen_pass:
            by_pose[str(row["pose_id"])].append(row)
            seen_pass.add(sequence)
    if "exact_duplicate_global" not in fields: fields.append("exact_duplicate_global")
    for pool in by_pose.values(): pool.sort(key=lambda row:int(row["mpnn_index"]))
    selected=[]; selected_sequences=set(); pose_ids=sorted(by_pose); cursors=Counter()
    while len(selected)<args.target:
        gained=0
        for pose_id in pose_ids:
            pool=by_pose[pose_id]
            while cursors[pose_id]<len(pool) and str(pool[cursors[pose_id]]["sequence"]) in selected_sequences:
                cursors[pose_id]+=1
            if cursors[pose_id]<len(pool):
                row=pool[cursors[pose_id]]; cursors[pose_id]+=1
                selected.append(row); selected_sequences.add(str(row["sequence"])); gained+=1
                if len(selected)==args.target: break
        if gained==0: break
    unique_pass=[row for pose in pose_ids for row in by_pose[pose]]
    data=root/"data"; data.mkdir(exist_ok=True)
    write_gzip_tsv(data/"fixed_pose_candidates_raw.tsv.gz",rows,fields)
    write_gzip_tsv(data/"fixed_pose_candidates_exact_unique_fastqc_pass.tsv.gz",unique_pass,fields)
    write_gzip_tsv(data/"fixed_pose_candidates_frozen75k.tsv.gz",selected,fields)
    with gzip.open(data/"fixed_pose_candidates_frozen75k.fasta.gz","wt",encoding="utf-8",compresslevel=1) as handle:
        for row in selected: handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")
    status="PASS" if len(selected)==args.target else "HOLD_INSUFFICIENT_EXACT_UNIQUE_FASTQC_PASS"
    summary={
        "status":status,"raw_output_count":len(rows),"parse_valid_count":sum(not row["parse_errors"] for row in rows),
        "fast_qc_pass_count":sum(row["fast_qc_status"]=="PASS" for row in rows),
        "exact_unique_all_count":len(seen_all),"exact_unique_fast_qc_pass_count":len(seen_pass),
        "frozen_count":len(selected),"target":args.target,
        "top_failure_reasons":Counter(reason for row in rows for reason in str(row["fast_qc_reasons"]).split("|") if reason).most_common(20),
        "scientific_boundary":"Fixed positive-pose ProteinMPNN proposals; not measured affinity or blocking evidence.",
    }
    outputs_to_hash=[data/"fixed_pose_candidates_raw.tsv.gz",data/"fixed_pose_candidates_exact_unique_fastqc_pass.tsv.gz",data/"fixed_pose_candidates_frozen75k.tsv.gz",data/"fixed_pose_candidates_frozen75k.fasta.gz"]
    summary["output_sha256"]={path.name:sha256_file(path) for path in outputs_to_hash}
    (data/"fixed_pose_freeze_summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
    print(json.dumps(summary,indent=2,sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())

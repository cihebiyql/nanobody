#!/usr/bin/env python3
"""Prepare broad-profile exploration-control tasks for bxcpu generation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import shutil
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("fullscale", HERE / "prepare_fullscale_cpu_tasks.py")
BASE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(BASE)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-campaign",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--count",type=int,default=70_000)
    parser.add_argument("--nodes",type=int,default=8)
    parser.add_argument("--workers-per-node",type=int,default=64)
    args=parser.parse_args()
    if args.count<=0 or args.nodes<=0 or args.workers_per_node<=0: parser.error("counts must be positive")
    source=args.pilot_campaign.resolve(); output=args.output_dir.resolve()
    if output.exists(): raise FileExistsError(output)
    parents=BASE.parent_rows(BASE.read_tsv(source/"manifests/pilot_generation_tasks.tsv"))
    rows=BASE.build_route("conservative_cdr_redesign",args.count,parents)
    modes=BASE.labels(args.count,{"H3":0.40,"H1H3":0.35,"H1H2H3":0.25},20260722)
    for index,(row,mode) in enumerate(zip(rows,modes),start=1):
        task_id=f"P500K__PROFILE_DIVERSIFIED_EXPLORATION_CONTROL__{index:07d}"
        row["task_id"]=task_id
        row["route_id"]="profile_diversified_exploration_control"
        row["route_ordinal"]=index
        row["generation_seed"]=int(BASE.sha256_text(task_id+"|profile_diversified_v1")[:8],16)
        row["implementation_status"]="BXCPU_CPU_VALIDATED_PROFILE_EXPLORATION"
        row["design_mode"]=mode
        row["generation_batch"]="profile_diversified_exploration_control_v1"
    random.Random(20260722).shuffle(rows)
    shard_count=args.nodes*args.workers_per_node; shards=[[] for _ in range(shard_count)]
    for index,row in enumerate(rows): shards[index%shard_count].append(row)
    fields=list(rows[0])
    for shard_index,shard in enumerate(shards):
        node=shard_index//args.workers_per_node; worker=shard_index%args.workers_per_node
        BASE.write_tsv(output/"tasks"/f"node_{node:02d}"/f"worker_{worker:02d}.tsv",shard,fields)
    (output/"inputs").mkdir(parents=True)
    for name in ("known_positive_CDR_table.csv","known_positive_antibodies.fasta","top_200_vhh_scaffolds_for_design.csv"):
        shutil.copy2(source/"inputs"/name,output/"inputs"/name)
    summary={
        "status":"READY_FOR_BXCPU_EXPLORATION_CONTROL","route":"profile_diversified_exploration_control",
        "raw_task_count":len(rows),"target_exact_unique_fast_qc":50_000,
        "design_mode_counts":dict(sorted(Counter(str(row["design_mode"]) for row in rows).items())),
        "nodes":args.nodes,"workers_per_node":args.workers_per_node,"shard_count":shard_count,
        "min_shard_size":min(map(len,shards)),"max_shard_size":max(map(len,shards)),
        "scientific_boundary":"Independent broad CDR-profile exploration/control route; not de novo structure generation and not a binding claim.",
    }
    (output/"PREPARED.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
    files=sorted(path for path in output.rglob("*") if path.is_file())
    (output/"SHA256SUMS").write_text("".join(f"{BASE.sha256_file(path)}  {path.relative_to(output)}\n" for path in files))
    print(json.dumps(summary,indent=2,sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())

#!/usr/bin/env python3
"""Materialize the V2.20 Phase-0 train-only 738-candidate contact teacher.

This runner is deliberately not a trainer.  It enforces the frozen scalar split
before any candidate pose path is resolved, stat'ed, hashed, opened, decompressed,
or parsed.  Development, frozen-test, quarantine, and unknown candidates can be
seen only as non-coordinate metadata IDs while streaming source tables; no pose
path is resolved for them.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import tempfile
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

SCHEMA = "pvrig_v2_20_phase0_train_only_contact_teacher_v1_1"
STATUS = "PASS_TRAIN_ONLY_738_CONTACT_TEACHER_MATERIALIZED_V1_1"
CLAIM = (
    "Train-only residue-contact weak supervision derived from computational independent "
    "8X6B/9E6Y Docking poses; not binding, affinity, experimental blocking, Docking Gold, "
    "or OOF model evidence."
)
RECEPTORS = ("8x6b", "9e6y")
SEEDS = (917, 1931, 3253)
TOP_K_MAX = 8
MINIMUM_POSES = 4
CUTOFF = 4.5
EXPECTED = {"V4D": 113, "V4H": 320, "V29": 305}
EXPECTED_TOTAL = 738
EXPECTED_PARENTS = 53
EXPECTED_HASHES = {
    "scalar_teacher": "46bc32276a574e21bb92d7e6672b18aa68323c778b4f65d2415a384144ab95c3",
    "split_manifest": "9dc416dcf8694f321a5432ba8574f0229c03527af14926fcf2f43ee4211f07ed",
    "v4d_pair": "39b600e6979e72ef89237070b36a1f7afaecb4be5be4735d1650d55cd17811a8",
    "v4d_marginal": "1f5906df603fdbaea166c992c93bb4ff1b95c22cccff80739cedbc892a6c6e8e",
    "v4d_receipt": "60502c7ef6931b02beaccd77c805c073e7689a485150ad1c0c3d0541980c1f5f",
    "v4h_pair": "9d27d2297822e978fe969bb645fee97a76ede544de902f6dfe6051c88a33ec92",
    "v4h_marginal": "7b79b07b7b052e518293ec98c5f4b5a79e4f5f0710950ae219a4205a8aff5a7f",
    "v4h_state": "47fc2eb0ee6bae43369bf774d47c490874ceb6dbe04f0fbaece95cd61c8d33e5",
    "v4h_receipt": "ef245ace9c7e2f8c6dbe15893c67689084d00e7720a1855fb88f900fe29b79be",
    "v29_release_receipt": "2f5f9622802262ce67749ea0436653200e6dfbd077920b61c52b511fb63db8c6",
    "v29_weaklabels": "2ffd88625a50b757f5a291a7bbea99632a39db636e8dba570dea890ea95945d4",
    "v29_job_results": "4d3a8c858de78683345c7bd7f3e9f06f801d55ce6953c776f22debbc84b9fd3c",
    "target_cache": "b3081b7e91a5492f7765a721d9114dcb11f8ae095f40bfbcdcc3fe2b36edc108",
    "target_manifest": "c78c30beb4ad668e28f8bfe17872b9712e92fd5871748718a70714a5d5f0ce9d",
    "target_receipt": "b1823387b70375517b65848d873ff0e875396125ca5882ea384fabfcbd8880a9",
}
AA3 = {
    "ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q","GLU":"E","GLY":"G","HIS":"H","ILE":"I",
    "LEU":"L","LYS":"K","MET":"M","PHE":"F","PRO":"P","SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V",
}
AA = set("ACDEFGHIKLMNPQRSTVWY")
PAIR_FIELDS = (
    "schema_version","candidate_id","sequence_sha256","parent_framework_cluster","teacher_source","reliability_tier",
    "receptor","observed_seed_count","observed_seed_ids","vhh_sequence_index","vhh_aa","vhh_region",
    "pvrig_node_index","pvrig_uniprot_position","pvrig_aa","contact_target_mean","contact_target_variance",
    "contact_uncertainty_weight","supporting_seed_count","seed_contact_values","pair_table_semantics","target_mask","claim_boundary",
)
MARGINAL_FIELDS = (
    "schema_version","candidate_id","sequence_sha256","parent_framework_cluster","teacher_source","reliability_tier",
    "receptor","observed_seed_count","observed_seed_ids","vhh_sequence_index","vhh_aa","vhh_region",
    "contact_marginal_mean","contact_marginal_variance","contact_marginal_uncertainty_weight",
    "supporting_seed_count","seed_marginal_values","target_mask","claim_boundary",
)
CANDIDATE_FIELDS = (
    "schema_version","candidate_id","sequence_sha256","sequence","parent_framework_cluster","model_split","teacher_source",
    "reliability_tier","observed_seed_count","observed_seed_ids","seed917_included_multiseed","cdr1","cdr2","cdr3","claim_boundary",
)
GROUP_FIELDS = (
    "schema_version","candidate_id","sequence_sha256","parent_framework_cluster","teacher_source","reliability_tier","receptor",
    "observed_seed_count","observed_seed_ids","sequence_length","target_node_count","dense_pair_universe_size",
    "sparse_nonzero_pair_rows","dense_marginal_rows","technical_failure_zero_imputations","pair_table_semantics","claim_boundary",
)
POSE_FIELDS = (
    "schema_version","candidate_id","sequence_sha256","parent_framework_cluster","model_split","teacher_source","receptor","seed",
    "job_id","top8_rank","model","pose_weight","size_bytes","pose_sha256","source_path","claim_boundary",
)
TARGET_FIELDS = (
    "schema_version","receptor","pvrig_node_index","pvrig_uniprot_position","pvrig_aa","interface_mask","hotspot_mask",
    "normalized_sequence_position","pair_position_baseline_key","marginal_position_baseline_key","fit_scope","claim_boundary",
)


class MaterializationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterializationError(message)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("xb") as handle:
        handle.write(canonical_json(payload)); handle.flush(); os.fsync(handle.fileno())
    os.replace(tmp, path)


def read_regular_snapshot(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise MaterializationError(f"open_failed:{label}:{path}") from exc
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode), f"not_regular:{label}:{path}")
        require(before.st_size > 0, f"empty_file:{label}:{path}")
        blocks=[]
        while True:
            block=os.read(fd, 1024*1024)
            if not block: break
            blocks.append(block)
        after=os.fstat(fd)
        identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        require(identity(before)==identity(after), f"changed_during_read:{label}:{path}")
        raw=b"".join(blocks)
        require(len(raw)==before.st_size, f"short_read:{label}:{path}")
        return raw
    finally:
        os.close(fd)


def parse_json(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str,Any]]) -> dict[str,Any]:
        out={}
        for k,v in pairs:
            require(k not in out, f"duplicate_json_key:{label}:{k}"); out[k]=v
        return out
    try: value=json.loads(raw.decode(), object_pairs_hook=unique)
    except Exception as exc: raise MaterializationError(f"invalid_json:{label}") from exc
    require(isinstance(value,dict), f"json_not_object:{label}")
    return value


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]], gzip_output: bool=False) -> int:
    count=0
    if gzip_output:
        raw=path.open("xb")
        compressed=gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
        text=io.TextIOWrapper(compressed, encoding="utf-8", newline="")
    else:
        raw=None; compressed=None; text=path.open("x",encoding="utf-8",newline="")
    try:
        writer=csv.DictWriter(text,fieldnames=list(fields),delimiter="\t",lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({f:row.get(f,"") for f in fields}); count+=1
        text.flush()
        if gzip_output:
            text.detach(); compressed.close(); raw.flush(); os.fsync(raw.fileno())
        else:
            os.fsync(text.fileno())
    finally:
        if gzip_output:
            if raw and not raw.closed: raw.close()
        elif not text.closed: text.close()
    return count


@dataclass
class AccessGuard:
    split_loaded: bool=False
    allowlist_frozen: bool=False
    train_allowlist: frozenset[str]=frozenset()
    event_order: list[str]=field(default_factory=list)
    pose_accesses: list[tuple[str,str,str,int,str,str]]=field(default_factory=list)
    forbidden_pose_attempts: list[str]=field(default_factory=list)
    metadata_opens: Counter[str]=field(default_factory=Counter)
    filtered_rows_skipped_before_payload_parse: Counter[str]=field(default_factory=Counter)
    lock: threading.Lock=field(default_factory=threading.Lock, repr=False)

    def open_split(self,path:Path)->bytes:
        require(not self.event_order, "split_manifest_not_first_access")
        raw=read_regular_snapshot(path,"split_manifest")
        self.event_order.append("split_manifest_open")
        self.split_loaded=True
        return raw

    def open_metadata(self,path:Path,label:str)->bytes:
        require(self.split_loaded, f"metadata_before_split:{label}")
        raw=read_regular_snapshot(path,label)
        self.event_order.append(f"metadata_open:{label}")
        self.metadata_opens[label]+=1
        return raw

    def freeze_allowlist(self,candidates:Iterable[str])->None:
        require(self.split_loaded, "allowlist_before_split")
        ids=frozenset(candidates); require(ids,"empty_train_allowlist")
        self.train_allowlist=ids; self.allowlist_frozen=True; self.event_order.append("train_allowlist_frozen")

    def resolve_pose(self,*,candidate_id:str,model_split:str,root:Path,job_id:str,model:str)->Path:
        if not self.allowlist_frozen or candidate_id not in self.train_allowlist or model_split!="train":
            with self.lock: self.forbidden_pose_attempts.append(f"{candidate_id}|{model_split}|{job_id}|{model}")
            raise MaterializationError(f"pose_resolution_forbidden:{candidate_id}:{model_split}")
        require(re.fullmatch(r"[A-Za-z0-9_.-]+",job_id) is not None,"unsafe_job_id")
        require(Path(model).name==model and re.fullmatch(r"[A-Za-z0-9_.-]+",model) is not None,"unsafe_model")
        # abspath/normpath are lexical and do not stat candidate paths.
        path=Path(os.path.abspath(os.path.join(str(root),job_id,"haddock_run","6_seletopclusts",model)))
        allowed=Path(os.path.abspath(os.path.join(str(root),job_id,"haddock_run","6_seletopclusts")))
        require(path.parent==allowed,"pose_outside_job_tree")
        return path

    def open_pose(self,path:Path,*,candidate_id:str,model_split:str,receptor:str,seed:int,job_id:str,model:str)->bytes:
        if not self.allowlist_frozen or candidate_id not in self.train_allowlist or model_split!="train":
            with self.lock:self.forbidden_pose_attempts.append(f"OPEN|{candidate_id}|{model_split}|{path}")
            raise MaterializationError(f"pose_open_forbidden:{candidate_id}:{model_split}")
        raw=read_regular_snapshot(path,f"train_pose:{job_id}:{model}")
        with self.lock:self.pose_accesses.append((candidate_id,model_split,receptor,seed,job_id,str(path)))
        return raw

    def audit(self)->dict[str,Any]:
        accesses=sorted(self.pose_accesses)
        return {
            "schema_version":f"{SCHEMA}_access_audit",
            "status":"PASS_SPLIT_BEFORE_ACCESS_TRAIN_ONLY",
            "event_order_prefix":self.event_order[:3],
            "split_manifest_opened_first":bool(self.event_order and self.event_order[0]=="split_manifest_open"),
            "allowlist_frozen_before_first_pose":self.allowlist_frozen,
            "train_pose_files_opened":len(accesses),
            "train_pose_candidates_opened":len({x[0] for x in accesses}),
            "development_pose_paths_resolved":0,
            "development_pose_files_stat_hashed_opened":0,
            "frozen_test_pose_paths_resolved":0,
            "frozen_test_pose_files_stat_hashed_opened":0,
            "quarantine_pose_paths_resolved":0,
            "quarantine_pose_files_stat_hashed_opened":0,
            "unknown_pose_files_stat_hashed_opened":0,
            "forbidden_pose_attempt_count":len(self.forbidden_pose_attempts),
            "forbidden_pose_attempts":sorted(self.forbidden_pose_attempts),
            "metadata_opens":dict(sorted(self.metadata_opens.items())),
            "nonallowlisted_source_rows_skipped_before_numeric_payload_parse":dict(sorted(self.filtered_rows_skipped_before_payload_parse.items())),
            "pose_access_inventory_sha256":sha256_bytes("".join("|".join(map(str,x))+"\n" for x in accesses).encode()),
        }


def tsv_header_and_rows(raw:bytes,label:str)->tuple[list[str],list[dict[str,str]]]:
    try:
        rd=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")),delimiter="\t")
        fields=list(rd.fieldnames or []); rows=[dict(x) for x in rd]
    except Exception as exc: raise MaterializationError(f"invalid_tsv:{label}") from exc
    require(fields and len(fields)==len(set(fields)),f"bad_header:{label}")
    return fields,rows


def stream_filtered_tsv(path:Path,*,label:str,candidate_field:str,allowed:set[str],guard:AccessGuard)->tuple[list[str],list[dict[str,str]]]:
    require(guard.allowlist_frozen,"source_stream_before_allowlist")
    opener=gzip.open if path.suffix==".gz" else open
    mode="rt"
    with opener(path,mode,encoding="utf-8-sig",newline="") as handle:
        header_line=handle.readline(); require(header_line,"empty_source")
        header=next(csv.reader([header_line],delimiter="\t")); require(candidate_field in header,f"candidate_field_missing:{label}")
        idx=header.index(candidate_field); rows=[]; skipped=0
        for line in handle:
            # Source production files contain no quoted tabs.  Candidate ID is inspected first;
            # the remainder is not converted or numerically parsed for non-allowlisted rows.
            raw_parts=line.rstrip("\r\n").split("\t")
            require(len(raw_parts)==len(header),f"source_column_count:{label}")
            candidate=raw_parts[idx]
            if candidate not in allowed:
                skipped+=1; continue
            parsed=next(csv.reader([line],delimiter="\t"))
            rows.append(dict(zip(header,parsed)))
    guard.filtered_rows_skipped_before_payload_parse[label]+=skipped
    guard.metadata_opens[f"stream:{label}"]+=1
    return header,rows


def parse_seed_ids(text:str)->tuple[int,...]:
    values=[int(x) for x in re.split(r"[,;|]+",text.strip()) if x.strip()]
    require(len(values)==len(set(values)) and set(values)<=set(SEEDS),f"invalid_seed_ids:{text}")
    return tuple(sorted(values))


def seed_ids_from_values(text:str)->tuple[int,...]:
    return parse_seed_ids(";".join(item.split(":",1)[0] for item in text.split(";") if item))


def finite_unit(text:Any,label:str)->float:
    try:v=float(text)
    except Exception as exc:raise MaterializationError(f"invalid_float:{label}:{text}") from exc
    require(math.isfinite(v) and 0<=v<=1,f"outside_unit:{label}:{v}");return v


def fmt(value:float)->str:
    require(math.isfinite(value),"nonfinite_output");return format(value,".12g")


def population_variance(values:Sequence[float])->float:
    require(values,"empty_variance");m=sum(values)/len(values);return sum((x-m)**2 for x in values)/len(values)


def uncertainty(variance:float)->float:return 1/(1+4*variance)



FORBIDDEN_FORWARD_KEYS = frozenset({
    "candidate_id", "parent_id", "parent_framework_cluster", "campaign_id", "teacher_source",
    "contact_availability", "seed_count", "reliability_tier", "docking_pose",
    "pose_derived_features", "true_contact_targets", "M2_outputs", "C2_outputs",
})
V213_FOLD_BINDINGS = (
    (0, 7870, 1979, "33f99c6ce640f90bf60e4bada4c134619d1fa284154f99dd86e744467c786617"),
    (1, 7869, 1980, "cdfa29dfaaf65f41250fd0d05d62bb7dd156b3f5113c137b39fb3750a1c60d1e"),
    (2, 7880, 1969, "915eca5630a2d39e15f451446dd33192d8877508141af7442dd825f3a4a3608d"),
    (3, 7848, 2001, "85081812dc09e6437dee93514d9649d8f3efacde0ae416bb1663191941948b4b"),
    (4, 7929, 1920, "4ea0bb063463ade9729e79a94db2f096414c25cd04a6aa844a8dda6fa1f0417d"),
)
B0_OOF_SHA256 = "d441a47e938a0c490cead10c80e6b71bd1a22abe9e22803ed1af43ec04f60669"


def softplus(value: np.ndarray) -> np.ndarray:
    value=np.asarray(value,dtype=np.float64)
    return np.maximum(value,0.0)+np.log1p(np.exp(-np.abs(value)))


def balanced_soft_bce(logits: Sequence[float], targets: Sequence[float], weights: Sequence[float], mask: Sequence[float]) -> float | None:
    l=np.asarray(logits,dtype=np.float64);t=np.asarray(targets,dtype=np.float64);w=np.asarray(weights,dtype=np.float64)*np.asarray(mask,dtype=np.float64)
    require(l.shape==t.shape==w.shape,"contact_reduction_shape")
    pos=w*t;neg=w*(1-t);parts=[]
    if pos.sum()>0:parts.append(float(np.sum(pos*softplus(-l))/pos.sum()))
    if neg.sum()>0:parts.append(float(np.sum(neg*softplus(l))/neg.sum()))
    if not parts:return None
    return sum(parts)/len(parts)


def smooth_l1(values: np.ndarray, beta: float=0.03) -> np.ndarray:
    a=np.abs(np.asarray(values,dtype=np.float64))
    return np.where(a<beta,0.5*a*a/beta,a-0.5*beta)


def v213_softmin(r8: np.ndarray, r9: np.ndarray, tau: float=0.02) -> np.ndarray:
    r8=np.asarray(r8,dtype=np.float64);r9=np.asarray(r9,dtype=np.float64)
    m=np.minimum(r8,r9)
    # Stable form of -tau*log(exp(-r8/tau)+exp(-r9/tau))+tau*log(2).
    return m-tau*np.log(np.exp(-(r8-m)/tau)+np.exp(-(r9-m)/tau))+tau*np.log(2.0)


def v213_scalar_loss(pred: np.ndarray, truth: np.ndarray, row_weights: Sequence[float]) -> float:
    pred=np.asarray(pred,dtype=np.float64);truth=np.asarray(truth,dtype=np.float64);w=np.asarray(row_weights,dtype=np.float64)
    require(pred.shape==truth.shape and pred.ndim==2 and pred.shape[1]==2 and len(w)==len(pred),"scalar_loss_shape")
    w=w/w.sum(); receptor=smooth_l1(pred-truth,0.03).mean(axis=1)
    dual=smooth_l1(v213_softmin(pred[:,0],pred[:,1])-np.minimum(truth[:,0],truth[:,1]),0.03)
    return float(np.sum(w*receptor)+0.5*np.sum(w*dual))


def v213_top_weights(exact_min_truth: Sequence[float], manifest_weights: Sequence[float]) -> np.ndarray:
    values=np.asarray(exact_min_truth,dtype=np.float64);base=np.asarray(manifest_weights,dtype=np.float64)
    require(values.ndim==base.ndim==1 and len(values)==len(base) and len(values)>1,"top_weight_shape")
    order=np.argsort(values,kind="mergesort"); ranks=np.empty(len(values),dtype=np.float64)
    start=0
    while start<len(values):
        end=start+1
        while end<len(values) and values[order[end]]==values[order[start]]:end+=1
        avg=(start+1+end)/2.0;ranks[order[start:end]]=avg;start=end
    p=(ranks-1)/(len(values)-1)
    return base*(1+3/(1+np.exp(-(p-0.85)/0.05)))


def v213_epoch_batches(count:int,seed:int,epoch:int,batch_size:int=8)->list[tuple[int,...]]:
    import random
    ids=list(range(count));random.Random(seed+epoch).shuffle(ids)
    return [tuple(ids[i:i+batch_size]) for i in range(0,count,batch_size)]


def v213_remainder_gradient_scale(remainder:int,accumulation:int=4)->float:
    require(1<=remainder<=accumulation,"bad_remainder")
    return accumulation/remainder if remainder<accumulation else 1.0


def state_hash(state: Mapping[str, Any]) -> str:
    digest=hashlib.sha256()
    for name in sorted(state):
        value=np.asarray(state[name]);digest.update(name.encode()+b"\0");digest.update(str(value.dtype).encode()+b"\0");digest.update(str(value.shape).encode()+b"\0");digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def validate_forward_keys(keys: Iterable[str]) -> None:
    bad=sorted(set(keys)&set(FORBIDDEN_FORWARD_KEYS));require(not bad,f"forbidden_forward_keys:{bad}")


def conflict_prelaunch_fails(cosines: Sequence[float]) -> bool:
    require(len(cosines)==8,"conflict_calibration_batch_count")
    return sum(float(x)<-0.50 for x in cosines)>2


def deterministic_derangement(items: Sequence[str], seed: int=20260723) -> dict[str,str]:
    import random
    values=list(items);require(len(values)>=2 and len(set(values))==len(values),"derangement_items")
    shuffled=values[:];random.Random(seed).shuffle(shuffled)
    # Rotate until no fixed points.  This is deterministic and always succeeds for n>=2.
    for shift in range(1,len(values)+1):
        candidate=shuffled[shift:]+shuffled[:shift]
        if all(a!=b for a,b in zip(values,candidate)):return dict(zip(values,candidate))
    # Fallback cyclic shift of the original order.
    candidate=values[1:]+values[:1];return dict(zip(values,candidate))


def movement_rate(mapping: Mapping[str,str]) -> float:
    require(mapping,"empty_movement_mapping")
    return sum(k!=v for k,v in mapping.items())/len(mapping)

def region_map(sequence:str,cdr1:str,cdr2:str,cdr3:str)->list[str]:
    regions=["framework"]*len(sequence); start=0
    for name,cdr in (("cdr1",cdr1),("cdr2",cdr2),("cdr3",cdr3)):
        require(cdr and set(cdr)<=AA,f"invalid_{name}")
        pos=sequence.find(cdr,start);require(pos>=0,f"{name}_not_found")
        for i in range(pos,pos+len(cdr)):regions[i]=name
        start=pos+len(cdr)
    return regions


def load_scalar_allowlist(split_raw:bytes,scalar_raw:bytes)->tuple[dict[str,dict[str,str]],dict[str,Any]]:
    split=parse_json(split_raw,"split_manifest")
    require(split.get("training_tsv_sha256")==EXPECTED_HASHES["scalar_teacher"],"split_scalar_hash")
    train_parents=set(split.get("train_parents") or []);score_parents=set(split.get("score_parents") or [])
    require(len(train_parents)==54 and len(score_parents)==10 and not train_parents&score_parents,"parent_split")
    text=scalar_raw.decode("utf-8-sig"); reader=csv.reader(io.StringIO(text),delimiter="\t")
    header=next(reader); required={"candidate_id","sequence_sha256","sequence","parent_framework_cluster","cdr1","cdr2","cdr3","teacher_source"}
    require(required<=set(header),"scalar_fields"); idx={x:header.index(x) for x in required}
    training={}; score_identity_rows=0
    for parts in reader:
        require(len(parts)==len(header),"scalar_column_count")
        parent=parts[idx["parent_framework_cluster"]]
        # No scalar numeric target is converted here.  Score rows contribute identity count only.
        if parent in score_parents: score_identity_rows+=1; continue
        require(parent in train_parents,f"scalar_parent_unknown:{parent}")
        row={k:parts[i] for k,i in idx.items()}; cid=row["candidate_id"]
        seq=row["sequence"].upper();require(seq and set(seq)<=AA,"bad_scalar_sequence")
        require(sha256_bytes(seq.encode())==row["sequence_sha256"],"scalar_sequence_hash")
        require(cid not in training,"duplicate_scalar_train")
        row["sequence"]=seq;row["regions"]=region_map(seq,row["cdr1"],row["cdr2"],row["cdr3"])
        training[cid]=row
    require(len(training)==9849 and score_identity_rows==795,"scalar_split_counts")
    return training,{"train_rows":len(training),"score_identity_rows_seen_without_numeric_parse":score_identity_rows,"train_parents":len(train_parents)}


def load_target(cache:Path,manifest:Path,receipt:Path,guard:AccessGuard)->tuple[dict[str,dict[int,tuple[int,str]]],dict[str,Any],list[dict[str,Any]]]:
    for label,path,key in (("target_cache",cache,"target_cache"),("target_manifest",manifest,"target_manifest"),("target_receipt",receipt,"target_receipt")):
        raw=guard.open_metadata(path,label);require(sha256_bytes(raw)==EXPECTED_HASHES[key],f"hash:{label}")
    manifest_raw=read_regular_snapshot(manifest,"target_manifest_reparse")
    fields,rows=tsv_header_and_rows(manifest_raw,"target_manifest")
    by={r["receptor"].lower():r for r in rows};require(set(by)==set(RECEPTORS),"target_receptors")
    maps={}; info={}; baseline=[]
    with np.load(io.BytesIO(read_regular_snapshot(cache,"target_cache_reparse")),allow_pickle=False) as z:
        for receptor in RECEPTORS:
            seq=by[receptor]["sequence"].strip();positions=z[f"{receptor}_uniprot_position"].tolist()
            interface=z[f"{receptor}_interface_mask"].tolist();hotspot=z[f"{receptor}_hotspot_mask"].tolist()
            require(len(seq)==len(positions)==int(by[receptor]["node_count"]),"target_count")
            maps[receptor]={int(p):(i+1,seq[i]) for i,p in enumerate(positions)}
            require(len(maps[receptor])==len(seq),"target_position_duplicate")
            info[receptor]={"node_count":len(seq),"sequence_sha256":by[receptor]["sequence_sha256"]}
            for i,(p,aa) in enumerate(zip(positions,seq),start=1):
                baseline.append({"schema_version":f"{SCHEMA}_target_node_position_baseline_contract","receptor":receptor,"pvrig_node_index":i,"pvrig_uniprot_position":p,"pvrig_aa":aa,"interface_mask":int(interface[i-1]),"hotspot_mask":int(hotspot[i-1]),"normalized_sequence_position":fmt((i-1)/max(1,len(seq)-1)),"pair_position_baseline_key":"receptor|vhh_region|vhh_sequence_index|pvrig_node_index","marginal_position_baseline_key":"receptor|vhh_region|vhh_sequence_index","fit_scope":"outer_fit_parents_only_Beta1_1_backoff","claim_boundary":"Label-free target-node/position baseline schema only; no score-parent or development contact labels."})
    return maps,info,baseline


def normalize_pair(row:Mapping[str,str],candidate:Mapping[str,Any],source:str,target_map:Mapping[str,Mapping[int,tuple[int,str]]])->dict[str,Any]:
    receptor=row["receptor"].lower();require(receptor in RECEPTORS,"pair_receptor")
    vi=int(row["vhh_sequence_index"]);require(1<=vi<=len(candidate["sequence"]),"pair_vhh_index")
    require(row["vhh_aa"]==candidate["sequence"][vi-1],"pair_vhh_aa")
    pos=int(row["pvrig_uniprot_position"]);require(pos in target_map[receptor],"pair_target_pos")
    node,aa=target_map[receptor][pos];require(row["pvrig_aa"]==aa,"pair_target_aa")
    observed=int(row["observed_seed_count"]);require(observed in (2,3),"pair_seed_count")
    seed_values=row["seed_contact_values"];seeds=seed_ids_from_values(seed_values);require(len(seeds)==observed,"pair_seed_values")
    mean=finite_unit(row["contact_target_mean"],"pair_mean");variance=float(row["contact_target_variance"]);weight=finite_unit(row["contact_uncertainty_weight"],"pair_weight")
    require(mean>0 and variance>=0 and abs(weight-uncertainty(variance))<2e-8,"pair_stats")
    return {"schema_version":SCHEMA,"candidate_id":candidate["candidate_id"],"sequence_sha256":candidate["sequence_sha256"],"parent_framework_cluster":candidate["parent_framework_cluster"],"teacher_source":source,"reliability_tier":f"{observed}_SEED","receptor":receptor,"observed_seed_count":observed,"observed_seed_ids":",".join(map(str,seeds)),"vhh_sequence_index":vi,"vhh_aa":candidate["sequence"][vi-1],"vhh_region":candidate["regions"][vi-1],"pvrig_node_index":node,"pvrig_uniprot_position":pos,"pvrig_aa":aa,"contact_target_mean":fmt(mean),"contact_target_variance":fmt(variance),"contact_uncertainty_weight":fmt(weight),"supporting_seed_count":row["supporting_seed_count"],"seed_contact_values":seed_values,"pair_table_semantics":"SPARSE_ABSENCE_IS_EXACT_ZERO_AFTER_VALID_GROUP_CLOSURE","target_mask":1,"claim_boundary":CLAIM}


def normalize_marginal(row:Mapping[str,str],candidate:Mapping[str,Any],source:str)->dict[str,Any]:
    receptor=row["receptor"].lower();require(receptor in RECEPTORS,"marginal_receptor")
    vi=int(row["vhh_sequence_index"]);require(1<=vi<=len(candidate["sequence"]),"marginal_index")
    require(row["vhh_aa"]==candidate["sequence"][vi-1],"marginal_aa")
    observed=int(row["observed_seed_count"]);require(observed in (2,3),"marginal_seed_count")
    seed_values=row["seed_marginal_values"];seeds=seed_ids_from_values(seed_values);require(len(seeds)==observed,"marginal_seed_values")
    mean=finite_unit(row["contact_marginal_mean"],"marginal_mean");variance=float(row["contact_marginal_variance"]);weight=finite_unit(row["contact_marginal_uncertainty_weight"],"marginal_weight")
    require(variance>=0 and abs(weight-uncertainty(variance))<2e-8,"marginal_stats")
    return {"schema_version":SCHEMA,"candidate_id":candidate["candidate_id"],"sequence_sha256":candidate["sequence_sha256"],"parent_framework_cluster":candidate["parent_framework_cluster"],"teacher_source":source,"reliability_tier":f"{observed}_SEED","receptor":receptor,"observed_seed_count":observed,"observed_seed_ids":",".join(map(str,seeds)),"vhh_sequence_index":vi,"vhh_aa":candidate["sequence"][vi-1],"vhh_region":candidate["regions"][vi-1],"contact_marginal_mean":fmt(mean),"contact_marginal_variance":fmt(variance),"contact_marginal_uncertainty_weight":fmt(weight),"supporting_seed_count":row["supporting_seed_count"],"seed_marginal_values":seed_values,"target_mask":1,"claim_boundary":CLAIM}


def decode_pose(raw:bytes,path:Path)->str:
    try:return (gzip.decompress(raw) if path.suffix==".gz" else raw).decode("ascii")
    except Exception as exc:raise MaterializationError(f"pose_decode:{path}") from exc


def heavy_atom(line:str)->bool:
    atom=line[12:16].strip().upper(); element=line[76:78].strip().upper() if len(line)>=78 else ""
    if not element:element="".join(c for c in atom if c.isalpha())[:1]
    return element not in {"H","D"} and not atom.startswith(("H","D"))


def contacts_from_pose(raw:bytes,path:Path,sequence:str,vhh_chain:str="A",target_chain:str="T")->tuple[set[tuple[int,int]],dict[int,str]]:
    vx=[];vkeys=[];tx=[];tpos=[];tnames={};order=[];seen=set()
    for n,line in enumerate(decode_pose(raw,path).splitlines(),start=1):
        if not line.startswith("ATOM  "):continue
        require(len(line)>=54,f"short_atom:{path}:{n}")
        rn=line[17:20].strip().upper()
        if rn not in AA3 or not heavy_atom(line):continue
        chain=line[21:22]
        try:num=int(line[22:26]);icode=line[26:27];xyz=(float(line[30:38]),float(line[38:46]),float(line[46:54]))
        except Exception as exc:raise MaterializationError(f"bad_atom:{path}:{n}") from exc
        key=(num,icode,rn)
        if chain==vhh_chain:
            if key not in seen:seen.add(key);order.append(key)
            vx.append(xyz);vkeys.append(key)
        elif chain==target_chain:
            require(tnames.setdefault(num,rn)==rn,"target_identity_conflict");tx.append(xyz);tpos.append(num)
    observed="".join(AA3[x[2]] for x in order);require(observed==sequence,f"pose_sequence_mismatch:{path}")
    require(vx and tx,"pose_chain_missing")
    key_index={x:i+1 for i,x in enumerate(order)};vi=np.asarray([key_index[x] for x in vkeys]);pi=np.asarray(tpos)
    left=np.asarray(vx,dtype=np.float64);right=np.asarray(tx,dtype=np.float64);pairs=set();c2=CUTOFF*CUTOFF
    for start in range(0,len(left),256):
        d=np.sum((left[start:start+256,None,:]-right[None,:,:])**2,axis=2)
        for i,j in np.argwhere(d<=c2):pairs.add((int(vi[start+int(i)]),int(pi[int(j)])))
    return pairs,tnames


def raw_pose_weights(count:int)->list[float]:
    require(MINIMUM_POSES<=count<=TOP_K_MAX,"pose_count_out_of_contract")
    raw=[1/math.log2(rank+1) for rank in range(1,count+1)];total=sum(raw);return [x/total for x in raw]


def process_v29_job(task:Mapping[str,Any],guard:AccessGuard,pose_root:Path,target_map:Mapping[str,Mapping[int,tuple[int,str]]])->dict[str,Any]:
    row=task["job"];c=task["candidate"];receptor=row["conformation"].lower();seed=int(row["seed"]);job=row["job_id"]
    models=[x for x in row["top8_model_ids"].split(",") if x]; expected_count=int(row["fixed_top8_count"]); require(MINIMUM_POSES<=expected_count<=TOP_K_MAX and len(models)==expected_count and len(set(models))==expected_count,"v29_top8_models")
    pair=defaultdict(float);marg=defaultdict(float);inventory=[];names={}
    for rank,(model,weight) in enumerate(zip(models,raw_pose_weights(len(models))),start=1):
        path=guard.resolve_pose(candidate_id=c["candidate_id"],model_split="train",root=pose_root,job_id=job,model=model)
        raw=guard.open_pose(path,candidate_id=c["candidate_id"],model_split="train",receptor=receptor,seed=seed,job_id=job,model=model)
        pairs,observed_names=contacts_from_pose(raw,path,c["sequence"])
        for vi,pos in pairs:
            require(pos in target_map[receptor],f"v29_target_outside_graph:{job}:{pos}")
            pair[(vi,pos)]+=weight
        for vi in {x[0] for x in pairs}:marg[vi]+=weight
        for pos,rn in observed_names.items():
            if pos in target_map[receptor]:require(AA3[rn]==target_map[receptor][pos][1],"v29_target_aa")
            names[pos]=rn
        inventory.append({"schema_version":SCHEMA,"candidate_id":c["candidate_id"],"sequence_sha256":c["sequence_sha256"],"parent_framework_cluster":c["parent_framework_cluster"],"model_split":"train","teacher_source":"V29","receptor":receptor,"seed":seed,"job_id":job,"top8_rank":rank,"model":model,"pose_weight":fmt(weight),"size_bytes":len(raw),"pose_sha256":sha256_bytes(raw),"source_path":str(path),"claim_boundary":CLAIM})
    return {"candidate_id":c["candidate_id"],"receptor":receptor,"seed":seed,"pair":dict(pair),"marginal":dict(marg),"inventory":inventory}


def aggregate_v29(candidate:Mapping[str,Any],receptor:str,seed_results:Sequence[Mapping[str,Any]],target_map:Mapping[str,Mapping[int,tuple[int,str]]])->tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    by={int(x["seed"]):x for x in seed_results};seeds=tuple(sorted(by));require(len(seeds)>=2 and 917 in seeds,"v29_seed_rule")
    pair_rows=[]
    for vi,pos in sorted({key for x in seed_results for key in x["pair"]}):
        vals=[float(by[s]["pair"].get((vi,pos),0)) for s in seeds];mean=sum(vals)/len(vals);var=population_variance(vals);node,aa=target_map[receptor][pos]
        pair_rows.append({"schema_version":SCHEMA,"candidate_id":candidate["candidate_id"],"sequence_sha256":candidate["sequence_sha256"],"parent_framework_cluster":candidate["parent_framework_cluster"],"teacher_source":"V29","reliability_tier":f"{len(seeds)}_SEED","receptor":receptor,"observed_seed_count":len(seeds),"observed_seed_ids":",".join(map(str,seeds)),"vhh_sequence_index":vi,"vhh_aa":candidate["sequence"][vi-1],"vhh_region":candidate["regions"][vi-1],"pvrig_node_index":node,"pvrig_uniprot_position":pos,"pvrig_aa":aa,"contact_target_mean":fmt(mean),"contact_target_variance":fmt(var),"contact_uncertainty_weight":fmt(uncertainty(var)),"supporting_seed_count":sum(x>0 for x in vals),"seed_contact_values":";".join(f"{s}:{fmt(v)}" for s,v in zip(seeds,vals)),"pair_table_semantics":"SPARSE_ABSENCE_IS_EXACT_ZERO_AFTER_VALID_GROUP_CLOSURE","target_mask":1,"claim_boundary":CLAIM})
    marginal=[]
    for vi,aa in enumerate(candidate["sequence"],start=1):
        vals=[float(by[s]["marginal"].get(vi,0)) for s in seeds];mean=sum(vals)/len(vals);var=population_variance(vals)
        marginal.append({"schema_version":SCHEMA,"candidate_id":candidate["candidate_id"],"sequence_sha256":candidate["sequence_sha256"],"parent_framework_cluster":candidate["parent_framework_cluster"],"teacher_source":"V29","reliability_tier":f"{len(seeds)}_SEED","receptor":receptor,"observed_seed_count":len(seeds),"observed_seed_ids":",".join(map(str,seeds)),"vhh_sequence_index":vi,"vhh_aa":aa,"vhh_region":candidate["regions"][vi-1],"contact_marginal_mean":fmt(mean),"contact_marginal_variance":fmt(var),"contact_marginal_uncertainty_weight":fmt(uncertainty(var)),"supporting_seed_count":sum(x>0 for x in vals),"seed_marginal_values":";".join(f"{s}:{fmt(v)}" for s,v in zip(seeds,vals)),"target_mask":1,"claim_boundary":CLAIM})
    return pair_rows,marginal


def validate_freeze(path:Path,contract:Path)->dict[str,Any]:
    payload=parse_json(read_regular_snapshot(path,"implementation_freeze"),"implementation_freeze")
    require(payload.get("status")=="FROZEN_PHASE0_TEACHER_MATERIALIZATION_ONLY_OOF_TRAINING_NOT_AUTHORIZED","freeze_status")
    require(payload.get("oof_training_authorized") is False,"freeze_oof")
    artifacts=payload.get("artifacts") or {}
    require(artifacts.get("materializer_sha256")==sha256_file(Path(__file__)),"freeze_materializer_hash")
    require(artifacts.get("phase0_contract_sha256")==sha256_file(contract),"freeze_contract_hash")
    return payload


def materialize(*,scalar_teacher:Path,split_manifest:Path,phase0_contract:Path,implementation_freeze:Path,v4d_pair:Path,v4d_marginal:Path,v4d_receipt:Path,v4h_pair:Path,v4h_marginal:Path,v4h_state:Path,v4h_receipt:Path,v29_release:Path,v29_pose_root:Path,target_cache:Path,target_manifest:Path,target_receipt:Path,output_dir:Path,workers:int=8)->dict[str,Any]:
    require(workers>=1,"workers")
    require(not output_dir.exists(),"output_exists")
    guard=AccessGuard()
    split_raw=guard.open_split(split_manifest);require(sha256_bytes(split_raw)==EXPECTED_HASHES["split_manifest"],"split_hash")
    scalar_raw=guard.open_metadata(scalar_teacher,"scalar_teacher");require(sha256_bytes(scalar_raw)==EXPECTED_HASHES["scalar_teacher"],"scalar_hash")
    training,split_audit=load_scalar_allowlist(split_raw,scalar_raw)
    guard.freeze_allowlist(training)
    contract=parse_json(guard.open_metadata(phase0_contract,"phase0_contract"),"phase0_contract")
    require(contract.get("status")=="FROZEN_PHASE0_TEACHER_MATERIALIZATION_ONLY_OOF_TRAINING_NOT_AUTHORIZED","phase0_status")
    freeze=validate_freeze(implementation_freeze,phase0_contract)
    target_map,target_info,baseline_rows=load_target(target_cache,target_manifest,target_receipt,guard)
    # Verify source artifacts only after the exact train allowlist is frozen.
    source_paths={"v4d_pair":v4d_pair,"v4d_marginal":v4d_marginal,"v4d_receipt":v4d_receipt,"v4h_pair":v4h_pair,"v4h_marginal":v4h_marginal,"v4h_state":v4h_state,"v4h_receipt":v4h_receipt,"v29_release_receipt":v29_release/"RELEASE_RECEIPT.json","v29_weaklabels":v29_release/"release/pvrig_v29_sequence_docking_weaklabels.tsv","v29_job_results":v29_release/"reports/canonical_job_results.tsv"}
    input_hashes={}
    for label,path in source_paths.items():
        raw=guard.open_metadata(path,label);digest=sha256_bytes(raw);require(digest==EXPECTED_HASHES[label],f"source_hash:{label}");input_hashes[label]=digest
    allowed_v4d={cid for cid,c in training.items() if c["teacher_source"]=="V4D_OPEN_MULTI_SEED"}
    allowed_v4h={cid for cid,c in training.items() if c["teacher_source"]=="V4H_ADAPTIVE_SEED_RANKING"}
    allowed_v29={cid for cid,c in training.items() if c["teacher_source"]=="V29_CANONICAL_PRIMARY_SEED917"}
    # V4D: filter source lines by frozen train allowlist before numeric parsing.
    _,v4d_m_rows=stream_filtered_tsv(v4d_marginal,label="v4d_marginal",candidate_field="candidate_id",allowed=allowed_v4d,guard=guard)
    v4d_ids={r["candidate_id"] for r in v4d_m_rows};require(len(v4d_ids)==EXPECTED["V4D"],f"v4d_count:{len(v4d_ids)}")
    _,v4d_p_rows=stream_filtered_tsv(v4d_pair,label="v4d_pair",candidate_field="candidate_id",allowed=v4d_ids,guard=guard)
    # V4H: select 2/3-seed state rows first, then filter pair/marginal.
    _,v4h_s_rows=stream_filtered_tsv(v4h_state,label="v4h_state",candidate_field="candidate_id",allowed=allowed_v4h,guard=guard)
    v4h_selected={r["candidate_id"]:r for r in v4h_s_rows if int(r["paired_seed_count"])>=2}
    require(len(v4h_selected)==EXPECTED["V4H"],f"v4h_count:{len(v4h_selected)}")
    _,v4h_p_rows=stream_filtered_tsv(v4h_pair,label="v4h_pair",candidate_field="candidate_id",allowed=set(v4h_selected),guard=guard)
    _,v4h_m_rows=stream_filtered_tsv(v4h_marginal,label="v4h_marginal",candidate_field="candidate_id",allowed=set(v4h_selected),guard=guard)
    # V29 canonical metadata: only train allowlist rows are parsed.
    _,v29_w_rows=stream_filtered_tsv(source_paths["v29_weaklabels"],label="v29_weaklabels",candidate_field="candidate_id",allowed=allowed_v29,guard=guard)
    v29_meta={r["candidate_id"]:r for r in v29_w_rows}
    for cid,r in v29_meta.items():
        c=training[cid];require(r["sequence_sha256"]==c["sequence_sha256"] and r["canonical_model_split"]=="train","v29_identity_split")
    _,v29_job_rows=stream_filtered_tsv(source_paths["v29_job_results"],label="v29_job_results",candidate_field="entity_id",allowed=allowed_v29,guard=guard)
    job_grid={}
    for r in v29_job_rows:
        if r["canonical_state"]!="SUCCESS" or r["selected_source"]!="lab":continue
        cid=r["entity_id"];require(r["sequence_sha256"]==training[cid]["sequence_sha256"],"v29_job_hash")
        receptor=r["conformation"].lower();seed=int(r["seed"]);require(receptor in RECEPTORS and seed in SEEDS,"v29_job_axis")
        pose_count=int(r["fixed_top8_count"]);require(MINIMUM_POSES<=pose_count<=TOP_K_MAX and pose_count==int(r["selected_model_count"]),"v29_selected_pose_count")
        key=(cid,receptor,seed);require(key not in job_grid,"v29_duplicate_job");job_grid[key]=r
    v29_seed_sets={}
    for cid in allowed_v29:
        seeds=tuple(s for s in SEEDS if (cid,"8x6b",s) in job_grid and (cid,"9e6y",s) in job_grid)
        if len(seeds)>=2 and 917 in seeds:v29_seed_sets[cid]=seeds
    require(len(v29_seed_sets)==EXPECTED["V29"],f"v29_count:{len(v29_seed_sets)}")
    # Canonical candidate records.
    candidates={}
    for source,ids in (("V4D",v4d_ids),("V4H",set(v4h_selected)),("V29",set(v29_seed_sets))):
        for cid in ids:
            require(cid not in candidates,"cross_source_candidate_duplicate");c=dict(training[cid]);c["candidate_id"]=cid;c["teacher_source_normalized"]=source;candidates[cid]=c
    require(len(candidates)==EXPECTED_TOTAL and len({c["parent_framework_cluster"] for c in candidates.values()})==EXPECTED_PARENTS,"primary_count_parent")
    pair_rows=[];marginal_rows=[]
    for row in v4d_p_rows:pair_rows.append(normalize_pair(row,candidates[row["candidate_id"]],"V4D",target_map))
    for row in v4d_m_rows:marginal_rows.append(normalize_marginal(row,candidates[row["candidate_id"]],"V4D"))
    for row in v4h_p_rows:pair_rows.append(normalize_pair(row,candidates[row["candidate_id"]],"V4H",target_map))
    for row in v4h_m_rows:marginal_rows.append(normalize_marginal(row,candidates[row["candidate_id"]],"V4H"))
    # Run V29 pose extraction only after final train-only candidate selection.
    tasks=[]
    for cid,seeds in sorted(v29_seed_sets.items()):
        for receptor in RECEPTORS:
            for seed in seeds:tasks.append({"candidate":candidates[cid],"job":job_grid[(cid,receptor,seed)]})
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results=list(executor.map(lambda t:process_v29_job(t,guard,v29_pose_root,target_map),tasks))
    by_group=defaultdict(list);pose_inventory=[]
    for result in results:by_group[(result["candidate_id"],result["receptor"])].append(result);pose_inventory.extend(result["inventory"])
    for cid in sorted(v29_seed_sets):
        for receptor in RECEPTORS:
            p,m=aggregate_v29(candidates[cid],receptor,by_group[(cid,receptor)],target_map);pair_rows.extend(p);marginal_rows.extend(m)
    # Bind seed provenance for all candidates from normalized marginals.
    provenance={}
    for row in marginal_rows:
        key=row["candidate_id"];value=(int(row["observed_seed_count"]),row["observed_seed_ids"],row["reliability_tier"])
        require(key not in provenance or provenance[key]==value,"candidate_seed_provenance_conflict");provenance[key]=value
    require(set(provenance)==set(candidates),"candidate_provenance_closure")
    pair_rows.sort(key=lambda r:(r["candidate_id"],RECEPTORS.index(r["receptor"]),int(r["vhh_sequence_index"]),int(r["pvrig_node_index"])))
    marginal_rows.sort(key=lambda r:(r["candidate_id"],RECEPTORS.index(r["receptor"]),int(r["vhh_sequence_index"])))
    pose_inventory.sort(key=lambda r:(r["candidate_id"],RECEPTORS.index(r["receptor"]),int(r["seed"]),int(r["top8_rank"]),r["model"]))
    pair_counts=Counter((r["candidate_id"],r["receptor"]) for r in pair_rows);marg_counts=Counter((r["candidate_id"],r["receptor"]) for r in marginal_rows)
    candidate_rows=[];group_rows=[]
    for cid in sorted(candidates):
        c=candidates[cid];observed,seed_text,tier=provenance[cid];source=c["teacher_source_normalized"]
        candidate_rows.append({"schema_version":SCHEMA,"candidate_id":cid,"sequence_sha256":c["sequence_sha256"],"sequence":c["sequence"],"parent_framework_cluster":c["parent_framework_cluster"],"model_split":"train","teacher_source":source,"reliability_tier":tier,"observed_seed_count":observed,"observed_seed_ids":seed_text,"seed917_included_multiseed":int(917 in parse_seed_ids(seed_text)),"cdr1":c["cdr1"],"cdr2":c["cdr2"],"cdr3":c["cdr3"],"claim_boundary":CLAIM})
        for receptor in RECEPTORS:
            require(marg_counts[(cid,receptor)]==len(c["sequence"]),f"marginal_dense_closure:{cid}:{receptor}")
            group_rows.append({"schema_version":SCHEMA,"candidate_id":cid,"sequence_sha256":c["sequence_sha256"],"parent_framework_cluster":c["parent_framework_cluster"],"teacher_source":source,"reliability_tier":tier,"receptor":receptor,"observed_seed_count":observed,"observed_seed_ids":seed_text,"sequence_length":len(c["sequence"]),"target_node_count":target_info[receptor]["node_count"],"dense_pair_universe_size":len(c["sequence"])*target_info[receptor]["node_count"],"sparse_nonzero_pair_rows":pair_counts[(cid,receptor)],"dense_marginal_rows":marg_counts[(cid,receptor)],"technical_failure_zero_imputations":0,"pair_table_semantics":"SPARSE_ABSENCE_IS_EXACT_ZERO_AFTER_VALID_GROUP_CLOSURE","claim_boundary":CLAIM})
    access=guard.audit();require(access["split_manifest_opened_first"] and access["forbidden_pose_attempt_count"]==0,"access_audit_fail")
    require(access["development_pose_files_stat_hashed_opened"]==0,"dev_pose_access")
    staging=Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.",dir=output_dir.parent))
    try:
        files={
            "train_contact_candidate_manifest.tsv":(CANDIDATE_FIELDS,candidate_rows,False),
            "train_sparse_pair_contact_teacher.tsv.gz":(PAIR_FIELDS,pair_rows,True),
            "train_dense_marginal_contact_teacher.tsv.gz":(MARGINAL_FIELDS,marginal_rows,True),
            "train_candidate_receptor_group_audit.tsv.gz":(GROUP_FIELDS,group_rows,True),
            "v29_train_pose_sha256_manifest.tsv.gz":(POSE_FIELDS,pose_inventory,True),
            "target_node_position_baseline_contract.tsv":(TARGET_FIELDS,baseline_rows,False),
        }
        output_counts={}
        for name,(fields,rows,gz) in files.items():output_counts[name]=write_tsv(staging/name,fields,rows,gz)
        atomic_json(staging/"ACCESS_AUDIT.json",access)
        outputs={name:sha256_file(staging/name) for name in (*files,"ACCESS_AUDIT.json")}
        receipt={"schema_version":f"{SCHEMA}_receipt","status":STATUS,"claim_boundary":CLAIM,"oof_training_authorized":False,"implementation":{"materializer_path":str(Path(__file__).resolve()),"materializer_sha256":sha256_file(Path(__file__)),"phase0_contract_sha256":sha256_file(phase0_contract),"implementation_freeze_sha256":sha256_file(implementation_freeze),"freeze_status":freeze["status"]},"inputs":{"hashes":{**input_hashes,"scalar_teacher":EXPECTED_HASHES["scalar_teacher"],"split_manifest":EXPECTED_HASHES["split_manifest"],"target_cache":EXPECTED_HASHES["target_cache"],"target_manifest":EXPECTED_HASHES["target_manifest"],"target_receipt":EXPECTED_HASHES["target_receipt"]}},"split_audit":split_audit,"counts":{"candidates":len(candidate_rows),"parents":len({x["parent_framework_cluster"] for x in candidate_rows}),"source_candidates":dict(sorted(Counter(x["teacher_source"] for x in candidate_rows).items())),"candidate_receptor_groups":len(group_rows),"sparse_pair_rows":len(pair_rows),"dense_marginal_rows":len(marginal_rows),"v29_train_pose_files":len(pose_inventory),"target_node_contract_rows":len(baseline_rows),"development_candidates_emitted":0,"single_seed_candidates_emitted":0,"technical_failed_seed_zero_imputations":0},"access_boundary":access,"output_row_counts":output_counts,"outputs":outputs,"gradient_calibration_future_contract":{"g_contact":"gradient_shared(L_marginal + 0.5*L_pair) before lambda scaling","phase0_gradient_computations":0},"target_node_position_baseline_contract":{"pair_key":"receptor|vhh_region|vhh_sequence_index|pvrig_node_index","marginal_key":"receptor|vhh_region|vhh_sequence_index","fit_scope":"outer_fit_parents_only","score_or_development_labels_used":False}}
        atomic_json(staging/"MATERIALIZATION_RECEIPT.json",receipt)
        sum_names=[*files,"ACCESS_AUDIT.json","MATERIALIZATION_RECEIPT.json"]
        (staging/"SHA256SUMS").write_text("".join(f"{sha256_file(staging/name)}  {name}\n" for name in sum_names),encoding="utf-8")
        os.replace(staging,output_dir)
        return receipt
    finally:
        if staging.exists():shutil.rmtree(staging)


def verify_package(root:Path)->dict[str,Any]:
    receipt=parse_json(read_regular_snapshot(root/"MATERIALIZATION_RECEIPT.json","receipt"),"receipt")
    require(receipt.get("status")==STATUS,"receipt_status");require(receipt.get("oof_training_authorized") is False,"oof_flag")
    counts=receipt["counts"];require(counts["candidates"]==738 and counts["parents"]==53,"receipt_counts")
    require(counts["source_candidates"]==EXPECTED,"receipt_source_counts")
    access=receipt["access_boundary"]
    for field in ("development_pose_files_stat_hashed_opened","frozen_test_pose_files_stat_hashed_opened","quarantine_pose_files_stat_hashed_opened","unknown_pose_files_stat_hashed_opened","forbidden_pose_attempt_count"):
        require(access[field]==0,f"access_nonzero:{field}")
    for name,digest in receipt["outputs"].items():require(sha256_file(root/name)==digest,f"output_hash:{name}")
    sums=(root/"SHA256SUMS").read_text().splitlines();require(len(sums)==len(receipt["outputs"])+1,"sums_count")
    for line in sums:
        digest,name=line.split("  ",1);require(sha256_file(root/name)==digest,f"sums_hash:{name}")
    return {"status":"PASS_VERIFIED_TRAIN_ONLY_738_PACKAGE","package":str(root),"receipt_sha256":sha256_file(root/"MATERIALIZATION_RECEIPT.json"),"sha256sums_sha256":sha256_file(root/"SHA256SUMS")}


def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scalar-teacher",type=Path,required=True);p.add_argument("--split-manifest",type=Path,required=True)
    p.add_argument("--phase0-contract",type=Path,required=True);p.add_argument("--implementation-freeze",type=Path,required=True)
    p.add_argument("--v4d-pair",type=Path,required=True);p.add_argument("--v4d-marginal",type=Path,required=True);p.add_argument("--v4d-receipt",type=Path,required=True)
    p.add_argument("--v4h-pair",type=Path,required=True);p.add_argument("--v4h-marginal",type=Path,required=True);p.add_argument("--v4h-state",type=Path,required=True);p.add_argument("--v4h-receipt",type=Path,required=True)
    p.add_argument("--v29-release",type=Path,required=True);p.add_argument("--v29-pose-root",type=Path,required=True)
    p.add_argument("--target-cache",type=Path,required=True);p.add_argument("--target-manifest",type=Path,required=True);p.add_argument("--target-receipt",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--workers",type=int,default=8);p.add_argument("--verify-only",action="store_true")
    return p


def main(argv:Sequence[str]|None=None)->int:
    a=parser().parse_args(argv)
    if a.verify_only:result=verify_package(a.output_dir)
    else:result=materialize(scalar_teacher=a.scalar_teacher,split_manifest=a.split_manifest,phase0_contract=a.phase0_contract,implementation_freeze=a.implementation_freeze,v4d_pair=a.v4d_pair,v4d_marginal=a.v4d_marginal,v4d_receipt=a.v4d_receipt,v4h_pair=a.v4h_pair,v4h_marginal=a.v4h_marginal,v4h_state=a.v4h_state,v4h_receipt=a.v4h_receipt,v29_release=a.v29_release,v29_pose_root=a.v29_pose_root,target_cache=a.target_cache,target_manifest=a.target_manifest,target_receipt=a.target_receipt,output_dir=a.output_dir,workers=a.workers)
    print(json.dumps(result,sort_keys=True));return 0

if __name__=="__main__":raise SystemExit(main())

#!/usr/bin/env python3
"""Extract all frozen common4 poses for the QC397 V2 bridged Final50."""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,tarfile
from collections import defaultdict,Counter
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

SEEDS={"42","917","1931","3047"}; CONFS={"8x6b","9e6y"}

def read_tsv(p:Path):
    with p.open(newline="",encoding="utf-8-sig") as h:return list(csv.DictReader(h,delimiter="\t"))
def write_tsv(p:Path,rows:list[dict[str,Any]]):
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields:fields.append(k)
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("w",newline="",encoding="utf-8") as h:
        w=csv.DictWriter(h,fieldnames=fields,delimiter="\t",lineterminator="\n");w.writeheader();w.writerows(rows)
def sha_bytes(b:bytes):return hashlib.sha256(b).hexdigest()
def sha_file(p:Path):return hashlib.sha256(p.read_bytes()).hexdigest()
def member_key(member:tarfile.TarInfo,model:str):
    if not member.isfile():return None
    name=Path(member.name).name; a=model[:-3] if model.endswith('.gz') else model; b=name[:-3] if name.endswith('.gz') else name
    if a!=b:return None
    loc=0 if '/6_seletopclusts/' in member.name else 1 if '/selected_models/' in member.name else 2
    return (loc,int(name.endswith('.gz')),member.name)
def extract(archive_path:Path,model:str):
    with tarfile.open(archive_path,'r:*') as a:
        hits=[(k,m) for m in a.getmembers() if (k:=member_key(m,model)) is not None]
        if not hits:raise RuntimeError(f'model missing: {archive_path} {model}')
        _,m=sorted(hits,key=lambda x:x[0])[0]; h=a.extractfile(m)
        if h is None:raise RuntimeError(f'unreadable member: {m.name}')
        payload=h.read()
        if m.name.endswith('.gz') or payload[:2]==b'\x1f\x8b':payload=gzip.decompress(payload)
        return payload,m.name
def chain_set(b:bytes):
    return ''.join(sorted({x[21:22].decode('ascii') for x in b.splitlines() if x.startswith((b'ATOM  ',b'HETATM')) and len(x)>=22}))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--final50',type=Path,required=True);ap.add_argument('--top10',type=Path,required=True);ap.add_argument('--old-common4-jobs',type=Path,required=True);ap.add_argument('--generated-jobs',type=Path,required=True);ap.add_argument('--generated-archive-root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    if a.out.exists():raise SystemExit(f'output exists: {a.out}')
    all_final=sorted(read_tsv(a.final50),key=lambda r:int(r['final_rank']))
    top10=read_tsv(a.top10); top10_rank={r['candidate_id']:r['top10_rank'] for r in top10}
    final=all_final
    for r in final:
        r['top10_rank']=top10_rank.get(r['candidate_id'],'')
        rank=int(r['final_rank'])
        r['fusion_panel_membership']='FINAL_RANK_TOP20' if rank<=20 else 'FINAL50_EXPANSION'
    final_ids={r['candidate_id'] for r in final}
    if (
        len(top10)!=10
        or len(final)!=50
        or len(final_ids)!=len(final)
        or not set(top10_rank).issubset(final_ids)
    ):raise ValueError('Final50 panel invalid or current Top10 not fully covered')
    ids={r['candidate_id'] for r in final}
    old={}
    for r in read_tsv(a.old_common4_jobs):
        if r.get('candidate_id') in ids and r.get('state')=='SUCCESS':old[(r['candidate_id'],r['seed'],r['conformation'])]=r
    generated={}
    for r in read_tsv(a.generated_jobs):
        if r.get('candidate_id') in ids and r.get('state')=='SUCCESS':generated[(r['candidate_id'],r['seed'],r['conformation'])]=r
    pdbdir=a.out/'representative_complexes';pdbdir.mkdir(parents=True)
    manifest=[]
    for rankrow in final:
        cid=rankrow['candidate_id']; source=rankrow['source_cohort']
        table=generated if source=='generated_top3000' else old
        keys={(c,s,f) for c,s,f in table if c==cid}
        expected={(cid,s,c) for s in SEEDS for c in CONFS}
        if keys!=expected:raise ValueError(f'{cid}: common4 key mismatch missing={expected-keys} extra={keys-expected}')
        for seed in sorted(SEEDS,key=int):
            for conf in sorted(CONFS):
                row=table[(cid,seed,conf)]; model=row.get('representative_model','')
                if not model:raise ValueError(f'{cid}: missing representative model')
                archive=(a.generated_archive_root/f"{row['job_id']}.tar.gz") if source=='generated_top3000' else Path(row['archive_path'])
                if not archive.is_file():raise FileNotFoundError(archive)
                payload,member=extract(archive,model); chains=chain_set(payload)
                if not {'A','T'}.issubset(set(chains)):raise ValueError(f'{cid}: chains {chains}')
                short=cid if len(cid)<90 else cid.split('_source_',1)[0]
                out=pdbdir/f"R{int(rankrow['final_rank']):02d}__{short}__{conf}__s{seed}.pdb"
                out.write_bytes(payload)
                manifest.append({'final_rank':rankrow['final_rank'],'candidate_id':cid,'source_cohort':source,'route':rankrow['route'],'conformation':conf,'seed':seed,'state':'SUCCESS','representative_model':model,'pdb_path':str(out),'pdb_sha256':sha_bytes(payload),'archive_path':str(archive),'archive_member':member,'haddock_score':row.get('haddock_score',''),'representative_pair_label':row.get('representative_pair_label',''),'job_id':row['job_id'],'chain_set':chains})
    if len(manifest)!=len(final)*8:raise ValueError(len(manifest))
    counts=Counter(r['candidate_id'] for r in manifest)
    if set(counts.values())!={8}:raise ValueError('not 8 poses/candidate')
    panel=a.out/'final50_candidates.tsv';write_tsv(panel,final)
    mp=a.out/'representative_models_manifest.tsv';write_tsv(mp,manifest)
    receipt={'schema_version':'pvrig.qc397.final50.common4_bundle.v1','state':'COMPLETE','candidates':len(final),'poses':len(manifest),'primary_top20':sum(int(r['final_rank'])<=20 for r in final),'final50_expansion':sum(int(r['final_rank'])>20 for r in final),'current_top10_covered':len(set(top10_rank)&ids),'seeds':sorted(map(int,SEEDS)),'conformations':sorted(CONFS),'source_counts':dict(Counter(r['source_cohort'] for r in manifest)),'manifest_sha256':sha_file(mp),'panel_sha256':sha_file(panel),'input_sha256':{str(a.final50):sha_file(a.final50),str(a.top10):sha_file(a.top10),str(a.old_common4_jobs):sha_file(a.old_common4_jobs),str(a.generated_jobs):sha_file(a.generated_jobs)},'claim_boundary':'Frozen common4 docking poses only; no redocking and no experimental binding/blocking claim.','created_at':datetime.now(timezone.utc).isoformat()}
    (a.out/'BUNDLE_RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':main()

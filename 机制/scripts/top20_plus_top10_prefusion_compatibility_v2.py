#!/usr/bin/env python3
"""Narrow, construct-agnostic VHH C-terminal fusion compatibility audit.

It checks only what frozen VHH-PVRIG poses can support: C-terminal exposure and
clearance, a straight exit-ray obstruction proxy, VHH-side junction hydrophobicity,
and intradomain cysteine pairing/exposure. Fc collision, VHH-VHH collision and
bivalent reachability stay deferred until the organizer provides the exact
linker/hinge/Fc construct.
"""
from __future__ import annotations
import argparse,csv,hashlib,importlib.util,json,math,statistics,sys
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

HYDRO=set('AILMFWVY')
def read_tsv(p:Path):
    with p.open(newline='',encoding='utf-8-sig') as h:return list(csv.DictReader(h,delimiter='\t'))
def write_tsv(p:Path,rows:list[dict[str,Any]]):
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields:fields.append(k)
    with p.open('w',newline='',encoding='utf-8') as h:
        w=csv.DictWriter(h,fieldnames=fields,delimiter='\t',lineterminator='\n');w.writeheader();w.writerows(rows)
def sha(p:Path):return hashlib.sha256(p.read_bytes()).hexdigest()
def xyz(a):return (a.x,a.y,a.z)
def distance(a,b):return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))
def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def norm(v):
    n=math.sqrt(dot(v,v)); return tuple(x/n for x in v) if n else None
def median(vals):return statistics.median(vals) if vals else None
def fmt(x):return '' if x is None else f'{x:.6f}'
def max_run(s,allowed):
    best=cur=0
    for x in s:
        cur=cur+1 if x in allowed else 0;best=max(best,cur)
    return best

def load_module(path:Path):
    spec=importlib.util.spec_from_file_location('surface_sidecar',path)
    if spec is None or spec.loader is None:raise RuntimeError(path)
    m=importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules during execution.
    sys.modules[spec.name]=m
    spec.loader.exec_module(m)
    return m

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--final50',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--surface-module',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    if a.out.exists():raise SystemExit(f'output exists: {a.out}')
    a.out.mkdir(parents=True)
    mod=load_module(a.surface_module)
    final=sorted(read_tsv(a.final50),key=lambda r:int(r['final_rank'])); rows={r['candidate_id']:r for r in final}
    manifest=read_tsv(a.manifest)
    if len(final)<20 or len(manifest)!=len(final)*8:raise ValueError((len(final),len(manifest)))
    by=defaultdict(list)
    for m in manifest:by[m['candidate_id']].append(m)
    if set(by)!=set(rows) or set(map(len,by.values()))!={8}:raise ValueError('manifest is not fusion-panel × 8')
    poses=[]
    for cid,row in rows.items():
        seq=row['sequence']; tail=seq[-10:]
        for m in by[cid]:
            p=Path(m['pdb_path']);atoms,residues,order=mod.parse_pdb(p);seqs,chains=mod.chain_sequences(residues,order)
            vchain,observed,identity=mod.best_chain(seq,seqs);vkeys=chains[vchain];mapping=mod.global_map(seq,observed,vkeys)
            vatoms=[x for x in atoms if x.chain==vchain];target=[x for x in atoms if x.chain!=vchain]
            ckey=mapping.get(len(seq)-1); c_atoms=residues[ckey]['atoms'] if ckey else []
            terminal_sasa=mod.sasa(c_atoms,vatoms).get(ckey,0.0) if c_atoms else None
            c_min=mod.min_distance(c_atoms,target) if c_atoms else None
            named={x.name:x for x in c_atoms}; origin=xyz(named['C']) if 'C' in named else (xyz(named['CA']) if 'CA' in named else None)
            direction=None
            if 'C' in named and 'CA' in named:direction=norm(sub(xyz(named['C']),xyz(named['CA'])))
            if direction is None and len(vkeys)>=2:
                a1=next((x for x in residues[vkeys[-2]]['atoms'] if x.name=='CA'),None);a2=next((x for x in c_atoms if x.name=='CA'),None)
                if a1 and a2:origin=xyz(a2);direction=norm(sub(xyz(a2),xyz(a1)))
            ray_min=None;ray_hits=0;ray_severe=False
            if origin and direction:
                for atom in target:
                    rel=sub(xyz(atom),origin); t=dot(rel,direction)
                    if 0<=t<=35:
                        perp=math.sqrt(max(0.0,dot(rel,rel)-t*t))
                        ray_min=perp if ray_min is None else min(ray_min,perp)
                        if perp<=3.5:ray_hits+=1
                ray_severe=ray_min is not None and ray_min<=2.0
            cys_keys=[k for k in vkeys if residues[k]['aa']=='C']; cys_atoms=[x for k in cys_keys for x in residues[k]['atoms']]
            cys_sasa=mod.sasa(cys_atoms,vatoms) if cys_atoms else {}
            sg={k:next((x for x in residues[k]['atoms'] if x.name=='SG'),None) for k in cys_keys}
            paired=set();pair_dist=[]
            for i,k1 in enumerate(cys_keys):
                for k2 in cys_keys[i+1:]:
                    if sg[k1] and sg[k2]:
                        d=distance(xyz(sg[k1]),xyz(sg[k2]));pair_dist.append(d)
                        if d<=3.0:paired|={k1,k2}
            unpaired=[k for k in cys_keys if k not in paired]; exposed=[k for k in unpaired if cys_sasa.get(k,0)>=25.0]
            poses.append({'candidate_id':cid,'final_rank':row['final_rank'],'source_cohort':row['source_cohort'],'route':row['route'],'conformation':m['conformation'],'seed':m['seed'],'pdb_path':str(p),'chain_identity_proxy':fmt(identity),'c_terminal_residue_sasa_a2':fmt(terminal_sasa),'c_terminal_target_min_distance_a':fmt(c_min),'c_terminal_target_contact_4p5a':str(c_min is not None and c_min<=4.5),'exit_ray_35a_target_min_perpendicular_distance_a':fmt(ray_min),'exit_ray_target_atom_hits_3p5a':ray_hits,'exit_ray_severe_crossing_2a':str(ray_severe),'sequence_cys_count':seq.count('C'),'paired_cys_residue_count':len(paired),'unpaired_cys_residue_count':len(unpaired),'exposed_unpaired_cys_residue_count':len(exposed),'minimum_sg_pair_distance_a':fmt(min(pair_dist) if pair_dist else None),'vhh_c_terminal_tail_10aa':tail,'tail_hydrophobic_count':sum(x in HYDRO for x in tail),'tail_max_hydrophobic_run':max_run(tail,HYDRO)})
    candidates=[]
    for cid,row in rows.items():
        pp=[x for x in poses if x['candidate_id']==cid];seq=row['sequence']
        cterm=[float(x['c_terminal_residue_sasa_a2']) for x in pp if x['c_terminal_residue_sasa_a2']]
        cdist=[float(x['c_terminal_target_min_distance_a']) for x in pp if x['c_terminal_target_min_distance_a']]
        ray=[float(x['exit_ray_35a_target_min_perpendicular_distance_a']) for x in pp if x['exit_ray_35a_target_min_perpendicular_distance_a']]
        direct=sum(x['c_terminal_target_contact_4p5a']=='True' for x in pp); severe=sum(x['exit_ray_severe_crossing_2a']=='True' for x in pp); low=sum(float(x['c_terminal_residue_sasa_a2'] or 0)<15 for x in pp); exposed_unpaired=max(int(x['exposed_unpaired_cys_residue_count']) for x in pp)
        cys=seq.count('C');extra=max(0,cys-2);tail=seq[-10:];tail_h=sum(x in HYDRO for x in tail);tail_run=max_run(tail,HYDRO)
        hard=[];warn=[]
        if cys%2:hard.append('ODD_CYS_COUNT')
        if exposed_unpaired:hard.append('EXPOSED_UNPAIRED_CYS_IN_PREDICTED_VHH')
        if direct>=4 and low>=4:hard.append('C_TERMINUS_BURIED_AGAINST_TARGET_IN_HALF_OR_MORE_POSES')
        if direct and not hard:warn.append('C_TERMINUS_TARGET_CONTACT_IN_SOME_POSES')
        if severe>=4:warn.append('STRAIGHT_EXIT_RAY_INTERSECTS_TARGET_IN_HALF_OR_MORE_POSES')
        if low>=4:warn.append('LOW_C_TERMINAL_SOLVENT_EXPOSURE_IN_HALF_OR_MORE_POSES')
        if extra and not exposed_unpaired:warn.append('EXTRA_CYS_PREDICTED_INTRADOMAIN_PAIRED_REVIEW')
        if tail_h>=5 or tail_run>=3:warn.append('HYDROPHOBIC_VHH_SIDE_FUSION_TAIL')
        grade='F3_HARD_FAIL' if hard else ('F2_REVIEW' if warn else 'F1_CLEAR_NARROW_PRECHECK')
        candidates.append({'final_rank':row['final_rank'],'candidate_id':cid,'source_cohort':row['source_cohort'],'route':row['route'],'pose_count':len(pp),'minimum_c_terminal_target_distance_a':fmt(min(cdist) if cdist else None),'median_c_terminal_residue_sasa_a2':fmt(median(cterm)),'low_c_terminal_sasa_pose_count_lt15a2':low,'c_terminal_target_contact_pose_count':direct,'minimum_exit_ray_target_distance_a':fmt(min(ray) if ray else None),'exit_ray_severe_crossing_pose_count':severe,'sequence_cys_count':cys,'extra_cys_count_beyond_two':extra,'max_exposed_unpaired_cys_count':exposed_unpaired,'vhh_side_fusion_tail_10aa':tail,'tail_hydrophobic_count':tail_h,'tail_max_hydrophobic_run':tail_run,'prefusion_compatibility_grade':grade,'fusion_hard_fail':str(bool(hard)).lower(),'fusion_hard_fail_reasons':';'.join(hard),'fusion_tie_breaker_warnings':';'.join(warn),'fc_target_collision_status':'DEFERRED_EXACT_LINKER_HINGE_FC_REQUIRED','vhh_vhh_collision_status':'DEFERRED_EXACT_DIMER_CONSTRUCT_REQUIRED','both_vhh_arms_exposed_status':'DEFERRED_EXACT_DIMER_CONSTRUCT_REQUIRED','bivalent_binding_geometry_status':'DEFERRED_EXACT_DIMER_CONSTRUCT_REQUIRED','fusion_junction_status':'VHH_SIDE_ONLY__LINKER_SIDE_DEFERRED','rank_use':'HARD_FAIL_PLUS_TIE_BREAKER_ONLY','claim_boundary':'Narrow prefusion geometry/cysteine proxy from frozen poses; not a full VHH-hFc model, expression, purity, aggregation, affinity, avidity, or blocking result.'})
    candidates.sort(key=lambda x:int(x['final_rank']));poses.sort(key=lambda x:(int(x['final_rank']),int(x['seed']),x['conformation']))
    pp=a.out/'Top20_prefusion_pose_audit.tsv';cp=a.out/'Top20_prefusion_candidate_audit.tsv';write_tsv(pp,poses);write_tsv(cp,candidates)
    receipt={'schema_version':'pvrig.qc397.top20_plus_top10.prefusion_compatibility.v2','state':'COMPLETE_WITH_FULL_CONSTRUCT_DEFERRED','candidates':len(final),'poses':len(poses),'grade_counts':dict(Counter(x['prefusion_compatibility_grade'] for x in candidates)),'hard_fail_count':sum(x['fusion_hard_fail']=='true' for x in candidates),'full_construct_available':False,'deferred_checks':['Fc-PVRIG collision','Fc-other-VHH collision','both VHH arms exposed','bivalent geometry','complete junction hydrophobicity','hinge/Fc engineered cysteines'],'input_sha256':{str(a.final50):sha(a.final50),str(a.manifest):sha(a.manifest),str(a.surface_module):sha(a.surface_module)},'output_sha256':{pp.name:sha(pp),cp.name:sha(cp)},'claim_boundary':'Hard fail and tie-breaker precheck only; exact full-format questions remain deferred until organizer construct disclosure.','created_at':datetime.now(timezone.utc).isoformat()}
    (a.out/'PREFUSION_RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':main()

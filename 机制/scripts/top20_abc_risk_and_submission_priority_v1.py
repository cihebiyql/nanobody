#!/usr/bin/env python3
"""Assign categorical A/B/C computational risk grades and a Top10 sidecar.

No continuous expression/purity score is created. Mechanism rank is immutable.
A/B/C is a risk triage; full VHH-hFc format remains incomplete until the exact
organizer construct is disclosed.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,re
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

def read_tsv(p:Path,key=None):
    with p.open(newline='',encoding='utf-8-sig') as h:r=list(csv.DictReader(h,delimiter='\t'))
    return {x[key]:x for x in r} if key else r
def write_tsv(p:Path,rows:list[dict[str,Any]]):
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields:fields.append(k)
    with p.open('w',newline='',encoding='utf-8') as h:
        w=csv.DictWriter(h,fieldnames=fields,delimiter='\t',lineterminator='\n');w.writeheader();w.writerows(rows)
def sha(p:Path):return hashlib.sha256(p.read_bytes()).hexdigest()
def b(x):return str(x).strip().lower() in {'true','1','yes','pass'}
def f(x,default=None):
    try:return float(x)
    except:return default
def i(x,default=0):
    try:return int(float(x))
    except:return default
def direct_id(a,b):return sum(x==y for x,y in zip(a,b))/len(a) if a and len(a)==len(b) else 0.0

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--final50',type=Path,required=True);ap.add_argument('--old-common4',type=Path,required=True);ap.add_argument('--generated-qc',type=Path,required=True);ap.add_argument('--generated-vhh',type=Path,required=True);ap.add_argument('--structure',type=Path,required=True);ap.add_argument('--prefusion',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    if a.out.exists():raise SystemExit(f'output exists: {a.out}')
    a.out.mkdir(parents=True)
    final=sorted(read_tsv(a.final50),key=lambda r:int(r['final_rank']))[:20]
    old=read_tsv(a.old_common4,'candidate_id');gen=read_tsv(a.generated_qc,'candidate_id');vhh=read_tsv(a.generated_vhh,'id');struct=read_tsv(a.structure,'candidate_id');fusion=read_tsv(a.prefusion,'candidate_id')
    ids={r['candidate_id'] for r in final}
    if len(final)!=20 or set(struct)!=ids or set(fusion)!=ids:raise ValueError('Top20 sidecar membership mismatch')
    grades=[]
    for row in final:
        cid=row['candidate_id']; isgen=row['source_cohort']=='generated_top3000'; src=gen[cid] if isgen else old[cid]; vr=vhh.get(cid,{})
        suitability=(src.get('single_domain_suitability') or '').lower()
        ab=f(src.get('abnativ_vhh_score_fullqc') or src.get('AbNatiV_VHH_score') or vr.get('AbNatiV_VHH_score'))
        sapiens=f(src.get('sapiens_mean_self_probability_fullqc') or src.get('Sapiens_mean_self_probability'))
        cys=row['sequence'].count('C')
        # vhh_eval's ``unpaired_cys_possible_count`` is a sequence-only listing
        # of every cysteine and therefore equals 2 for canonical VHHs.  It is
        # not evidence that the conserved intradomain disulfide is unpaired.
        # Use the sequence count plus the 8-pose structural pairing audit.
        unusual=(cys!=2) if isgen else b(src.get('has_unusual_cysteine'))
        ng=i(vr.get('nglyc_motif_count')) if isgen else i(src.get('nglyc_motif_count') or (1 if b(src.get('has_N_glycosylation_motif')) else 0))
        hydro5=i(vr.get('hydrophobic_5_count')) if isgen else i(src.get('hydrophobic_5_count'))
        instability=f(vr.get('instability_index') if isgen else src.get('instability_index'))
        if isgen:
            red=i(src.get('upstream_tnp_red_flag_count'));amber=i(src.get('upstream_tnp_amber_flag_count'))
            conservative=(suitability=='good' and ab is not None and ab>=0.70 and sapiens is not None and sapiens>=0.70 and red==0 and cys==2 and ng==0 and hydro5==0)
        else:
            flags=(src.get('TNP_flags') or '').lower().split('/')
            red=sum(x=='red' for x in flags);amber=sum(x=='amber' for x in flags);conservative=b(src.get('developability_conservative_pass'))
        cdr=''.join((row.get('cdr1',''),row.get('cdr2',''),row.get('cdr3','')));cdr_ng=bool(re.search(r'N[^P][ST]',cdr))
        st=struct[cid];fu=fusion[cid];patch_n=f(st.get('median_largest_hydrophobic_patch_residues'),0) or 0;patch_area=f(st.get('median_largest_hydrophobic_patch_free_sasa_a2'),0) or 0
        acid=i(st.get('exposed_noncontact_acid_clipping_rows'));fgrade=fu['prefusion_compatibility_grade']
        hard=[];warn=[]
        if fgrade=='F3_HARD_FAIL':hard.append('PREFUSION_HARD_FAIL:'+fu.get('fusion_hard_fail_reasons',''))
        if suitability in {'poor','not_vhh_like'}:hard.append('NOT_VHH_LIKE_OR_POOR_SINGLE_DOMAIN')
        if cys%2:hard.append('ODD_CYS_COUNT')
        if unusual:hard.append('UNEXPLAINED_CYS_SEQUENCE_RISK')
        if cdr_ng:hard.append('CDR_N_GLYCOSYLATION_MOTIF')
        if hydro5>0:hard.append('HYDROPHOBIC_RUN_5')
        if patch_n>=20 and patch_area>=1000:hard.append('EXTREME_SURFACE_HYDROPHOBIC_PATCH')
        if red>=2:hard.append('MULTIPLE_TNP_RED_FLAGS')
        if suitability=='borderline':warn.append('BORDERLINE_SINGLE_DOMAIN')
        if ab is not None and ab<0.70:warn.append('ABNATIV_BELOW_0P70')
        if sapiens is not None and sapiens<0.70:warn.append('SAPIENS_BELOW_0P70')
        if not conservative:warn.append('CONSERVATIVE_GATE_NOT_CLEAR')
        if red==1:warn.append('ONE_TNP_RED_FLAG')
        if amber>0:warn.append(f'TNP_AMBER_{amber}')
        if patch_n>=15 or patch_area>=900:warn.append('ELEVATED_SURFACE_HYDROPHOBIC_PATCH')
        if acid>=4:warn.append('EXPOSED_ACID_CLIPPING_MOTIF_MULTI_POSE')
        if instability is not None and instability>=40:warn.append('INSTABILITY_INDEX_REVIEW')
        if fgrade=='F2_REVIEW':warn.append('PREFUSION_REVIEW:'+fu.get('fusion_tie_breaker_warnings',''))
        grade='C_HIGH_RISK' if hard else ('B_REVIEW' if warn else 'A_LOWER_RISK')
        grades.append({'final_rank':row['final_rank'],'current_top10_rank':row.get('top10_rank',''),'candidate_id':cid,'source_cohort':row['source_cohort'],'route':row['route'],'parent_cluster':row['parent_cluster'],'cdr3':row['cdr3'],'mechanism_rank_immutable':row['final_rank'],'developability_grade':grade,'developability_hard_fail':str(bool(hard)).lower(),'hard_fail_reasons':';'.join(hard),'review_reasons':';'.join(warn),'single_domain_suitability':suitability,'abnativ_vhh_score_for_threshold': '' if ab is None else f'{ab:.6f}','sapiens_probability_for_threshold':'' if sapiens is None else f'{sapiens:.6f}','conservative_gate_clear':str(conservative).lower(),'sequence_cys_count':cys,'unusual_or_unexplained_cys':str(unusual).lower(),'cdr_nglyc_motif':str(cdr_ng).lower(),'hydrophobic_5_count':hydro5,'tnp_red_count':red,'tnp_amber_count':amber,'instability_index_for_review':'' if instability is None else f'{instability:.3f}','median_largest_hydrophobic_patch_residues':st.get('median_largest_hydrophobic_patch_residues',''),'median_largest_hydrophobic_patch_free_sasa_a2':st.get('median_largest_hydrophobic_patch_free_sasa_a2',''),'prefusion_compatibility_grade':fgrade,'fusion_hard_fail':fu['fusion_hard_fail'],'full_hfc_construct_status':'NOT_DISCLOSED__FULL_FORMAT_CHECK_DEFERRED','risk_data_completeness':'SEQUENCE_PLUS_8POSE_PREFUSION__NO_EXPERIMENTAL_YIELD_PURITY_SEC_TM','rank_use':'C_HARD_EXCLUDE; A_OVER_B_TIE_BREAK; DO_NOT_CHANGE_MECHANISM_RANK','claim_boundary':'Categorical computational risk triage only; not actual expression, purity, SEC monomer, Tm, aggregation, BLI, Kd, IC50, avidity, or blocking.'})
    # Portfolio: 8 A first under diversity caps, then at most 2 high-mechanism B.
    A=[r for r in grades if r['developability_grade']=='A_LOWER_RISK'];B=[r for r in grades if r['developability_grade']=='B_REVIEW'];C=[r for r in grades if r['developability_grade']=='C_HIGH_RISK']
    for pool in (A,B,C):pool.sort(key=lambda r:int(r['final_rank']))
    selected=[];parents=Counter();routes=Counter()
    def allowed(r):return parents[r['parent_cluster']]<4 and routes[r['route']]<7 and all(direct_id(r['cdr3'],x['cdr3'])<0.80 for x in selected)
    def add(r,role):
        q=dict(r);q['competition_top10_role']=role;selected.append(q);parents[r['parent_cluster']]+=1;routes[r['route']]+=1
    for r in A:
        if len(selected)>=8:break
        if allowed(r):add(r,'A_PRIMARY')
    for r in B:
        if len(selected)>=10:break
        if allowed(r):add(r,'B_HIGH_MECHANISM_LIMITED')
    for r in A:
        if len(selected)>=10:break
        if r['candidate_id'] not in {x['candidate_id'] for x in selected} and allowed(r):add(r,'A_DIVERSITY_BACKFILL')
    if len(selected)<10:
        for r in B:
            if len(selected)>=10:break
            if r['candidate_id'] not in {x['candidate_id'] for x in selected} and allowed(r):add(r,'B_LIMITED_BACKFILL')
    if len(selected)!=10:raise ValueError(f'could only select {len(selected)} non-C Top10')
    for n,r in enumerate(selected,1):r['competition_submission_priority']=n
    grade_path=a.out/'Top20_expression_purity_risk_grades.tsv';priority_path=a.out/'Top10_competition_priority_after_fusion_developability.tsv';write_tsv(grade_path,grades);write_tsv(priority_path,selected)
    receipt={'schema_version':'pvrig.qc397.top20.abc_risk_and_top10_priority.v1','state':'COMPLETE','top20_count':20,'grade_counts':dict(Counter(r['developability_grade'] for r in grades)),'top10_grade_counts':dict(Counter(r['developability_grade'] for r in selected)),'top10_candidate_ids':[r['candidate_id'] for r in selected],'mechanism_rank_changed':False,'full_hfc_construct_available':False,'rules':{'C_hard':['prefusion hard fail','poor/not-VHH-like','odd/unexplained Cys','CDR N-glyc','hydrophobic run 5','hydrophobic patch >=20 residues and >=1000 A2','>=2 TNP red'],'B_review':['borderline VHH','AbNatiV<0.70','Sapiens<0.70','conservative gate not clear','one TNP red/any amber','patch >=15 residues or >=900 A2','multi-pose exposed DP','instability index >=40','prefusion review'],'portfolio':'8 A primary, max 2 B high-mechanism; C excluded; parent cap 4; route cap 7; direct CDR3 identity <0.80'},'input_sha256':{str(p):sha(p) for p in [a.final50,a.old_common4,a.generated_qc,a.generated_vhh,a.structure,a.prefusion]},'output_sha256':{grade_path.name:sha(grade_path),priority_path.name:sha(priority_path)},'claim_boundary':'Risk categories and portfolio policy, not a continuous predicted Yield/purity or experimental activity score.','created_at':datetime.now(timezone.utc).isoformat()}
    (a.out/'ABC_PRIORITY_RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':main()

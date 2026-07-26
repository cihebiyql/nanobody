#!/usr/bin/env python3
"""Join Final50 mechanism ranks with non-ranking manufacturability sidecars."""
from __future__ import annotations
import argparse,csv,hashlib,json,sys
from pathlib import Path

def read_tsv(p): return list(csv.DictReader(open(p),delimiter='\t'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--final50',required=True); ap.add_argument('--top10',required=True); ap.add_argument('--audit',required=True); ap.add_argument('--tnp-json',required=True); ap.add_argument('--structure',required=True); ap.add_argument('--format-assessment',required=True); ap.add_argument('--outdir',required=True); a=ap.parse_args()
 out=Path(a.outdir); out.mkdir(parents=True,exist_ok=False)
 final=read_tsv(a.final50); top10=read_tsv(a.top10); audit=read_tsv(a.audit); struct=read_tsv(a.structure)
 assert len(final)==50 and len({x['candidate_id'] for x in final})==50
 assert len(top10)==10 and len({x['candidate_id'] for x in top10})==10
 ad={x['candidate_id']:x for x in audit}; sd={x['candidate_id']:x for x in struct}; t10={x['candidate_id']:x for x in top10}
 if set(ad)!=set(x['candidate_id'] for x in final): raise SystemExit('audit membership mismatch')
 if set(sd)!=set(x['candidate_id'] for x in final): raise SystemExit('structure membership mismatch')
 tnp=json.load(open(a.tnp_json));
 if set(tnp)!=set(x['candidate_id'] for x in final): raise SystemExit(f'TNP membership mismatch: {len(tnp)}')
 fmt=json.load(open(a.format_assessment));
 rows=[]
 for f in sorted(final,key=lambda x:int(x['final_rank'])):
  cid=f['candidate_id']; q=ad[cid]; s=sd[cid]; t=tnp[cid]; flags=t.get('Flags',{})
  if set(flags)!= {'L','L3','C','PSH','PPC','PNC'}: raise SystemExit(f'Incomplete TNP flags: {cid}')
  tnp_status='COMPLETE_ALL_GREEN' if all(v.lower()=='green' for v in flags.values()) else 'COMPLETE_REVIEW'
  top=t10.get(cid,{}); tr=top.get('top10_rank','')
  cterm=int(s['c_terminal_contact_pose_count'])
  if cterm:
   format_status='REVIEW_C_TERMINAL_TARGET_CONTACT'
  elif tr in {'2','10'}:
   format_status='C_TERMINAL_CLEAR__GENERIC_HFC_PILOT_INCONCLUSIVE'
  elif tr:
   format_status='C_TERMINAL_CLEAR__NO_FULL_HFC_MODEL'
  else:
   format_status='NOT_TOP10__C_TERMINAL_CLEAR'
  structural=s['structural_ptm_review_status']
  review=[]
  if q.get('developability_proxy_tier')!='D1_LOWER_RISK_PROXY': review.append(q.get('developability_proxy_tier',''))
  if tnp_status!='COMPLETE_ALL_GREEN': review.append('TNP_COMPONENT_REVIEW')
  if structural!='NO_HIGH_STRUCTURAL_FLAG': review.append(structural)
  if 'INCONCLUSIVE' in format_status: review.append('GENERIC_HFC_LOW_CONFIDENCE')
  rows.append({
   'final_rank':f['final_rank'],'top10_rank':tr,'candidate_id':cid,'parent_id':f.get('parent_id',''),
   'mechanism_rank_semantics':'frozen common4 dual-conformation computational mechanism rank; unchanged by this sidecar',
   'manufacturability_proxy_tier':q.get('developability_proxy_tier',''),'prior_proxy_risk_reasons':q.get('proxy_risk_reasons',''),
   'tnp_component_evidence_completeness':'COMPLETE_PATCHED_ALL50','tnp_L':flags['L'],'tnp_L3':flags['L3'],'tnp_C':flags['C'],'tnp_PSH':flags['PSH'],'tnp_PPC':flags['PPC'],'tnp_PNC':flags['PNC'],'tnp_status':tnp_status,
   'tnp_total_cdr_length':t.get('Total CDR Length',''),'tnp_cdr3_length':t.get('CDR3 Length',''),'tnp_cdr3_compactness':t.get('CDR3 Compactness',''),'tnp_psh':t.get('PSH',''),'tnp_ppc':t.get('PPC',''),'tnp_pnc':t.get('PNC',''),
   'median_largest_hydrophobic_patch_residues':s['median_largest_hydrophobic_patch_residues'],'median_largest_hydrophobic_patch_free_sasa_a2':s['median_largest_hydrophobic_patch_free_sasa_a2'],'median_largest_positive_patch_residues':s['median_largest_positive_patch_residues'],'median_largest_negative_patch_residues':s['median_largest_negative_patch_residues'],
   'minimum_c_terminal_target_distance_a':s['minimum_c_terminal_target_distance_a'],'c_terminal_contact_pose_count':s['c_terminal_contact_pose_count'],'exposed_noncontact_acid_clipping_rows':s['exposed_noncontact_acid_clipping_rows'],'exposed_noncontact_isomerization_rows':s['exposed_noncontact_isomerization_rows'],'structural_ptm_review_status':structural,
   'format_review_status':format_status,'additional_review_flags':';'.join(x for x in review if x),
   'claim_boundary':'Non-ranking computational manufacturability/format sidecar. It does not predict CHO yield, SDS/HPLC purity, SEC, aggregation, Protein-A low-pH outcome, BLI, Kd, IC50, or experimental blocking.'
  })
 keys=list(rows[0]);
 with (out/'FINAL50_MANUFACTURABILITY_SIDECAR.tsv').open('w',newline='') as h:
  w=csv.DictWriter(h,fieldnames=keys,delimiter='\t');w.writeheader();w.writerows(rows)
 # Top10 experiment-dispatch groups intentionally preserve, rather than overwrite, mechanism rank.
 groups={'1':'MECHANISM_STRONG_MANUFACTURING_REVIEW','2':'FIRST_CORE_D1','3':'SECOND_LAYER_D2','4':'SECOND_LAYER_D2','5':'MECHANISM_STRONG_MANUFACTURING_REVIEW','6':'FIRST_CORE_D1','7':'FIRST_CORE_D1','8':'HIGH_RISK_FORMAT_CONTROL','9':'PARENT_DIVERSITY_D1','10':'HIGH_RISK_FORMAT_CONTROL'}
 top=[r for r in rows if r['top10_rank']]
 for r in top:r['recommended_experimental_group']=groups[r['top10_rank']]
 with (out/'TOP10_EXPERIMENT_DISPATCH_SIDECAR.tsv').open('w',newline='') as h:
  w=csv.DictWriter(h,fieldnames=list(top[0]));w.writeheader();w.writerows(sorted(top,key=lambda x:int(x['top10_rank'])))
 receipt={'schema_version':'pvrig.final50.manufacturability_sidecar.v1','state':'COMPLETE','candidates':50,'top10':10,'tnp_complete_all50':True,'mechanism_rank_changed':False,'format_pilot_state':fmt['state'],'format_pilot_decision':fmt['decision'],'input_sha256':{str(Path(x)):sha(x) for x in [a.final50,a.top10,a.audit,a.tnp_json,a.structure,a.format_assessment]},'claim_boundary':'No experimental manufacturing/binding/blocking claim; no predicted official score.'}
 (out/'FINAL50_MANUFACTURABILITY_SIDECAR_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
 print(json.dumps(receipt))
if __name__=='__main__':main()

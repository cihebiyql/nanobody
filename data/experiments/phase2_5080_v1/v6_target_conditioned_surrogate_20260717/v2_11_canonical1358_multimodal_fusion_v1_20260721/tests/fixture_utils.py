from __future__ import annotations
import csv,hashlib,json
from pathlib import Path
import numpy as np, torch

AA="ACDEFGHIKLMNPQRSTVWY"

def sha(path:Path)->str:
 h=hashlib.sha256();h.update(path.read_bytes());return h.hexdigest()
def parent_hash(values):return hashlib.sha256(("\n".join(sorted(values))+"\n").encode()).hexdigest()
def write_tsv(path,rows):
 with path.open('w',newline='') as h:
  w=csv.DictWriter(h,fieldnames=list(rows[0]),delimiter='\t',lineterminator='\n');w.writeheader();w.writerows(rows)
def make_cache(root:Path, rows, embeddings)->Path:
 cache=root/'cache650';shards=cache/'shards';shards.mkdir(parents=True)
 shard=shards/'shard_00000.pt';torch.save({'metadata':{'candidate_ids':[r['candidate_id'] for r in rows]+['EXTRA'],'sequence_sha256':[r['sequence_sha256'] for r in rows]+['f'*64]},'embeddings':torch.tensor(np.vstack([embeddings,np.zeros((1,embeddings.shape[1]))]),dtype=torch.float32)},shard)
 (cache/'embedding_cache_receipt.json').write_text(json.dumps({'schema_version':'pvrig_v6_esm_embedding_cache_v1','rows':len(rows)+1,'shards':[{'path':str(shard),'sha256':sha(shard)}]}))
 return cache

def fixture(root:Path,n_parents=10,per_parent=6):
 rng=np.random.default_rng(7);rows=[];struct=[];coarse=[];emb=[]
 sf=[f'REG{i:03d}__feature' for i in range(126)]
 c2=['8x6b__pose_count','9e6y__pose_count','8x6b__top20_score_entropy','9e6y__top20_score_entropy']+[f'dual__feature_{i:02d}' for i in range(32)]
 for i in range(n_parents*per_parent):
  parent=f'P{i//per_parent:02d}';a=AA[i%20];b=AA[(i//20)%20];c=AA[(i//400)%20]
  cdr1='ACDE'+a;cdr2='FGHI'+b;cdr3='KLMNPQ'+a+b+c
  seq='QVQLVESGGGLVQSGGSLRLSCAAS'+cdr1+'WYRQAPGKERELVA'+cdr2+'RFTISRDFSRSTMYLQMNSLKPEDTAIYYCAA'+cdr3+'WGQGTQVTVSS'
  vector=rng.normal(size=126);pose=rng.normal(size=36);embedding=rng.normal(size=20)
  signal=.6*vector[0]+.25*pose[4]+.15*embedding[0];signal9=.55*vector[1]+.25*pose[5]+.2*embedding[1]
  r8=.52+.055*np.tanh(signal);r9=.515+.055*np.tanh(signal9)
  cid=f'C{i:04d}';seqsha=hashlib.sha256(seq.encode()).hexdigest()
  rows.append({'candidate_id':cid,'sequence_sha256':seqsha,'sequence':seq,'parent_framework_cluster':parent,'cdr1':cdr1,'cdr2':cdr2,'cdr3':cdr3,'sample_weight':'1','R_8X6B':f'{r8:.9f}','R_9E6Y':f'{r9:.9f}','R_dual_min':f'{min(r8,r9):.9f}','teacher_source':'V4D' if i<18 else 'V4H','teacher_reliability':'MULTI_SEED' if i<18 else 'DUAL_1_SEED'})
  sr={'schema_version':'fixture','candidate_id':cid,'sequence_sha256':seqsha,'parent_framework_cluster':parent,'monomer_sha256':hashlib.sha256((cid+'pdb').encode()).hexdigest(),'claim_boundary':'fixture'};sr.update({name:f'{value:.9f}' for name,value in zip(sf,vector)});struct.append(sr)
  cr={'candidate_id':cid,'monomer_sha256':sr['monomer_sha256'],'feature_schema':'fixture'};cr.update({name:f'{value:.9f}' for name,value in zip(c2,pose)});coarse.append(cr);emb.append(embedding)
 teacher=root/'teacher.tsv';write_tsv(teacher,rows);train=[f'P{i:02d}' for i in range(n_parents-2)];dev=[f'P{i:02d}' for i in range(n_parents-2,n_parents)];frozen=['P90']
 split=root/'split.json';split.write_text(json.dumps({'schema_version':'pvrig_v2_9_whole_parent_split_v1','data_version':'D1','split_id':'fixture','open_only':True,'frozen_test_access_count':0,'sealed_truth_access_count':0,'training_tsv_sha256':sha(teacher),'train_parents':train,'score_parents':dev,'frozen_test_parents':frozen,'train_parent_set_sha256':parent_hash(train),'score_parent_set_sha256':parent_hash(dev),'frozen_test_parent_set_sha256':parent_hash(frozen)}))
 s4=root/'s4.tsv';sh=root/'sh.tsv';write_tsv(s4,struct[:len(struct)//2]);write_tsv(sh,struct[len(struct)//2:]);cp=root/'c2.tsv';write_tsv(cp,coarse);cache=make_cache(root,rows,np.asarray(emb))
 return {'rows':rows,'teacher':teacher,'split':split,'s4':s4,'sh':sh,'c2':cp,'cache':cache,'train_rows':(n_parents-2)*per_parent,'dev_rows':2*per_parent}

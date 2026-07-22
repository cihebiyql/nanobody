import pandas as pd,numpy as np,math,json
from pathlib import Path
from scipy.stats import rankdata,spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier
base=Path('experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/v2_13_top5_enrichment_v1_20260722/inputs')
mods=['S0','M2','C2','B']
train=pd.read_csv(base/'TRAIN_INNER_OOF_PREDICTIONS.tsv',sep='\t').merge(pd.read_csv(base/'CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv',sep='\t')[['candidate_id','fold_id','B_CLEAN_TARGET_ATTENTION__R8','B_CLEAN_TARGET_ATTENTION__R9','B_CLEAN_TARGET_ATTENTION__Rdual_exact_min']],on='candidate_id',validate='one_to_one')
dev=pd.read_csv(base/'OPEN_DEVELOPMENT_PORTFOLIO_PREDICTIONS.tsv',sep='\t')
pref_t={'S0':'S0_MATCHED_ESM2_650M_PCA_ELASTICNET','M2':'M2_STRUCTURE_ALPHA10','C2':'C2_COARSE_POSE_PCA8','B':'B_CLEAN_TARGET_ATTENTION'}
pref_d={k:k for k in mods}
def arrays(df,pref,truth):
 raw=np.column_stack([df[pref[k]+'__Rdual_exact_min'] for k in mods]); r8=np.column_stack([df[pref[k]+'__R8'] for k in mods]); r9=np.column_stack([df[pref[k]+'__R9'] for k in mods]); gaps=np.abs(r8-r9); ranks=np.column_stack([(rankdata(raw[:,j])-1)/(len(df)-1) for j in range(4)])
 X=np.column_stack([raw,r8,r9,gaps,ranks,raw.mean(1),raw.std(1),ranks.mean(1),ranks.std(1),ranks.min(1),np.median(ranks,1),np.sort(ranks,axis=1)[:,1:].mean(1),(ranks>=.95).sum(1),(ranks>=.90).sum(1)])
 y=df[truth].to_numpy(); ids=df.candidate_id.astype(str).to_numpy(); parents=df.parent_framework_cluster.astype(str).to_numpy(); return X,y,ids,parents,ranks
Xt,yt,idt,pt,rt=arrays(train,pref_t,'truth_Rdual_exact_min'); Xd,yd,idd,pd,rd=arrays(dev,pref_d,'truth_Rdual_exact_min'); folds=train.fold_id.astype(str).to_numpy()
def metric(y,s,ids):
 n=len(y); k=max(1,math.ceil(.05*n)); p=max(1,math.ceil(.1*n)); io=np.lexsort((ids,-y)); so=np.lexsort((ids,-s)); h=len(set(io[:p])&set(so[:k])); return {'n':n,'k':k,'positives':p,'hits':h,'precision':h/k,'recall':h/p,'ef':h/k/(p/n),'rho':float(spearmanr(y,s).statistic)}
def fit(tr):
 threshold=np.sort(yt[tr])[-max(1,math.ceil(.1*len(tr)))]; lab=(yt[tr]>=threshold).astype(int); unique,counts=np.unique(pt[tr],return_counts=True); count_by=dict(zip(unique,counts)); w=np.array([1/count_by[p] for p in pt[tr]],float); w/=w.mean(); q=lab.mean(); w[lab==1]*=.5/q; w[lab==0]*=.5/(1-q)
 m=HistGradientBoostingClassifier(max_iter=128,learning_rate=.05,max_depth=3,min_samples_leaf=128,l2_regularization=5.,random_state=43); m.fit(Xt[tr],lab,sample_weight=w); return m
scores=np.zeros(len(train))
fold_metrics=[]
for f in sorted(set(folds)):
 tr=np.flatnonzero(folds!=f); te=np.flatnonzero(folds==f); model=fit(tr); scores[te]=model.predict_proba(Xt[te])[:,1]; fold_metrics.append(metric(yt[te],scores[te],idt[te]))
# fold-normalize HGB probability and mean base ranks, matching real cohort rank normalization
hgb_rank=np.zeros(len(train)); mean_rank=np.zeros(len(train))
for f in sorted(set(folds)):
 ix=np.flatnonzero(folds==f); hgb_rank[ix]=(rankdata(scores[ix])-1)/(len(ix)-1); mean_rank[ix]=rt[ix].mean(1)
model=fit(np.arange(len(train))); dev_hgb=model.predict_proba(Xd)[:,1]; dev_hgb_rank=(rankdata(dev_hgb)-1)/(len(dev_hgb)-1); dev_mean=rd.mean(1)
out={'schema':'v213_fixed_hgb_descriptive_v1','fixed_hgb':{'max_iter':128,'lr':.05,'depth':3,'min_leaf':128,'l2':5.,'seed':43},'oof':{'HGB':metric(yt,hgb_rank,idt),'MEAN4':metric(yt,mean_rank,idt),'fold_HGB':fold_metrics},'dev':{'HGB':metric(yd,dev_hgb_rank,idd),'MEAN4':metric(yd,dev_mean,idd)}}
for w in (.25,.5,.75):
 name=f'BLEND_HGB_{w:.2f}'
 out['oof'][name]=metric(yt,w*hgb_rank+(1-w)*mean_rank,idt)
 out['dev'][name]=metric(yd,w*dev_hgb_rank+(1-w)*dev_mean,idd)
print(json.dumps(out,indent=2,sort_keys=True))

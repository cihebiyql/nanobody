#!/usr/bin/env python3
"""Strict expanded-signal hard-negative reranking for EF@5%."""
from __future__ import annotations
import argparse,csv,importlib.util,json,math,os,pickle,shutil,sys,tempfile
from pathlib import Path
from typing import Any,Mapping,Sequence
import numpy as np

HERE=Path(__file__).resolve().parent
P=HERE.parents[1]/"v2_15_raw_multimodal_top5_v1_20260722"/"src"/"run_v215_raw_multimodal_top5_oof_v1.py"
S=importlib.util.spec_from_file_location("v215_core_for_v217",P)
if S is None or S.loader is None:raise RuntimeError("import")
V215=importlib.util.module_from_spec(S);sys.modules[S.name]=V215;S.loader.exec_module(V215)

SCHEMA="pvrig_v2_17_expanded_union_top5_oof_v1";CONTRACT_SCHEMA="pvrig_v2_17_expanded_union_top5_contract_v1"
METHODS=("E0_L1","E1_EQUAL_RANK8","E2_HGB_U20","E3_EXTRA_U20","E4_HGB_U30","E5_EXTRA_U30","E6_U20_MEAN","E7_U20_L1_BLEND")
class Error(RuntimeError):pass
def require(c:bool,m:str)->None:
 if not c:raise Error(m)

def rows(path:Path)->dict[str,dict[str,str]]:
 _,x=V215.read_tsv(path);r={v["candidate_id"]:v for v in x};require(len(r)==len(x),f"duplicate:{path}");return r

def load_signals(data:dict[str,Any],paths:Sequence[Path])->None:
 names=("G3","N1","N2","N3");columns=(("G3_HGB_R8R9_RAW__frontscreen_score",),("B_TOP5_N1__R8","B_TOP5_N1__R9","B_TOP5_N1__Rdual_exact_min"),("B_TOP5_N2__R8","B_TOP5_N2__R9","B_TOP5_N2__Rdual_exact_min"),("B_TOP5_N3__R8","B_TOP5_N3__R9","B_TOP5_N3__Rdual_exact_min"))
 ids=data["candidate_ids"];matrix=[];dual=[]
 for name,path,cols in zip(names,paths,columns):
  source=rows(path);require(set(source)==set(ids),f"closure:{name}");value=np.asarray([[float(source[c][x]) for x in cols] for c in ids]);matrix.append(value);dual.append(value[:,-1])
 data["expanded_signal_matrix"]=np.column_stack(matrix);data["expanded_dual"]=np.column_stack(dual)

def all_dual(data:Mapping[str,Any],idx:np.ndarray)->np.ndarray:
 return np.column_stack((data["base"][idx,2],data["base"][idx,5],data["base"][idx,8],data["l1"][idx,2],data["expanded_dual"][idx]))

def features(data:Mapping[str,Any],train:np.ndarray,idx:np.ndarray)->np.ndarray:
 original=V215.augmented_features(data,train,idx);extra=data["expanded_signal_matrix"][idx]
 train_dual=all_dual(data,train);value_dual=all_dual(data,idx)
 ranks=np.column_stack([V215.percentile_from_train(train_dual[:,j],value_dual[:,j]) for j in range(train_dual.shape[1])])
 agreement=np.column_stack((ranks.mean(1),ranks.std(1),np.sort(ranks,axis=1)[:,-2:].mean(1),(ranks>=.8).sum(1),(ranks>=.9).sum(1)))
 return np.column_stack((original,extra,ranks,agreement))

def mask(data:Mapping[str,Any],train:np.ndarray,idx:np.ndarray,fraction:float)->np.ndarray:
 t=all_dual(data,train);v=all_dual(data,idx);r=np.column_stack([V215.percentile_from_train(t[:,j],v[:,j]) for j in range(t.shape[1])]);m=np.any(r>=1-fraction,axis=1);minimum=math.ceil(.05*len(idx))
 if m.sum()<minimum:m[np.argsort(-r.max(1),kind="stable")[:minimum]]=True
 return m

def fit(kind:str,data:Mapping[str,Any],train:np.ndarray,fraction:float,c:Mapping[str,Any])->tuple[Any,int]:
 p=train[mask(data,train,train,fraction)];truth=np.min(data["truth"][train],axis=1);threshold=np.sort(truth)[-max(1,math.ceil(.1*len(train)))];y=(np.min(data["truth"][p],axis=1)>=threshold).astype(int);w=V215.balanced_weights(data["weights"][p],y);model=V215.make_hgb_classifier(c["hgb_classifier"]) if kind=="hgb" else V215.make_extra_trees(c["extra_trees"]);model.fit(features(data,train,p),y,sample_weight=w);return model,len(p)

def predict(model:Any,data:Mapping[str,Any],train:np.ndarray,test:np.ndarray,fraction:float)->tuple[np.ndarray,int]:
 m=mask(data,train,test,fraction);p=test[m];s=np.full(len(test),-1.0);s[m]=model.predict_proba(features(data,train,p))[:,1];tail=np.mean(np.column_stack([V215.percentile_from_train(all_dual(data,train)[:,j],all_dual(data,test)[:,j]) for j in range(8)]),axis=1);s[~m]=-1+1e-3*tail[~m];return s,len(p)

def oof(data:Mapping[str,Any],c:Mapping[str,Any])->tuple[dict[str,np.ndarray],dict[str,Any]]:
 n=len(data["candidate_ids"]);score={x:np.full(n,np.nan) for x in METHODS};audit={}
 for fold in range(5):
  train=np.flatnonzero(data["folds"]!=fold);test=np.flatnonzero(data["folds"]==fold);require(not(set(data["parents"][train])&set(data["parents"][test])),"parent_overlap")
  score["E0_L1"][test]=data["l1"][test,2];rank8=np.column_stack([V215.percentile_from_train(all_dual(data,train)[:,j],all_dual(data,test)[:,j]) for j in range(8)]);score["E1_EQUAL_RANK8"][test]=rank8.mean(1);observed={};fa={}
  for fraction,label in ((.2,"U20"),(.3,"U30")):
   for kind in ("hgb","extra"):
    model,ntrain=fit(kind,data,train,fraction,c);pred,ntest=predict(model,data,train,test,fraction);observed[f"{label}_{kind}"]=pred;fa[f"{label}_{kind}"]={"train_pool":ntrain,"test_pool":ntest}
  score["E2_HGB_U20"][test]=observed["U20_hgb"];score["E3_EXTRA_U20"][test]=observed["U20_extra"];score["E4_HGB_U30"][test]=observed["U30_hgb"];score["E5_EXTRA_U30"][test]=observed["U30_extra"]
  mean=.5*V215.percentile_rank(observed["U20_hgb"])+.5*V215.percentile_rank(observed["U20_extra"]);score["E6_U20_MEAN"][test]=mean;score["E7_U20_L1_BLEND"][test]=.8*mean+.2*V215.percentile_rank(data["l1"][test,2]);audit[str(fold)]=fa
 require(all(np.isfinite(v).all() for v in score.values()),"nonfinite");return score,audit

def write(path:Path,rr:Sequence[Mapping[str,Any]])->None:
 with path.open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=list(rr[0]),delimiter="\t",lineterminator="\n");w.writeheader();w.writerows(rr)

def run(contract_path:Path,raw:Path,assignment:Path,legacy:Path,l1:Path,g3:Path,n1:Path,n2:Path,n3:Path,out:Path)->dict[str,Any]:
 require(not out.exists(),"output_exists");c=json.loads(contract_path.read_text());require(c.get("schema_version")==CONTRACT_SCHEMA and c.get("status")=="FROZEN_BEFORE_V2_17_OOF_EXECUTION","contract")
 for p,k in ((raw,"raw_multimodal_sha256"),(assignment,"assignment_sha256"),(legacy,"legacy_oof_sha256"),(l1,"l1_oof_sha256"),(g3,"g3_oof_sha256"),(n1,"n1_oof_sha256"),(n2,"n2_oof_sha256"),(n3,"n3_oof_sha256")):require(V215.sha256_file(p)==c["input_bindings"][k],f"hash:{k}")
 data=V215.load_inputs(raw,assignment,legacy,l1,c);require(data["raw_rows_scanned"]-len(data["candidate_ids"])==795,"firewall");load_signals(data,(g3,n1,n2,n3));scores,audit=oof(data,c);truth=np.min(data["truth"],axis=1);observed={k:V215.metrics(data["candidate_ids"],data["folds"],truth,v) for k,v in scores.items()};selected=max(METHODS,key=lambda x:(observed[x]["pooled_ef5"],observed[x]["binary_ndcg_true_top10_at_budget5"],observed[x]["median_fold_ef5"],observed[x]["worst_fold_ef5"],-METHODS.index(x)))
 out.parent.mkdir(parents=True,exist_ok=True);st=Path(tempfile.mkdtemp(prefix=f".{out.name}.",dir=out.parent))
 try:
  rr=[]
  for i,x in enumerate(data["candidate_ids"]):
   row={"candidate_id":x,"parent_framework_cluster":data["parents"][i],"fold_id":int(data["folds"][i]),"truth_Rdual_exact_min":truth[i]};row.update({f"{k}__frontscreen_score":v[i] for k,v in scores.items()});rr.append(row)
  pred=st/"V2_17_EXPANDED_UNION_TOP5_OOF_PREDICTIONS.tsv";write(pred,rr);report={"schema_version":SCHEMA,"status":"PASS_V2_17_EXPANDED_UNION_TOP5_OOF","methods":observed,"selected_method":selected,"target_ef5":5.0,"target_achieved_in_this_oof":observed[selected]["pooled_ef5"]>=5,"pool_audit":audit,"input_access":c["input_access"]};metric=st/"V2_17_EXPANDED_UNION_TOP5_METRICS.json";metric.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n");receipt={"schema_version":SCHEMA,"status":report["status"],"selected_method":selected,"target_achieved_in_this_oof":report["target_achieved_in_this_oof"],"input_access":report["input_access"],"outputs":{pred.name:V215.sha256_file(pred),metric.name:V215.sha256_file(metric)}};(st/"RUN_RECEIPT.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n");os.replace(st,out);return report
 finally:
  if st.exists():shutil.rmtree(st)

def main()->int:
 p=argparse.ArgumentParser();
 for name in ("contract","raw_multimodal","assignment","legacy_oof","l1_oof","g3_oof","n1_oof","n2_oof","n3_oof","output_dir"):p.add_argument("--"+name.replace("_","-"),dest=name,type=Path,required=True)
 a=p.parse_args();r=run(a.contract,a.raw_multimodal,a.assignment,a.legacy_oof,a.l1_oof,a.g3_oof,a.n1_oof,a.n2_oof,a.n3_oof,a.output_dir);print(json.dumps({"selected":r["selected_method"],"ef5":r["methods"][r["selected_method"]]["pooled_ef5"],"target":r["target_achieved_in_this_oof"]}));return 0
if __name__=="__main__":raise SystemExit(main())

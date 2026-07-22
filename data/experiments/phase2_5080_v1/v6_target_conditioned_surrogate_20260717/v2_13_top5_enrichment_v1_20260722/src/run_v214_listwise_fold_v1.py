#!/usr/bin/env python3
"""Train one frozen V2.14 whole-parent fold with listwise Top5 losses."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn


HERE=Path(__file__).resolve().parent


def load_module(name: str,path: Path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:raise RuntimeError(f"module_import:{path}")
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module


BASE=load_module("v213_clean_attention_base_for_v214",HERE/"run_top5_clean_attention_fold_v1.py")
LISTWISE=load_module("v214_listwise_losses_for_runner",HERE/"top5_listwise_losses_v1.py")

SCHEMA_VERSION="pvrig_v2_14_listwise_top5_fold_v1"
CONTRACT_SCHEMA="pvrig_v2_14_listwise_top5_contract_v1"
RESULT_NAME="RESULT.json"
HISTORY_NAME="TRAIN_HISTORY.json"
PREDICTION_NAME="DEVELOPMENT_PREDICTIONS.tsv"
CHECKPOINT_NAME="HEAD_CHECKPOINT.pt"
VARIANTS=("N1","N2","N3")


def require(condition: bool,message: str)->None:
    if not condition:raise BASE.CleanAttentionError(message)


def train(args: argparse.Namespace)->dict[str,Any]:
    BASE.seed_everything(args.seed)
    contract=BASE.load_contract(args.contract)
    list_contract=json.loads(args.listwise_contract.read_text())
    require(list_contract.get("schema_version")==CONTRACT_SCHEMA and list_contract.get("status")=="FROZEN_BEFORE_V2_14_LAUNCH","listwise_contract")
    variant=(list_contract.get("variants") or {}).get(args.variant);require(isinstance(variant,Mapping),"variant")
    fixed=list_contract["fixed_training"]
    observed={"epochs":args.epochs,"batch_size":args.batch_size,"gradient_accumulation":args.gradient_accumulation,"precision":args.precision,"learning_rate":args.learning_rate,"weight_decay":args.weight_decay,"graph_hidden_dim":args.graph_hidden_dim,"dropout":args.dropout,"receptor_weight":args.receptor_weight,"dual_weight":args.dual_weight,"huber_beta":args.huber_beta,"softmin_tau":args.softmin_tau}
    if not args.tiny_e2e:
        require(observed==fixed,f"fixed_training_drift:{observed}")
    task=contract.get("task") or {};require(args.seed==int(task.get("seed",-1)),"seed");require(int(task.get("fold_id",-1)) in range(5),"fold")
    expected=contract["expected_counts"]
    training_path=BASE._verify_bound_file(contract["training_table"],"training_table");split_path=BASE._verify_bound_file(contract["split_manifest"],"split_manifest")
    target_receipt_path=BASE._verify_bound_file(contract["fixed_target_graph"]["receipt"],"target_receipt");target_path=BASE._verify_bound_file(contract["fixed_target_graph"]["torch_artifact"],"target_pt")
    rows=BASE.load_rows(training_path,int(expected["total"]));split=BASE.load_split(split_path,rows,int(expected["train"]),int(expected["score"]))
    graph_store=BASE.GraphCacheStore(args.graph_cache_dir,rows,require_full_receipt=not args.tiny_e2e)
    target_graphs=BASE.load_target_graphs(target_path,graph_store.edge_feature_dim,target_receipt_path);target_dim=int(next(iter(target_graphs.values()))["node_features"].shape[1])
    model,tokenizer,loss_config,trainer,model_identity=BASE.build_clean_model(args,contract,graph_store.edge_feature_dim,target_dim)
    truth_percentiles=BASE.training_truth_percentiles(rows,split.train_indices)
    weights={index:rows[index].sample_weight*BASE.top_weight(truth_percentiles[index],float(list_contract["sample_weighting"]["top_strength"]),float(list_contract["sample_weighting"]["top_center"]),float(list_contract["sample_weighting"]["top_scale"])) for index in split.train_indices}
    collator=BASE.CleanCollator(rows,tokenizer,graph_store,weights,truth_percentiles)
    probe=collator(split.train_indices[:2]);neural=trainer.neural_forward_kwargs(probe,target_graphs)
    require(set(neural)==set(trainer.NEURAL_REQUIRED_BATCH_FIELDS)|{"target_graphs"},"neural_allowlist");require(not(set(neural)&BASE.FORBIDDEN_NEURAL_INPUTS),"forbidden_input")
    require(not args.output_dir.exists(),"output_exists");args.output_dir.mkdir(parents=True)
    BASE._atomic_json(args.output_dir/"RUNNING.json",{"schema_version":SCHEMA_VERSION,"status":"RUNNING_V2_14_LISTWISE_FOLD","variant":args.variant,"seed":args.seed,"fold_id":int(task["fold_id"])})
    device=torch.device(args.device);require(device.type!="cuda" or torch.cuda.is_available(),"cuda")
    model.to(device);target_device=BASE.move(target_graphs,device)
    optimizer,optimizer_audit=trainer.build_optimizer(model,trainer.OptimizerConfig(learning_rate=args.learning_rate,weight_decay=args.weight_decay,contact_learning_rate_multiplier=1.0))
    require(optimizer_audit["contact"]["parameter_values"]==0,"contact_parameters")
    trainable=[parameter for parameter in model.parameters() if parameter.requires_grad]
    history=[];optimizer_steps=0
    loss_settings={**variant,"softmin_tau":args.softmin_tau}
    for epoch in range(args.epochs):
        model.train();model.backbone.eval();optimizer.zero_grad(set_to_none=True);sums=defaultdict(float);batches=0
        iterator=BASE.iter_top_balanced_batches(split.train_indices,collator,args.batch_size,shuffle_seed=args.seed+epoch,truth_percentiles=truth_percentiles,top_per_batch=int(list_contract["balanced_batch"]["top_per_batch"]),top_threshold=float(list_contract["balanced_batch"]["top_threshold"]))
        for _indices,raw in iterator:
            batch=BASE.move(raw,device)
            with torch.autocast(device_type=device.type,dtype=torch.bfloat16,enabled=args.precision=="bf16"):
                output=trainer.forward_lane(model,BASE.LANE,batch,target_device);total,parts=trainer.compute_loss(output,batch,BASE.LANE,loss_config)
                list_total,list_parts=LISTWISE.combined_listwise_loss(output,batch,loss_settings)
                pair=BASE.pairwise_rank_loss(output,batch,softmin_tau=args.softmin_tau,margin=float(variant["pair_margin"]),temperature=float(variant["pair_temperature"]),top_strength=float(list_contract["sample_weighting"]["top_strength"]))
                total=total+list_total+float(variant["pair_rank_weight"])*pair
                parts={**dict(parts),**list_parts,"pair_rank":pair,"total_with_listwise":total}
            (total/args.gradient_accumulation).backward();batches+=1
            for name,value in parts.items():sums[name]+=float(value.detach().cpu())
            if batches%args.gradient_accumulation==0:
                nn.utils.clip_grad_norm_(trainable,args.gradient_clip,error_if_nonfinite=True);optimizer.step();trainer.assert_train_state_finite(model,optimizer);optimizer.zero_grad(set_to_none=True);optimizer_steps+=1
        require(batches>0,"empty_epoch")
        remainder=batches%args.gradient_accumulation
        if remainder:
            correction=args.gradient_accumulation/remainder
            for parameter in trainable:
                if parameter.grad is not None:parameter.grad.mul_(correction)
            nn.utils.clip_grad_norm_(trainable,args.gradient_clip,error_if_nonfinite=True);optimizer.step();trainer.assert_train_state_finite(model,optimizer);optimizer.zero_grad(set_to_none=True);optimizer_steps+=1
        history.append({"epoch":epoch+1,"batches":batches,**{name:value/batches for name,value in sorted(sums.items())}});BASE._atomic_json(args.output_dir/HISTORY_NAME,{"selection":"NONE_FIXED_EPOCH_ONLY","epochs":history})
    metrics,records=BASE.evaluate(model,trainer,rows,split.development_indices,collator,target_graphs,device,args.precision,args.eval_batch_size)
    row_by={row.candidate_id:row for row in rows}
    for record in records:
        record["sequence_sha256"]=row_by[record["candidate_id"]].sequence_sha256;record["fold_id"]=str(task["fold_id"]);record["seed"]=str(args.seed);record["variant"]=args.variant
    prediction_path=args.output_dir/PREDICTION_NAME;BASE._write_predictions(prediction_path,records)
    checkpoint_path=args.output_dir/CHECKPOINT_NAME;BASE._atomic_torch_save(checkpoint_path,{"schema_version":SCHEMA_VERSION,"seed":args.seed,"variant":args.variant,"split_id":split.split_id,"head_config":asdict(model.head.config),"head_state_dict":{name:value.detach().cpu() for name,value in model.head.state_dict().items()},"backbone_identity_sha256":model_identity})
    receipt={"schema_version":SCHEMA_VERSION,"status":"PASS_V2_14_LISTWISE_TOP5_FOLD","claim_boundary":BASE.CLAIM_BOUNDARY,"seed":args.seed,"variant":args.variant,"fold_id":int(task["fold_id"]),"split":{"split_id":split.split_id,"train_rows":len(split.train_indices),"score_rows":len(split.development_indices),"train_parents":len(split.train_parents),"score_parents":len(split.development_parents),"whole_parent_overlap":0},"training":{"fixed_epochs":args.epochs,"optimizer_steps":optimizer_steps,"batch_size":args.batch_size,"gradient_accumulation":args.gradient_accumulation,"loss":asdict(loss_config),"listwise_loss":dict(loss_settings),"optimizer_parameter_roles":optimizer_audit},"metrics":metrics,"neural_input_firewall":{"candidate_id_input_count":0,"parent_id_input_count":0,"m2_input_count":0,"c2_input_count":0,"candidate_docking_pose_input_count":0},"input_bindings":{"contract_sha256":BASE.sha256_file(args.contract),"listwise_contract_sha256":BASE.sha256_file(args.listwise_contract),"training_table_sha256":BASE.sha256_file(training_path),"split_manifest_sha256":BASE.sha256_file(split_path),"backbone_identity_file_sha256":model_identity},"outputs":{PREDICTION_NAME:BASE.sha256_file(prediction_path),CHECKPOINT_NAME:BASE.sha256_file(checkpoint_path),HISTORY_NAME:BASE.sha256_file(args.output_dir/HISTORY_NAME)},"exact_min_inference":True,"open_development_access_count":0,"frozen_test_access_count":0}
    BASE._atomic_json(args.output_dir/RESULT_NAME,receipt);(args.output_dir/"RUNNING.json").unlink();return receipt


def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--contract",type=Path,required=True);p.add_argument("--listwise-contract",type=Path,required=True);p.add_argument("--variant",choices=VARIANTS,required=True);p.add_argument("--graph-cache-dir",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--device",default="cuda:0");p.add_argument("--seed",type=int,required=True)
    p.add_argument("--epochs",type=int,default=8);p.add_argument("--batch-size",type=int,default=32);p.add_argument("--eval-batch-size",type=int,default=16);p.add_argument("--gradient-accumulation",type=int,default=1);p.add_argument("--precision",choices=("fp32","bf16"),default="bf16");p.add_argument("--learning-rate",type=float,default=1e-4);p.add_argument("--weight-decay",type=float,default=.02);p.add_argument("--gradient-clip",type=float,default=1.0);p.add_argument("--graph-hidden-dim",type=int,default=128);p.add_argument("--dropout",type=float,default=.25);p.add_argument("--receptor-weight",type=float,default=1.0);p.add_argument("--dual-weight",type=float,default=.5);p.add_argument("--huber-beta",type=float,default=.03);p.add_argument("--softmin-tau",type=float,default=.02);p.add_argument("--backbone-kind",choices=("hf","tiny"),default="hf");p.add_argument("--backbone-dtype",choices=("fp32","bf16"),default="bf16");p.add_argument("--model-path",type=Path);p.add_argument("--model-identity-file",type=Path);p.add_argument("--expected-model-sha256");p.add_argument("--tiny-hidden-size",type=int,default=16);p.add_argument("--tiny-e2e",action="store_true");return p


def validate_args(args: argparse.Namespace)->None:
    require(args.epochs>0 and args.batch_size>0 and args.gradient_accumulation>0,"training_count");require(args.learning_rate>0 and args.weight_decay>=0 and args.gradient_clip>0,"optimizer")
    if args.backbone_kind=="hf":require(args.model_path is not None and args.model_identity_file is not None and args.expected_model_sha256,"model_binding")


def main(argv: Sequence[str]|None=None)->int:
    args=parser().parse_args(argv);validate_args(args);result=train(args);print(json.dumps(result,sort_keys=True));return 0


if __name__=="__main__":raise SystemExit(main())

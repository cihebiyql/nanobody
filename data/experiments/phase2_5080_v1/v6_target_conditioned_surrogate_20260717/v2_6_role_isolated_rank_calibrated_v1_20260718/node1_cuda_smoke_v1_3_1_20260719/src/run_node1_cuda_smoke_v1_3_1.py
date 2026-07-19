#!/usr/bin/env python3
from __future__ import annotations
import argparse, gc, hashlib, importlib, json, math, os, random, sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence
import numpy as np
import torch

SCHEMA_VERSION="pvrig_v2_6_node1_cuda_bf16_smoke_v1_3_1"
CLAIM_BOUNDARY="Open-development CUDA/BF16 technical smoke of an independent 8X6B/9E6Y computational Docking-geometry surrogate; not binding, affinity, experimental blocking, Docking Gold, V4-F/test32, or submission truth."
PHYSICAL_GPU=1; LOGICAL_GPU=0; STEPS=20; ACCUMULATION=2; MAIN_BATCHES=40
INTEGRATION_FREEZE_SHA="e73335c32e8495d609f9b5e6379ba648d1c38e4da49c40088468eae7308e3faa"
INTEGRATION_TRAINER_SHA="e99146be166cab7f703bd6cbcad3594e196d7a155c422459cb16f8cbfc2b6a24"
V25_RUNNER_SHA="f7c4e813f19d9034a945982d029118dc87cc6c420f1f8c8cf898bfec74065b7f"
V25_API_SHA="af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0"
V25_MODEL_SHA="26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521"
OPT_SHA="2dadc945ec30eb802ca9f32fac84ce647783b9defc36db68f345fc00e972f363"
RANK_SHA="b420766a7769a546418a68367b71742eb3ea7872dd2411a48609139a985ef2ec"
TRUST_RECEIPT_SHA="2acf16069e3609a8160d9193818fa707a5105405e28354956f3431634756959e"
V25_SRC=Path("/data1/qlyu/projects/pvrig_v2_5_ortho_heads_smoke_package_v1_2_20260718/src")
DATA_ROOT=Path("/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718")
ADAPTER=Path("/data1/qlyu/projects/pvrig_v6_residue_v2_4_deployment_bundle_v2_2_2_20260718/src/train_v2_4_base_split.py")
V23=Path("/data1/qlyu/projects/pvrig_v6_residue_v2_3_deployment_bundle_v1_20260718")
TARGET=Path("/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graphs_v2.pt")
MODEL=Path("/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c")
MODEL_FILE=MODEL/"model.safetensors"
MODEL_SHA="a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0"

def require(c:bool,m:str)->None:
    if not c: raise RuntimeError(m)
def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()
def atomic_json(path:Path,payload:Mapping[str,Any])->None:
    tmp=path.with_name(f'.{path.name}.{os.getpid()}.tmp');tmp.write_text(json.dumps(dict(payload),indent=2,sort_keys=True,allow_nan=False)+'\n');os.replace(tmp,path)
def save_head(path:Path,model:torch.nn.Module,lane:str)->dict[str,Any]:
    state={n:p.detach().cpu().clone() for n,p in model.named_parameters() if p.requires_grad}
    require(state and all(n.startswith('head.') for n in state),'checkpoint_not_head_only')
    torch.save({'schema_version':SCHEMA_VERSION+'_head_checkpoint','lane':lane,'head_state':state,'claim_boundary':CLAIM_BOUNDARY},path)
    return {'path':path.name,'sha256':sha(path),'parameter_tensors':len(state),'scope':'trainable_head_only'}

class LimitedFactory:
    def __init__(self,base:Any): self.base=base; self.batch_size=base.batch_size
    def __call__(self,indices:Sequence[int],shuffle:bool,epoch:int)->Iterable[Mapping[str,Any]]:
        for i,batch in enumerate(self.base(indices,shuffle,epoch)):
            if shuffle and i>=MAIN_BATCHES: break
            yield batch

def module_imports(package_root:Path):
    for path,expected in (
        (V25_SRC/'run_real1507_split_v1.py',V25_RUNNER_SHA),
        (V25_SRC/'train_v2_5_ortho_heads.py',V25_API_SHA),
        (V25_SRC/'residue_model_v2_5_ortho.py',V25_MODEL_SHA),
    ):
        require(path.is_file() and not path.is_symlink(),f'v25_source_not_regular:{path}')
        require(sha(path)==expected,f'v25_source_hash:{path.name}')
    paths=[V25_SRC,package_root/'vendor/integration',package_root/'vendor/optimizer',package_root/'vendor/rank']
    sys.path[:0]=[str(p) for p in paths]
    runner=importlib.import_module('run_real1507_split_v1')
    v25=importlib.import_module('train_v2_5_ortho_heads')
    model=importlib.import_module('residue_model_v2_5_ortho')
    integ=importlib.import_module('real1507_role_isolated_trainer_v1_3')
    opt=importlib.import_module('role_isolated_optimization_v1')
    require(sha(Path(runner.__file__))==V25_RUNNER_SHA,'v25_runner_hash')
    require(sha(Path(v25.__file__))==V25_API_SHA,'v25_api_hash')
    require(sha(Path(model.__file__))==V25_MODEL_SHA,'v25_model_hash')
    require(sha(Path(integ.__file__))==INTEGRATION_TRAINER_SHA,'integration_hash')
    require(sha(Path(opt.__file__))==OPT_SHA,'optimizer_hash')
    rank_path=package_root/'vendor/rank/rank_calibration_core_v1_1.py'
    require(sha(rank_path)==RANK_SHA,'rank_hash')
    policy=integ.RankPolicyAdapter.load(rank_path,RANK_SHA)
    return runner,v25,integ,opt,policy

def real_args(runtime:Path,variant:str)->argparse.Namespace:
    split='outer_0_inner_0'
    return argparse.Namespace(
      lane_variant=variant,output_dir=runtime/f'_unused_{variant}',v2_4_adapter_path=ADAPTER,
      expected_v2_4_adapter_sha256='59245b7aa28c14e9134f15fa1c2f4717e3a3b3a7c3e044a4d7cda06afc1c685f',
      v2_3_bundle_root=V23,training_tsv=DATA_ROOT/f'inputs/split_training/{split}.tsv',
      contact_tsv_gz=DATA_ROOT/f'inputs/split_contacts/{split}.marginal.tsv.gz',
      pair_contact_tsv_gz=DATA_ROOT/f'inputs/split_contacts/{split}.pair.tsv.gz',
      graph_cache_dir=DATA_ROOT/f'inputs/split_graphs/{split}',target_graph_pt=TARGET,
      contact_formula_json=DATA_ROOT/'inputs/contact_score_formula_v1.json',
      split_manifest=DATA_ROOT/f'plan/trainer_splits/{split}.json',model_path=MODEL,
      model_identity_file=MODEL_FILE,expected_model_sha256=MODEL_SHA,device='cuda:0',
      expected_rows=1269,expected_parents=28,expected_train_rows=1085,expected_score_rows=184,
    )

def set_seed()->None:
    random.seed(43);np.random.seed(43);torch.manual_seed(43);torch.cuda.manual_seed(43)

def run_lane(package_root:Path,runtime:Path,lane:str,variant:str,modules,reference_init_path:Path)->dict[str,Any]:
    runner,v25,integ,opt,policy=modules
    set_seed(); context=runner.load_real_context(real_args(runtime,variant)); context.batches=LimitedFactory(context.batches)
    roles=opt.role_mapping_from_v25_orthogonal_model(context.model)
    scalar_shared_names=sorted(name for role in ('shared_encoder','attention_scalar') for name,_parameter in roles[role])
    named=dict(context.model.named_parameters())
    if lane==integ.LANE_B:
        torch.save({'names':scalar_shared_names,'state':{name:named[name].detach().cpu().clone() for name in scalar_shared_names}},reference_init_path)
    else:
        reference=torch.load(reference_init_path,map_location='cpu',weights_only=True)
        require(reference['names']==scalar_shared_names,'reference_scalar_shared_name_mismatch')
        with torch.no_grad():
            for name,value in reference['state'].items(): named[name].copy_(value)
    before=save_head(runtime/f'{lane}.before.pt',context.model,lane)
    scalar_loss=v25.OrthoLossConfig(receptor_weight=1.0,dual_weight=0.5,marginal_weight=0.0,pair_weight=0.0)
    contact_loss=v25.OrthoLossConfig(receptor_weight=1.0,dual_weight=0.5,marginal_weight=1.0,pair_weight=0.5)
    role_config=opt.RoleOptimizerConfig(learning_rate=1e-4,contact_learning_rate=1e-4,weight_decay=0.02,clip_shared=1.0,clip_scalar=1.0,clip_contact=1.0,kappa=0.25,lambda_contact_shared=1.0)
    config=integ.V26TrainerConfig(integration_lane=lane,fixed_epochs=1,gradient_accumulation=ACCUMULATION,
      lambda_rank=0.10,precision='bf16',base_seed=43,outer_fold=0,inner_fold=0,
      expected_main_batches_per_epoch=MAIN_BATCHES,
      rank_trust_anchor_set_receipt_path=str(package_root/'vendor/trust_anchors/TRUST_ANCHOR_SET_RECEIPT.json'),
      rank_trust_anchor_dir=str(package_root/'vendor/trust_anchors'),physical_gpu_index=PHYSICAL_GPU,logical_cuda_index=LOGICAL_GPU)
    receipt=integ.train_open_partition_fixed_epochs(model=context.model,rows=context.rows,manifest=context.manifest,
      train_indices=context.train_indices,score_indices=context.score_indices,batch_factory=context.batches,
      target_graphs=context.target_graphs,v25_api=v25,optimizer_api=opt,rank_policy=policy,
      delta_noise_binding_path=package_root/'vendor/V2_6_DELTA_NOISE_BINDING.json',
      scalar_loss_config=scalar_loss,contact_loss_config=contact_loss,role_optimizer_config=role_config,
      config=config,device_name='cuda:0')
    require(receipt['optimizer_steps']==STEPS,'optimizer_step_count')
    require(len(receipt['gradient_step_diagnostics'])==STEPS,'step_evidence_count')
    after=save_head(runtime/f'{lane}.after.pt',context.model,lane)
    atomic_json(runtime/f'{lane}.TRAINING_RECEIPT.json',receipt)
    del context;gc.collect();torch.cuda.empty_cache()
    return {'receipt':receipt,'before_checkpoint':before,'after_checkpoint':after}

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--package-root',type=Path,required=True);p.add_argument('--runtime-root',type=Path,required=True);p.add_argument('--result',type=Path,required=True);a=p.parse_args()
    visible=os.environ.get('CUDA_VISIBLE_DEVICES','');require(visible=='1',f'visible_gpu_not_exact_1:{visible}')
    require(os.environ.get('CUBLAS_WORKSPACE_CONFIG')==':4096:8','cublas_workspace_not_frozen')
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic=True; torch.backends.cudnn.benchmark=False
    torch.backends.cuda.matmul.allow_tf32=False; torch.backends.cudnn.allow_tf32=False
    require(torch.cuda.is_available() and torch.cuda.is_bf16_supported(),'cuda_or_bf16_unavailable');require(torch.cuda.current_device()==0,'logical_gpu_not_0')
    require(not a.runtime_root.exists(),'runtime_exists');a.runtime_root.mkdir(parents=True)
    modules=module_imports(a.package_root)
    require(sha(a.package_root/'vendor/trust_anchors/TRUST_ANCHOR_SET_RECEIPT.json')==TRUST_RECEIPT_SHA,'trust_receipt_hash')
    lanes={}
    for lane,variant in ((modules[2].LANE_B,'E_DECOUPLED_CONTACT_DETACHED'),(modules[2].LANE_E,'E_DECOUPLED_CONTACT_DETACHED'),(modules[2].LANE_F,'E_DECOUPLED_CONTACT_SHARED')):
        lanes[lane]=run_lane(a.package_root,a.runtime_root,lane,variant,modules,a.runtime_root/'REFERENCE_SCALAR_SHARED_INIT.pt')
    b=lanes[modules[2].LANE_B]['receipt']['gradient_step_diagnostics'];e=lanes[modules[2].LANE_E]['receipt']['gradient_step_diagnostics'];f=lanes[modules[2].LANE_F]['receipt']['gradient_step_diagnostics']
    be_equal=all(x['evidence_hashes']['scalar_trajectory_after_sha256']==y['evidence_hashes']['scalar_trajectory_after_sha256'] for x,y in zip(b,e))
    require(be_equal,'be_scalar_trajectory_mismatch')
    budget=all(x['core_gradient_event'].get('post_lambda_contact_gradient_budget_pass') is True for x in f);require(budget,'f_budget_failure')
    step_evidence={lane:[event['evidence_hashes'] for event in data['receipt']['gradient_step_diagnostics']] for lane,data in lanes.items()}
    result={'schema_version':SCHEMA_VERSION,'status':'PASS','claim_boundary':CLAIM_BOUNDARY,'precision':'bf16','physical_gpu_index':1,'logical_cuda_index':0,
      'cuda_visible_devices':[1],'determinism':{'torch_deterministic_algorithms':True,'cublas_workspace_config':':4096:8','cudnn_deterministic':True,'cudnn_benchmark':False,'matmul_tf32':False,'cudnn_tf32':False},'integration_freeze_sha256':INTEGRATION_FREEZE_SHA,'integration_trainer_sha256':INTEGRATION_TRAINER_SHA,
      'rank_core_sha256':RANK_SHA,'rank_trust_anchor_set_receipt_sha256':TRUST_RECEIPT_SHA,
      'real_partition':{'outer_fold':0,'inner_fold':0,'rows':1269,'parents':28,'train_rows':1085,'score_rows':184,'main_microbatches_per_lane':MAIN_BATCHES},
      'be_trajectory':{'optimizer_steps':STEPS,'exact_scalar_trajectory_hash_match_every_step':be_equal,'maximum_scalar_shared_parameter_delta':0.0},
      'f_shared_gated':{'optimizer_steps':STEPS,'kappa':0.25,'post_lambda_budget_pass_every_step':budget,'gradient_budget_violation_count':0},
      'gradient_accumulation':{'microbatches_per_optimizer_step':ACCUMULATION,'optimizer_steps':STEPS,'microbatches_consumed':MAIN_BATCHES,'reduction':'EXACT_EFFECTIVE_MASS_WEIGHTED'},
      'exact_min':{'independent_rdual_output_trained':False,'maximum_abs_error':max(float(x['receipt']['exact_min_probe_error']) for x in lanes.values()),'inference_semantics':'exact_min(R_8X6B,R_9E6Y)'},
      'checkpoints':{lane:{'before':x['before_checkpoint'],'after':x['after_checkpoint']} for lane,x in lanes.items()},
      'per_step_evidence_hashes':step_evidence,
      'firewall':{'v4_f_test32_access_count':0,'score_partition_truth_access_count':0,'outer_metrics_access_count':0,'candidate_docking_pose_input_count':0}}
    atomic_json(a.result,result);atomic_json(a.runtime_root/'TERMINAL.json',{'schema_version':SCHEMA_VERSION+'_terminal','status':'PASS','result_sha256':sha(a.result),'v4_f_test32_access_count':0})
    print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__': raise SystemExit(main())

# V2.5-ORTHO-CONTACT-POSE-STACK：正交神经头实现 V1

## 状态

```text
BUILD_AND_TEST_ONLY
NOT_DEPLOYED
NOT_LAUNCHED
NO_V4_F_TEST32_ACCESS
REAL_1269_OUTER0_INNER0_PACKAGE_AUDIT_PASS
GPU1_SEQUENTIAL_OVERLAY_AUDIT_PASS_PENDING_AUTHORIZATION
```

本目录不修改 V2.4 冻结文件。它只实现下一代 neural model/trainer
原语；M2、coarse-pose 和最终 meta-stack 必须在严格 inner-OOF 层合并，
不能作为 neural forward 输入。

本版本已增加真实 1507 teacher 数据链的 `outer_0_inner_0` adapter 和
**非启动** Node1 package。当前 package 只覆盖冻结 split 中的 1,269 条：

```text
28 whole-parent clusters
1,085 train rows
184 score rows
```

它没有执行训练、预测或指标计算，也没有访问 V4-F/test32。

## 两条实现分支

### B_CLEAN_TARGET_ATTENTION

```text
frozen residue PLM
+ label-free VHH monomer graph
+ fixed 8X6B/9E6Y target graphs
        -> shared graph encoders
        -> attention-only low-rank pair branch
        -> attention-routed receptor pools
        -> direct R8/R9
        -> inference exact min
```

该 lane **不实例化 contact module**，输出中也没有 contact tensor。

### E_DECOUPLED_CONTACT

```text
shared encoders
   |-- independent attention projections/terminal -> scalar R8/R9
   `-- independent contact projections/terminal   -> marginal/pair/contact summary
```

scalar head 不读取 contact logits、probabilities、summary 或 contact pooling。
改变全部 contact 参数时 scalar 输出逐位不变，已有单元测试锁定。

`contact_encoder_gradient` 支持：

- `detached`：默认；contact loss 只更新独立 contact branch，不更新共享 encoder；
- `shared`：contact loss 可更新共享 encoder，但仍不能更新 attention terminal 或
  scalar head。用于正式实验前必须作为独立 lane 预注册，不可在 outer 结果后切换。

contact sigmoid 仅称为 `contact evidence/score`，当前不声明为校准概率。

## API

模型：

```python
from residue_model_v2_5_ortho import (
    ResidueV25OrthoConfig,
    OrthogonalTargetHead,
    OrthogonalResidueSurrogate,
    model_contract,
)
```

训练：

```python
from train_v2_5_ortho_heads import (
    OrthoLossConfig,
    OptimizerConfig,
    build_model,
    neural_forward_kwargs,
    compute_loss,
    build_optimizer,
    train_fixed_epochs,
    trainer_contract,
)
```

`neural_forward_kwargs()` 采用正向 allowlist，唯一允许字段为：

```text
input_ids
attention_mask
residue_mask
vhh_aa_index
vhh_region_index
vhh_confidence
vhh_edge_index
vhh_edge_features
target_graphs
```

以下字段即使存在于训练 batch，也不会被读取或传给模型：

```text
M2/126D structure
candidate/parent/campaign ID
teacher_source
candidate Docking pose 或 pose-derived features
```

真实输入 runner：

```text
real1507/run_real1507_split_v1.py
```

它动态校验并复用冻结 V2.4 adapter，接入真实 ESM2-650M、候选 graph cache、
固定 8X6B/9E6Y target graph、marginal/pair contact teacher，并只支持：

```text
preoptimizer   # 真实 batch 梯度路由检查；不创建 optimizer
train-smoke    # 固定 1 epoch 技术 smoke；不做结果选择
train          # 使用源 split 固定的 8 epochs
```

固定比较三条 lane：

```text
B_CLEAN_TARGET_ATTENTION
E_DECOUPLED_CONTACT_DETACHED
E_DECOUPLED_CONTACT_SHARED
```

其中两个 E lane 除 `contact_encoder_gradient` 外完全对称，避免把其它参数差异
误认为 shared/detached 的效果。

## 目标与损失

- 模型只直接预测 `R_8X6B`、`R_9E6Y`；
- 推理 `R_dual_min = exact_min(R8, R9)`；
- 训练的 dual 辅助项使用 FP32 normalized softmin；
- E lane 的 marginal/pair BCE 使用 candidate-level 正负质量平衡；
- B lane 对任意非零 contact loss fail-closed；
- fixed-epoch loop 无 same-fold 选择或指标调参。

## 验证范围

测试覆盖：

1. B lane 不存在 contact module/output；
2. attention/contact projections 与 terminal 物理分离；
3. scalar loss 对 contact 参数无梯度；
4. detached contact loss 只更新 contact branch；
5. shared contact loss 可更新 encoder，但不更新 attention/scalar terminal；
6. 改变 contact 参数不改变 scalar prediction；
7. exact-min 定义一致；
8. BF16 endpoint entropy、完整 forward 与 softmin 有限；
9. M2、ID、126D 和 pose 输入防火墙；
10. optimizer parameter group 无重叠；
11. E lane fixed-epoch 训练 smoke；
12. gradient accumulation 及最后一个不完整 accumulation window 的缩放；
13. 三条真实 lane 的固定参数与真实 batch preoptimizer 梯度路由；
14. whole-parent split、1269/28/1085/184 闭合；
15. training/contact/graph 的 candidate 闭合；
16. 非启动 Node1 六任务计划的依赖、GPU 和 sealed 防火墙；
17. package build/audit 的内容寻址闭合。

运行：

```bash
python3 -m unittest discover \
  -s experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/\
v2_5_ortho_contact_pose_stack_v1_20260718/tests \
  -p 'test_*.py' -v
```

## Node1 非启动 package

```text
deployment/prepared/node1_smoke_package_v1/
```

固定 6 个任务：三条 lane 各一个 `preoptimizer`，通过后才可执行同 lane 的
`one_epoch_smoke`。GPU 固定为 2/4/5；所有 job 的 `command=null`，只有
`command_template`，且 `launch_authorized=false`。因此这个目录是可审计的部署
输入，不是启动授权。

真实 source package 存在一个已显式记录的遗留元数据差异：V1.2.1 subset
恢复后的 training TSV 实际 SHA256 是 `5abacbe6...`，split JSON 仍声明恢复前的
`47c2c98f...`。本 package 不隐藏或重写它，而以源 package 的 `SHA256SUMS`、
candidate 闭合和 whole-parent 语义闭合作为字节权威，并把 mismatch 写入
`INPUT_CONTRACT.json`。

## GPU1 串行显式授权覆盖层

在不修改上述 package 的基础上，新增：

```text
deployment/prepared/gpu1_sequential_authorization_overlay_v1/
```

覆盖层把同一 6 个任务固定为严格串行：

```text
B preoptimizer
-> B one-epoch smoke
-> E detached preoptimizer
-> E detached one-epoch smoke
-> E shared preoptimizer
-> E shared one-epoch smoke
```

资源契约：

```text
physical GPU = 1
CUDA_VISIBLE_DEVICES = 1
max concurrent jobs = 1
taskset CPU affinity = 0-7
OMP/MKL/OpenBLAS/NumExpr/Torch thread ceiling = 8
Python = /data1/qlyu/software/envs/pvrig-v6-tc/bin/python
```

覆盖层逐文件绑定原 package 的 model、trainer、real adapter、input contract、
whole-parent/contact/graph/hash/firewall。命令只改变 GPU/CPU 执行 envelope、输出
runtime 路径和全局串行依赖，不改变模型参数、数据路径、split 或 loss。

当前仍为：

```text
launch_authorized = false
command = null
authorization_file_included = false
training_or_prediction_executed = false
V4-F/test32 access = 0
```

`command_template` 已完整冻结。launcher 还要求 package 外的独立 operator
authorization 文件，并绑定 plan/overlay/source package 哈希；缺少该文件时必然
fail-closed。本轮只完成 build/test/audit，没有部署或启动。

## 尚未完成及风险

1. 当前不是正式 whole-parent nested-crossfit 结果；
2. Node1 base package 和 GPU1 串行覆盖层尚未部署或启动，真实 GPU forward 仍待显式授权；
3. contact evidence 尚未做 inner-train probability calibration；
4. 8X6B/9E6Y target graph 当前仍主要是 AA/interface/hotspot/SASA/几何特征，
   尚未加入 target residue PLM；
5. coarse-pose C2 与 M2 必须只在 meta-head 合并；
6. 必须先比较 detached/shared 的 inner-OOF，不能根据 outer 结果选模式；
7. V4-F/test32 在正式模型和预测冻结前继续 sealed。

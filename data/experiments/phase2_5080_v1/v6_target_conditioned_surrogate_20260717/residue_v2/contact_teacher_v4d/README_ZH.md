# V4-D OPEN_TRAIN 多种子 Contact Teacher V2

## 目的与证据边界

本目录实现 `PLAN_V2_ZH.md` / `PREREGISTRATION_V2.json` 的第一步：从冻结的
V4-D OPEN_TRAIN Docking 坐标构建多种子 VHH–PVRIG residue-contact 监督。

它只表示：

```text
VHH 序列在独立 8X6B / 9E6Y 计算 Docking pose 中的接触频率
```

它不表示结合概率、Kd、实验竞争/阻断、Docking Gold 或最终提交证据。

本目录只包含合同、实现、测试和说明；当前提交没有运行 Node23 生产提取。

## 冻结输入范围

生产合同固定使用：

```text
/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715
```

只选择 `model_split=OPEN_TRAIN`：

| 项目 | 冻结数量 |
|---|---:|
| 候选 | 226 |
| parent clusters | 20 |
| 计划任务 | 1,356 |
| 成功任务 | 1,355 |
| 技术失败任务 | 1 |
| 完整 2 receptor × 3 seed 候选 | 225 |
| 部分技术重复候选 | 1 |

唯一 partial 候选：

```text
RFV1__PLDNANO_VHH_00322__A_CENTER__H3__B02__M00
8x6b: seed 917, 1931
9e6y: seed 917, 1931, 3253
```

缺失的 `8x6b/seed3253` 不补零，也不伪造重复。

## Sealed 边界

实现只从共享 candidate/job manifest 读取路由和身份元数据。完成 OPEN_TRAIN
筛选后，只打开选中 OPEN_TRAIN job 的：

```text
results/<job_id>/job_result.json
runs/<job_id>/haddock_run/6_seletopclusts/<model>.pdb.gz
```

禁止打开：

```text
OPEN_DEVELOPMENT job_result / pose
PROSPECTIVE_COMPUTATIONAL_TEST job_result / pose
reports/job_results.tsv
reports/pose_scores.tsv
```

后二者包含跨 split 汇总，因此只在 `CONTRACT_V2.json` 中保留来源哈希，不作为
extractor 输入。测试使用不可解析的 sealed job result，证明 sealed evidence 没有被打开。

## Contact 规则

顺序不可改变：

1. 每个 OPEN_TRAIN job 验证 candidate、sequence hash、receptor、seed、job hash、
   `protocol_core_sha256`；
2. 每个 selected model 必须具有完整 8X6B/9E6Y 两参考评分；
3. 先删除 job-native `overlay.t_ca_rmsd_a > 1.0 Å` 的 pose；
4. 对剩余 pose 按 `HADDOCK score, model name` 排序；
5. 过滤后取 Top-8，每 job 至少保留 4 个；
6. 只使用标准氨基酸 heavy `ATOM`，4.5 Å 接触阈值；
7. job 内 pose 权重为归一化 `1/log2(rank+1)`；
8. 每个 seed 独立形成 pair frequency 和 residue any-contact marginal；
9. 同 receptor 在实际成功 seeds 上等权平均；
10. variance 使用 observed seed 的 population variance；
11. uncertainty weight 为 `1/(1+4*variance)`。

pair 在某个**实际成功 seed** 中没有出现时，该 seed 的 pair frequency 为 0；这是
真实的非接触观察。技术失败、未观察到的 seed 不加入均值，不能被当作 0。

## 真正的 residue marginal

每个 pose 先计算：

```text
I(VHH residue i 是否接触任意 PVRIG residue)
```

然后执行 pose 加权和 seed 等权平均。因此：

```text
contact_marginal_mean
!= max_j(contact_target_mean_ij)
```

实现还检查 marginal 不得小于同一 VHH residue 的任何 pair target。

## 输出

生产运行会在一个全新目录中产生：

```text
v4d_open226_multi_seed_pair_contact_teacher_v2.tsv.gz
v4d_open226_multi_seed_residue_marginal_teacher_v2.tsv.gz
v4d_open226_top8_pose_inventory_v2.tsv.gz
EXTRACTION_AUDIT.json
RUN_RECEIPT.json
```

### Pair 表的 merger 核心字段

```text
candidate_id
sequence_sha256
parent_framework_cluster
receptor
vhh_sequence_index
vhh_aa
pvrig_uniprot_position
pvrig_aa
contact_target_mean
contact_target_variance
contact_uncertainty_weight
supporting_seed_count
observed_seed_count
expected_seed_count
```

### Residue marginal 表的 merger 核心字段

```text
candidate_id
sequence_sha256
parent_framework_cluster
receptor
vhh_sequence_index
vhh_aa
contact_marginal_mean
contact_marginal_variance
contact_marginal_uncertainty_weight
observed_seed_count
expected_seed_count
```

### Pose inventory

只包含 overlay 过滤后真正进入 Top-8 聚合的 pose，记录：

```text
candidate / receptor / seed / job / model / rank
HADDOCK score / native overlay / normalized weight
relative path / SHA256 / size
```

`RUN_RECEIPT.json` 再绑定整个 gzip inventory 的 SHA256，以及所有已打开
OPEN_TRAIN job-result JSON 的 canonical inventory hash。

## 测试

从仓库根目录运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/\
residue_v2/contact_teacher_v4d/tests/test_extract_v4d_contact_teacher_v2.py
```

测试覆盖：

- overlay 先过滤、再 Top-8；
- 多 seed mean / population variance / uncertainty；
- partial seed 不补零；
- 真正 any-contact marginal；
- merger 字段合同；
- sealed job result 不打开；
- protocol lock 与 partial identity 冻结；
- PDB 序列不一致 fail-closed；
- 单进程与双进程输出 byte deterministic；
- raw source 不变。

## 生产命令模板（本次未执行）

```bash
python3 src/extract_v4d_contact_teacher_v2.py \
  --raw-root /data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715 \
  --contract CONTRACT_V2.json \
  --output-dir /data/qlyu/projects/<NEW_VERSIONED_OUTPUT> \
  --workers 8
```

输出目录必须预先不存在；实现不会覆盖既有结果，也不会修改原始 campaign。

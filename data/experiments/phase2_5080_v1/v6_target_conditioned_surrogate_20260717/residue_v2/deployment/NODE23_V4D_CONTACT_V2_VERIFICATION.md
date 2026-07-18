# Node23 V4-D Contact Teacher V2 独立验证

## 结论

```text
PASS_INDEPENDENT_NODE23_V4D_CONTACT_V2_VERIFICATION
```

验证时间：`2026-07-18T07:51:22+08:00`

远程生产根目录：

```text
/data/qlyu/projects/pvrig_v6_residue_v2_contact_teacher_20260718
```

本次为只读验证；未修改 Node23 数据，未修改 extractor/contract，也未同步任何大文件到本地。

## 运行终态

启动时记录的 launcher PID 为 `801181`；验证时 launcher 和 extractor
均已退出，无残留 worker。

`status/terminal.json`：

```json
{
  "return_code": 0,
  "schema_version": "pvrig_v6_v4d_contact_teacher_v2_terminal",
  "status": "PASS_V4D_CONTACT_TEACHER_V2"
}
```

部署的 extractor/contract 与当前本地字节一致；tests 哈希是生产启动时冻结的
测试字节。生产后本地只修正了合成 gzip fixture 的 mtime 非确定性，详见
`contact_teacher_v4d/TEST_FIXTURE_CORRECTION_V2_1.md`，该修正不改变 extractor、
contract 或真实教师输出：

```text
extractor  6e7d41fa23ff0e3dec60796d01fb7c9622e3ab8caed3e0a6ad4dd326ab904efb
tests      06992ff7dfe874d4d00baf453b098eec46177f123aa3d2d604204e5fb029ed89
contract   ff220a5b1544c0e75bc587c91db60ac84798d37500e8a6bee640de99c92171d7
README     5706289f2296a3a9cf0fbf8c83a6ef1e1727480cdc6d7d76ec70409cdb14d046
```

Node23 launcher 在生产提取前先运行了完整测试：

```text
Ran 6 tests
OK
```

## Receipt / Audit 状态

```text
RUN_RECEIPT.status
= COMPLETE_V4D_OPEN226_MULTI_SEED_CONTACT_TEACHER_V2

EXTRACTION_AUDIT.status
= PASS_V4D_OPEN_TRAIN_MULTI_SEED_CONTACT_CLOSURE
```

receipt 与 audit 的计数完全一致，且等于冻结合同：

| 项目 | 独立复核值 |
|---|---:|
| teacher candidates | 226 |
| parent clusters | 20 |
| scheduled OPEN_TRAIN jobs | 1,356 |
| successful jobs | 1,355 |
| failed jobs | 1 |
| complete three-seed candidates | 225 |
| partial candidates | 1 |
| selected poses before filter | 12,725 |
| invalid native-overlay poses | 85 |
| valid poses after filter | 12,640 |
| Top-8 pose inventory rows | 10,632 |
| pair rows | 132,874 |
| residue marginal rows | 55,138 |
| zero-imputed failed seeds | 0 |

唯一失败 job 和 partial candidate 与冻结合同一致：

```text
failed job:
CANDIDATE_RFV1__PLDNANO_VHH_00322__A_CENTER__H3__B02__M00_8x6b_s3253_447e4cf0dc26

partial candidate:
RFV1__PLDNANO_VHH_00322__A_CENTER__H3__B02__M00
```

该候选的 `8x6b` 为 2 个 observed seeds，`9e6y` 为 3 个；其余
225 条在两受体上均为 3 个 seeds。

## 输出哈希与 gzip 完整性

独立重新计算的 SHA256：

```text
pair teacher
39b600e6979e72ef89237070b36a1f7afaecb4be5be4735d1650d55cd17811a8

residue marginal teacher
1f5906df603fdbaea166c992c93bb4ff1b95c22cccff80739cedbc892a6c6e8e

pose inventory
32ea99b24277726328ba5303a532ba7cb053790588b5267beef85edf7265a042

EXTRACTION_AUDIT.json
fc638279ecc5a76a5dec68f1ac89b596fd1b5ac1b5853cebe09b4539e513cbe8
```

上述哈希同时与 `RUN_RECEIPT.json` 及 `EXTRACTION_AUDIT.json` 内嵌值一致。

三个 gzip TSV 均通过：

```text
gzip -t
PASS_GZIP_CRC_ALL_3
```

物理解压后数据行数（不含 header）：

```text
pair rows             132874
residue marginal rows  55138
pose inventory rows    10632
```

本地未保存这些大输出；Node23 输出目录总大小约 `4.59 MB`。

## Candidate / Sequence / Receptor 闭包

逐行验证通过：

- pair、residue marginal、pose inventory 的 candidate set 都精确等于 OPEN_TRAIN 226；
- 226 条共属于 20 个 parent clusters；
- residue 表形成精确 `226 × 2 = 452` 个 candidate/receptor 组；
- 每个 candidate/receptor 的 VHH index 从 1 到 sequence length 连续且无重复；
- `sequence_sha256`、`parent_framework_cluster`、`vhh_aa` 均与冻结 candidate manifest 一致；
- pair target、variance、uncertainty 和 seed-count 取值范围及公式全部通过；
- marginal 不小于同一 VHH residue 任一 pair target，保持 true any-contact 语义。

## Pose Inventory 闭包

```text
inventory jobs     1355
poses per job      4–8
unique job/model   10632/10632
overlay RMSD       all <= 1.0 A
rank               each job contiguous from 1
pose weight sum    each job = 1 within numerical tolerance
```

还对 inventory 中全部 `10,632` 个原始 PDB gzip 重新计算了文件大小和
SHA256：

```text
PASS_POSE_INVENTORY_RAW_BYTE_CLOSURE
files: 10632
raw compressed bytes: 383856740
missing/symlink/size mismatch/SHA mismatch: 0
```

## Sealed / Read-only 边界

receipt 和 audit 均记录：

```text
sealed_result_files_opened    0
sealed_pose_files_opened      0
shared_job_results_tsv_opened 0
shared_pose_scores_tsv_opened 0
source_mutation_operations    0
```

`sealed_candidate_metadata_rows_seen=64` 仅表示从共享 manifest 看到路由/身份
元数据；对应的 job result、pose 和 contact label 均未打开。

## 最终判断

该产物已满足当前 V2 的 V4-D OPEN_TRAIN multi-seed contact teacher 输入
闭包，可进入下一步的 V4-D/V4-H dual-source contact target merge。

它仍只是 computational Docking contact supervision，不得对外宣称为实验
binding/blocking 标签。

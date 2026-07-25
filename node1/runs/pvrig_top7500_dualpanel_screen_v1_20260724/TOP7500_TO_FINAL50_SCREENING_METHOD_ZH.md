# PVRIG 两批 Top7500 到 Final50 的筛选方法

## 1. 目的和证据边界

本流程用于从两批已经完成 docking 的 PVRIG VHH 候选中，依次形成 Top200
静态复核池、Top80 精细池、Final50 提交组合和 Top10 优先实验组合。

最终结果是经过合规性、阻断几何、可开发性、多样性、静态结构和短 MD
联合审计的**计算优先级**。它不能替代实验 BLI、Kd、IC50、表达量、纯度
或真实阻断活性。

## 2. 总体漏斗

```text
两批既有 docking
  ├─ old priority：25,000 jobs
  └─ C2 four-seed：41,760 jobs
        ↓
候选级去重与证据聚合：13,720条
        ↓
strict docking gate：6,042条
        ↓
positive-calibrated developability gate：6,041条
        ↓
完整 QC：2,000条
        ↓
Top200：静态复核池
        ↓
400个静态 pose jobs
        ↓
Top80：精细池
        ↓
20候选 × 3 seeds × 2 ns MD＝60条轨迹
        ↓
Final50 + Top10
        ↓
官方 validator、完整相似性、组合约束和 hash 审计
```

## 3. 两批 docking 证据归一化

### 3.1 输入

- 旧路线：25,000 docking jobs；
- C2 四 seed 路线：41,760 docking jobs；
- 序列去重后：13,720条候选。

每条候选被统一整理为候选级证据，包括：

- 8X6B、9E6Y 双参考覆盖；
- 多 seed 成功率和一致性；
- 有效 pose 比例；
- blocker-like A/B pose 比例；
- PVRIG 界面和热点接触；
- PVRL2 界面空间遮挡；
- CDR3 接触贡献；
- pose-pair 共识；
- 双构象和双参考一致性；
- 技术失败与几何失败的分离状态。

技术失败、缺失输出和 `TECHNICAL_NA` 不被计为生物学阴性。

### 3.2 Docking 主门控

主要 docking 指标是：

1. `blocking_consensus_score`；
2. `pose_robustness_score`；
3. 多 seed 成功比例；
4. 双构象覆盖率；
5. 双参考一致性；
6. blocker-like A pose 比例；
7. PVRL2 竞争界面遮挡；
8. PVRIG 热点接触；
9. CDR3 对界面的贡献；
10. 有效 docking job 比例。

优先保留多 seed、双构象和双参考结论一致，并且由 CDR 主导功能界面接触
的候选。单个异常 pose、framework 主导、严重 clash 或仅表现为普通 binder
几何的候选不进入高优先级。

结果：

- strict docking hardpass：6,042条；
- 加入阳性校准的可开发性门控后：6,041条。

## 4. 完整序列 QC：2,000条

从 docking 和序列风险综合排序中选择2,000条执行完整 QC。

### 4.1 合规与完整性

- 官方 `ab-data-validator`；
- 标准20种氨基酸；
- ANARCI/IMGT 编号；
- VHH heavy variable domain 识别；
- FR1/2/3/4、CDR1/2/3 完整性；
- 长度、保守 Cys 和 FR4 motif 合理性。

### 4.2 CDR 新颖性

- 与官方和本地阳性参照逐个比较 CDR1/2/3；
- 任一对应 CDR identity `>=0.80` 为 hard fail；
- `0.75–0.80` 标记为边界风险；
- 最终50重新运行官方 validator，不复用早期推断结果。

### 4.3 VHH 属性和自然度

- FR2 VHH hallmark；
- 单域适配性；
- AbNatiV VHH/FR 分数；
- Sapiens 自然度和建议突变数。

### 4.4 可开发性

- TNP/polyreactivity 风险；
- pI、pH 7 净电荷、MW、GRAVY、instability index；
- 非预期 Cys；
- N-糖基化 motif；
- 脱酰胺、氧化、异构化和剪切风险；
- 连续疏水片段；
- 表达、纯度和聚集风险 proxy。

这些指标用于提前排除明显风险，但不是实验表达量或纯度。

完整 QC 结果：2,000/2,000完成。

## 5. Top200 静态复核池

Top200不是简单截取总分前200，而是按证据通道组成：

| 通道 | 数量 |
|---|---:|
| `CORE_EXPLOITATION` | 120 |
| `PARENT_CDR3_DIVERSITY` | 40 |
| `STRUCTURAL_RESERVE` | 20 |
| `QUOTA_SAFE_BACKFILL` | 20 |

选择时执行：

- exact sequence duplicate＝0；
- exact CDR3 duplicate＝0；
- 任意同长度 CDR3 直接 identity `<0.80`；
- 保留 parent/CDR3 多样性；
- 同时保留 old 和 C2 两条路线；
- 单链连接分量仅报告，不作为小配额硬门控。

Top200最大同长度直接 CDR3 identity 为 `0.7894736842`。

## 6. Top200 静态结构复核

每条候选检查两个冻结构象，共400个静态 jobs。

### 6.1 原子级指标

- 界面原子接触数；
- 界面残基对数；
- 接触密度 proxy；
- 2 Å 物理 clash proxy；
- 氢键和盐桥距离 proxy；
- 疏水界面接触；
- CDR/CDR3 接触贡献；
- framework 异常主导；
- 暴露疏水残基；
- 暴露 PTM 风险位点。

### 6.2 软件指标的角色

- Rosetta InterfaceAnalyzer：`DESCRIPTIVE_ONLY`；
- PRODIGY：`WEAK_PRIOR_ONLY`；
- FoldX 跨候选绝对排序：阳性校准未通过，本轮标为
  `NOT_RUN_CROSS_CANDIDATE_RANK_REJECTED`。

静态软件不覆盖多 seed docking 主证据，也不直接解释为 Kd。

结果：400/400 jobs完成，失败0。

## 7. Top80 精细池

Top80继续使用分层配额：

| 通道 | 数量 |
|---|---:|
| `CORE_EXPLOITATION` | 48 |
| `PARENT_CDR3_DIVERSITY` | 16 |
| `STRUCTURAL_RESERVE` | 8 |
| `QUOTA_SAFE_BACKFILL` | 8 |

重点降低以下候选的优先级：

- clash 过高；
- 接触密度过低；
- framework 主导；
- CDR3 几乎不参与；
- 两构象差异过大；
- 只有单 seed 支持；
- 序列或可开发性风险偏高。

Top80 exact CDR3 duplicate为0，最大同长度直接 CDR3 identity仍为
`0.7894736842`。

## 8. Top80 中20条的短 MD

从Top80选择20条具有代表性的候选：

- 每条3个速度 seed；
- 每条2 ns；
- 共60条轨迹；
- 使用物理 GPU `0,1,2,4`；
- 总计最多16条轨迹、32 CPU threads并发；
- 每条轨迹拥有独立目录、随机 seed 和 checkpoint。

### 8.1 MD分析指标

- VHH RMSD；
- 复合物 RMSD；
- CDR3 RMSF；
- 界面接触保持；
- PVRIG 热点接触保持；
- 界面氢键保持；
- 三个 seed 的中位数和范围。

短 MD 仅判断起始 docking pose 是否快速散开以及 seed 间是否稳定。
二元 PVRIG–VHH MD 不能直接观察 PVRL2，因此：

```text
md_role = DESCRIPTIVE_ONLY
pvrl2_occlusion_retention_status =
NOT_DIRECTLY_OBSERVABLE_IN_BINARY_MD
```

MD结果：60/60轨迹完成，失败0；产生60条 trajectory metrics和20条
candidate summaries。

## 9. Final50 组合

Final50继续采用组合优化，而不是纯总分截断：

| 通道 | 数量 |
|---|---:|
| `EXPLOITATION` | 30 |
| `PARENT_MECHANISM_DIVERSITY` | 10 |
| `STRUCTURAL_DIVERSITY_RESERVE` | 5 |
| `QUOTA_SAFE_BACKFILL` | 5 |

硬约束：

- 50条序列全部唯一；
- CDR3全部唯一；
- 任意同长度 CDR3 identity `<0.80`；
- 单一 parent 最多15条；
- 单一路线最多35条；
- 至少4个 parent clusters；
- 官方 validator全部通过；
- 与阳性参照 CDR identity全部低于80%；
- 最终 QC hard fail＝0。

实际结果：

- parent clusters：5；
- 单一 parent 最大：15；
- old路线：28；
- C2路线：22；
- 最大同长度直接 CDR3 identity：`0.7894736842`；
- 官方 validator：50/50通过；
- similarity filter：50/50通过；
- hard fail：0。

## 10. Top10 优先组合

Top10由：

- 7条 `HIGHEST_CONFIDENCE_CORE`；
- 3条 `INDEPENDENT_PARENT_OR_MECHANISM`。

约束：

- 单一 parent 最多4条；
- 单一路线最多7条；
- 实际覆盖4个 parent clusters；
- old路线4条、C2路线6条。

## 11. 证据优先级

```text
提交合规和CDR新颖性 hard gate
→ 多seed/双构象/双参考阻断几何
→ VHH可开发性和表达纯度风险
→ 候选间多样性与parent/路线配额
→ 静态结构诊断
→ 短MD pose-persistence复核
```

Rosetta、PRODIGY和短 MD 不能单独把候选判定为实验 binder/blocker。

## 12. 关键产物和验证

- `run/top200/top200_pre_static.tsv`：200条；
- `run/static_review/STATIC_POSE_METRICS.tsv`：400行；
- `run/top80/top80_post_static.tsv`：80条；
- `run/md/reports/md_trajectory_metrics.tsv`：60条；
- `run/md/reports/md_candidate_summary.tsv`：20条；
- `run/final50/final50_ranked.tsv`：50条；
- `run/final50/top10_priority.tsv`：10条；
- `run/final50/FINAL50_COMPLETE.json`；
- `run/final50/GOAL_COMPLETION_AUDIT.json`。

最终完成审计：

- 29/29 checks通过；
- 新鲜单元测试15/15通过；
- 审计 SHA256：
  `6f72b08248299922328c0d6469147a364f7df7870e88effe4bd5ddc981d70dcc`。

## 13. 多 seed 覆盖、工具覆盖和已知局限

### 13.1 并非13,720条全部具有两个以上完整 seed

候选级实际覆盖为：

| 完整 docking seed 数 | 候选数 |
|---:|---:|
| 0 | 5 |
| 1 | 3,506 |
| 2 | 4,992 |
| 3 | 1,018 |
| 4 | 4,199 |

因此，13,720条中有10,209条（74.4%）具备至少两个完整 seed，3,511条
只有部分 docking 证据。这里的“一个完整 seed”要求该 seed 的8X6B和9E6Y
两个构象 docking 都成功；不是只要存在一个输出文件。

部分证据候选没有进入主 Top200。最终各层实际覆盖为：

| 层级 | 2 seeds | 3 seeds | 4 seeds | 少于2 seeds |
|---|---:|---:|---:|---:|
| Top200 | 67 | 39 | 94 | 0 |
| Top80 | 31 | 13 | 36 | 0 |
| Final50 | 19 | 9 | 22 | 0 |
| Top10 | 3 | 1 | 6 | 0 |

Final50的50条全部满足“至少2个完整 seed”，并且其每个完整 seed 都通过
规定的 strict 双构象判断。但不同路线仍然使用2、3或4个 seed，证据强度
不是完全对称。

尤其需要注意：

- old路线按至少2个完整且strict的seed进入主门控；
- C2 four-seed路线要求4/4个seed全部strict；
- 2,000条 `c2_two_seed` 候选在本轮被标为 `NOT_G3_READY`，没有进入主
  strict池。这是保守的协议可比性选择，不代表它们是生物学阴性，也可能
  因此漏掉真实阳性。

### 13.2 分层配额对Final50的影响

如果只按Top80中的计算分数直接取前50，与当前受多样性约束的Final50有
41条重叠，另外9条被parent、路线、CDR3和机制通道配额替换。

因此组合约束改变了18%的名单。它降低了单一parent或单一路线押注失败的
风险，但可能牺牲少量纯分数排名。

### 13.3 已使用的软件

| 工具 | 本轮实际角色 |
|---|---|
| `ab-data-validator` | 最终提交合规和官方CDR相似性hard gate |
| ANARCI/IMGT、MUSCLE | 编号、CDR提取和相似性计算 |
| DeepNano/NanoBind | sequence-only binding weak prior |
| AbNatiV、Sapiens | VHH自然度和可开发性 |
| TNP | polyreactivity/developability风险；不能判断阻断 |
| NanoBodyBuilder2/ImmuneBuilder | 上游单体结构和序列-结构一致性 |
| HADDOCK3 | 双构象、多seed docking主证据 |
| Rosetta InterfaceAnalyzer | 静态描述性复核，rank contribution＝0 |
| PRODIGY | 弱先验，不能解释为真实Kd |
| GROMACS | 20候选、60条短MD pose-persistence复核 |

### 13.4 已安装但没有进入本轮最终主排名的软件

- FoldX：已安装，但阳性校准不支持跨候选绝对排名，因此明确拒绝作为
  Final50主排名项；
- IgFold、NanoNet：未对Final50执行完整跨工具FR RMSD；
- Chai-1、Boltz-2：未对Final50运行独立复合物预测；
- RF2 blind pose recovery：未纳入这次两批Top7500末端筛选；
- RFantibody：用于上游生成，不是本轮末端QC排名器；
- Node1 `/data/qlyu/software` 中未发现名称含 `Plano` 的安装目录；如果
  “Plano”指的是另一个具体软件，需要按准确名称单独接入和校准。

### 13.5 当前不能回避的技术缺口

- Final50中只有15条进入短MD，另外35条是 `NOT_RUN_RESERVE`；
- Top10中5条有短MD，5条没有；
- Final50虽然上游 NanoBodyBuilder2 为50/50成功且序列匹配，但最终QC的
  跨工具 `FR_RMSD_cross_tool` 仍为空；
- Final50最终TNP复跑中有15条技术错误。上游缓存记录仍为PASS，所以这些
  候选没有被判为hard fail，但TNP证据不能称为50/50重新验证成功；
- Rosetta、PRODIGY和MD均被限制为描述性或弱先验，没有实际改变主排名；
- 缺少足量已知阴性和湿实验标签，无法从当前数据计算真实灵敏度、特异度
  或Final50实验阳性率。

所以本流程在计数、hash、可复现性和门控执行方面是规范的；在生物学预测
方面属于中等置信度的计算优先级，而不是高确定性的阳性判定。

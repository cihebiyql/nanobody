# PVRIG Final50：VHH-hFc 制造/格式补充执行结果 v1.1

日期：2026-07-25  
计划：`机制/reports/PVRIG_Final50_VHHhFc_制造格式补充执行计划_v1_20260725.md`  
对象：四 seed、双构象机制重排后的 Final50；不改写已有机制排名。

## 1. 执行结论

已完成三项可执行补充，并完成独立审计：

1. **TNP 六分量补齐**：50/50 成功，所有候选均有 `L/L3/C/PSH/PPC/PNC` 六项原始结果。
2. **结构制造侧车**：在 Final50 的 `50 × 4 seed × 2 构象 = 400` 个代表 HADDOCK 复合物上完成近似 SASA、表面疏水/电荷 patch、CDR PTM 暴露/接触及 C 端可达性统计。
3. **通用 VHH-hFc 格式 pilot**：Top2（D1 核心）和 Top10（D3 格式风险）各跑短/长 G4S linker 情景，4 个任务、8 个 Chai-1 模型。因跨链 ipTM 为 `0.116–0.250` 且主办方未定义实际 linker/hinge/Fc 序列，判定为 `COMPLETE_NO_EXPANSION`：该模型不足以可靠地按 VHH–Fc 相对取向筛选 Top10。

独立审计：50 条、Top10 10 条、TNP 50/50、结构 pose 400/400、机制排名未改变，均通过。

## 2. 资源与可复现性

- Node1 上限：32 CPU 线程、GPU 0–3；没有写入空间紧张的 `/data1`。
- TNP 的全局依赖存在 ImmuneBuilder/OpenMM 线程属性兼容问题。为避免影响其他项目，仅在本次输出目录中复制并修复依赖副本；原始全局安装没有被修改。
- TNP 的可选 PDB 注释仍会出现非致命后处理提示；六项主 JSON 已逐条验证完整，因此不将该注释错误记为候选失败。

## 3. 新增数据结果

### 3.1 TNP 完整分量

| 分量 | green | amber | red |
|---|---:|---:|---:|
| L | 50 | 0 | 0 |
| L3 | 50 | 0 | 0 |
| C | 50 | 0 | 0 |
| PSH | 41 | 9 | 0 |
| PPC | 45 | 0 | 5 |
| PNC | 50 | 0 | 0 |

这证明此前“总 PASS”不能替代逐分量记录。PSH amber 和 PPC red 一律进入 review，不是 hard fail，也不等价于实际 CHO 表达、SEC、纯度或 polyreactivity 结论。

### 3.2 400 pose 结构侧车

- 50/50 候选均无 C 端与 PVRIG 的直接接触（4.5 Å 判定）。
- 每条候选 8 pose 中，C 端到 PVRIG 的最小距离范围为 `25.63–36.25 Å`，中位数 `30.74 Å`。
- 最大表面疏水 patch 的残基数中位数为 `11.75`，范围 `4.0–21.5`；此为几何 proxy，不是 HIC、SEC 或聚集测定。
- DP/DG/DS 等 liability 采用“游离暴露、结合遮蔽、PVRIG 接触”三者共同记录。暴露 motif 仅作 review，不能机械删除。

### 3.3 Top10 的新增判读

- #2、#6、#7、#9：仍为 D1 proxy；其中 #2 的通用 hFc pilot 完成但低置信，不能据此额外加分。
- #3：TNP 六分量出现 review，保留第二层 D2，不升级为核心制造位。
- #1、#4、#5：D2，机制证据保留，制造侧车继续 review。
- #8、#10：D3；#8 有暴露非接触 acid-clipping 迹象，#10 更强（31 条 pose-residue 记录），均保留为高风险格式/机制对照，不作为唯一主力。
- #9：保持 PVRIG-38 parent 多样性位；不能因其 D1 proxy 就超越机制主排序。

## 4. 格式模型为何停止在 pilot

官方规则只规定 VHH-hFc，没有披露实际 hinge/linker/Fc 的精确氨基酸构建。通用 human-IgG1-hFc 情景下模型虽未报告显式跨链 clash，但柔性 linker 对相对取向缺乏稳定预测：所有 scenario 的 ipTM 均低。因此：

```text
C端无 target 接触 → 可作为窄范围的格式可达性正信号；
通用 hFc 共折叠 → 当前不具备跨候选排名资格；
实际 CHO / Protein A / SEC / 纯度 → 仍只能由湿实验确认。
```

不扩展到 Top10/Top20，避免用低置信模型制造虚假的制造排序。

## 5. 固化后的流程变化

```text
机制主排序：保持 common4 four-seed / dual-conformation blocker geometry
制造侧车：TNP 六项 + 结构 patch + PTM 暴露/接触 + C端可达性
格式证据：仅在取得主办方真实 hinge/linker/Fc 序列后重启全格式模型
组合选择：mechanism rank 与 D1/D2/D3、TNP review、parent/CDR3 diversity 并列展示
```

禁止：把上述 proxy 解释为预测 Yield（mg/L）、SDS/HPLC 纯度、SEC 主峰、Tm/Tagg、Protein A 低 pH 聚集、BLI、Kd、IC50 或实验阻断。

## 6. 文件位置

### 本地

- `机制/data/audits/PVRIG_Final50_制造格式侧车_v1_1_20260725.tsv`
- `机制/data/audits/PVRIG_Final50_Top10_实验投放侧车_v1_1_20260725.tsv`
- `机制/data/audits/PVRIG_Final50_TNP六分量补齐_v1_20260725.json`
- `机制/data/audits/PVRIG_Final50_通用hFc格式pilot_v1_20260725.json`
- `机制/data/audits/PVRIG_Final50_制造格式侧车_FINAL_AUDIT_v1_1_20260725.json`

### Node1 主结果

```text
/data/qlyu/projects/pvrig_top7500_dualpanel_screen_v1_20260724/run/
  final50_vhhfc_developability_v1_20260725/
    PLAN_ZH.md
    tnp/patched_all50/TNP_Results_Multientry.json
    structure_sidecar/final50/
    format_pilot/FORMAT_PILOT_ASSESSMENT.json
    reports/integrated_v1_1/
```

`reports/integrated/` 的 Top10 dispatch 文件分隔符错误，未影响候选、分数或排名；已明确 supersede，后续只使用 `reports/integrated_v1_1/`。

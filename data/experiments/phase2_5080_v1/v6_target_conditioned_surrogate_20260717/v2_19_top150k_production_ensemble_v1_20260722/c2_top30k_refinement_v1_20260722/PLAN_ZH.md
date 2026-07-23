# V2.19 C2 Top30K 自动精排 V1

## 目标

等待冻结四模型阶段产生 `STAGE1_TOP30000_FOR_C2.tsv`，仅使用候选序列、NBB2
单体结构、固定公开 PVRIG 8X6B/9E6Y 结构与接口掩码，运行冻结 V2.5
`300 poses × 2 receptors` 粗姿势扫描，并调用冻结 V2.11 C2/多模态模型，对 30,000
条预池重新排序，最终输出 7,500 条供独立 Docking。

本阶段是 **label-free computational Docking-geometry surrogate**；不读取任何候选
Docking 结果、teacher/实验标签，也不输出可校准的结合或阻断概率。

## 冻结流程

1. 验证 preliminary receipt、Stage-0、NBB2 staging receipt 的输出哈希；
2. 对 candidate ID、sequence SHA256、parent 做精确闭合，生成 32 个 C2 shard manifest；
3. 复用 SHA256 固定的 V2.5 coarse-pose extractor 与固定 target 资产；
4. 合并 36D 原始特征，删除两个 pose-count 与两个 entropy QC 列，形成冻结 32D C2；
5. 复用冻结 V2.11 artifact 与 V2.19 multimodal adapter 的预测函数，产生 C2、M2+C2、
   S0+M2+C2、shallow-GBDT 四条互补 lane；
6. 最终融合固定为：

   ```text
   80% four-model preliminary utility
   15% S0+M2+C2 convex rank percentile
    5% M2+C2 convex rank percentile
   ```

7. 输出 6,750 consensus、500 L1/B rescue、250 parent-balanced diversity，共 7,500 条。

## 停止条件

只有在所有 shard receipt、target/code/model hash、candidate/sequence/parent closure、
32D 有限值、最终配额与零 truth access 全部通过时，才发布 terminal receipt。

# SICBC 2026 抗体赛道官方信息摘录

官方页面：

```text
https://www.bioshanghaiweek.com/2026/SICBC?lan=cn&section=5
```

复核时间：2026-07-06
读取方式：agent-reach web 路由 / Jina Reader

## 与机制探究直接相关的信息

官方赛题说明中，PVRIG/CD112R 被定义为 DNAM-1/TIGIT/CD96/PVRIG 免疫调控轴中的抑制性受体，主要表达于 CD8+ T 细胞和 NK 细胞表面。其主要配体为 PVRL2/CD112/Nectin-2，常表达于肿瘤细胞和抗原提呈细胞表面。

官方机制要点可以概括为：PVRIG 与 PVRL2 结合后会向效应免疫细胞传递抑制性信号，降低 T/NK 细胞活化、增殖、细胞因子分泌和杀伤功能。因此，本项目后续设计目标不是简单结合 PVRIG，而是阻断 PVRIG-PVRL2 相互作用。

## 官方指定结构

官方推荐参考结构：

```text
8X6B: Crystal structure of immune receptor PVRIG in complex with ligand Nectin-2
9E6Y: Structure of CD112 (Nectin-2) domain 1 bound to CD112R (PVRIG)
```

这就是当前 `机制/` 包先围绕 8X6B / 9E6Y 做共识界面和可视化的依据。

## 官方指定表位方向

官方要求候选抗体结合 PVRIG 胞外区，并优先靶向 PVRIG 与天然配体 PVRL2 的结合界面，以实现阻断 PVRIG-PVRL2 相互作用的功能目标。

这句话是当前机制可视化和 hotspot 定义的直接依据：后续模型必须从 `binding score` 进一步走向 `blocking-oriented interface coverage`。

## 官方阳性参考和相似性约束

官方给出：

- Tab5：IgG 抗体，提供 VH/VL 序列；
- HR-151：VHH 抗体，提供 VHH 序列。

官方还说明 CDR 相似性原则上应低于 80%，相似性计算使用 ANARCI 按 IMGT 编号确定 CDR，再用 MUSCLE/Hamming/Identity 计算。

## 官方实验评价对机制模型的影响

官方初筛会看表达、纯度和 BLI 结合；复筛会重点看 Kd 和竞争 ELISA 的 IC50。因此后续模型不能只追求结构贴合或 docking score，而要同时考虑：

```text
1. PVRIG-PVRL2 interface 识别；
2. blocking-oriented epitope coverage；
3. PVRIG binding + PVRL2 competition；
4. developability / expression / purity 风险；
5. 与 Tab5 / HR-151 等阳性参考 CDR 相似性排除。
```

当前 `机制/` 文件夹主要解决第 1 和第 2 的结构机制基础。

## 后续继续参考官网时要注意

官网页面可能继续更新；正式提交前应再次复核日期、附件、评分规则和 validator 链接。本文件只作为 2026-07-06 的机制相关摘录。

# PVRIG 新 Final50：统一序列与结构包

- `sequences/`：Final50 与 Top10 的 FASTA。
- `tables/`：排序、筛选与逐条指标。
- `docking/representative_complexes/`：每条 Final50 候选在 4 个随机 seed × 2 个受体构象下的代表 HADDOCK 复合物，合计 400 个未压缩 PDB。
- `docking/representative_models_manifest.tsv`：每个 PDB 与候选、Final50/Top10 排名、seed、构象、HADDOCK 分数、原始归档和 SHA256 的映射。
- `docking/archives/`：400 个原始紧凑 job archive 的符号链接；每个 archive 含该 job 的全部 10 个 selected cluster PDB、HADDOCK 配置、日志及技术收据。

注意：PDB 是计算 docking 结构，用于复核和比较，不能解释为实验结合、亲和力或阻断已获证明。

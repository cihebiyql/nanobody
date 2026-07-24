# Top5000 双受体四 seed Docking handoff builder

`build_top5000_dualreceptor_4seed_handoff_v1.py` 只物化交付包，不启动
HADDOCK、Slurm 或任何调度器。

## 生产命令

```bash
python3 build_top5000_dualreceptor_4seed_handoff_v1.py \
  --release-tsv /path/to/TOP5000_RELEASE.tsv \
  --release-fasta /path/to/TOP5000_RELEASE.fasta \
  --shortlist-tsv-gz /path/to/SHORTLIST100K.tsv.gz \
  --nbb2-manifest-tsv-gz /path/to/NBB2_AGGREGATE_MANIFEST.tsv.gz \
  --nbb2-archive /path/to/node_000.tar.gz \
  --nbb2-archive /path/to/node_001.tar.gz \
  --nbb2-archive /path/to/node_002.tar.gz \
  --nbb2-archive /path/to/node_003.tar.gz \
  --nbb2-archive /path/to/node_004.tar.gz \
  --nbb2-archive /path/to/node_005.tar.gz \
  --nbb2-archive /path/to/node_006.tar.gz \
  --nbb2-archive /path/to/node_007.tar.gz \
  --template-root /path/to/frozen_template_root \
  --output-root /path/to/new_handoff_root \
  --created-at 2026-07-24T12:00:00+08:00
```

生产模式固定门禁：

- release TSV/FASTA：恰好 5,000 条，ID 与序列集合精确闭合且分别唯一；
- shortlist：恰好 100,000 行，Top5000 join 恰好 5,000；
- `IMGT_CDR1/2/3`（兼容同义小写列名）必须各自在完整序列中唯一出现，
  据此推导 1-based sequence range，再映射到 PDB chain H residue ID；
- NBB2 aggregate manifest：Top5000 join 恰好 5,000，状态为 `SUCCESS`，
  sequence hash 一致；
- 恰好 8 个非 symlink tar.gz；每个选中成员必须为安全路径下的普通文件，
  解包字节数及 SHA256 必须匹配 manifest；
- PDB chain H 序列必须等于 release 序列；
- protocol core 固定为
  `8c55751f66ac2930ce115a9419321a2b2bed220b61af2e1671f7ac6e6a2e33b3`；
- 生产构建必须存在非 symlink 普通文件
  `scripts/validate_protocol.py` 和
  `scripts/aggregate_external_candidate_results.py`；此外会复制存在且非
  symlink 的 `scripts/aggregate_results.py`、`scripts/status.py` 及三个
  `inputs/source/` reference 文件。所有复制项均逐文件写入 receipt SHA256；
- 8X6B/9E6Y × seeds 917/1931/42/3047 的八个 cfg hash 固定；
- 每个 job 除 `job_id/job_hash/job_hash_basis` 外的全部 manifest 字段进入
  canonical JSON hash basis；`job_id` 再绑定该 job hash；
- 40,000 jobs 按完整候选八-job unit 分配到 8 个 shard，每 shard 5,000
  jobs、625 candidates、每个 receptor/seed 组合 625 jobs，hash 集合精确闭合。

## 主要输出

```text
HANDOFF_RECEIPT.json
READY.json
SHA256SUMS
PROTOCOL_CORE_LOCK.json
config/FOUR_SEED_CFG_LOCK.json
inputs/top5000_candidates.tsv
inputs/candidate_monomers/*.pdb       # 5,000
inputs/source/*                       # 源 reference 存在时复制
manifests/docking_jobs.tsv            # 40,000
manifests/shards_exact_8/shard_00.tsv
...
manifests/shards_exact_8/shard_07.tsv
manifests/shards_exact_8/SHARD_RECEIPT.json
scripts/validate_protocol.py
scripts/aggregate_external_candidate_results.py
scripts/aggregate_results.py           # 存在时复制
scripts/status.py                      # 存在时复制
```

输出根必须事先不存在。构建使用同目录 staging，任何异常都会清理 staging，
不会留下半成品或覆盖既有交付。

## 无 pytest 测试

```bash
python3 -m py_compile \
  build_top5000_dualreceptor_4seed_handoff_v1.py \
  test_build_top5000_dualreceptor_4seed_handoff_v1.py

python3 test_build_top5000_dualreceptor_4seed_handoff_v1.py -v
```

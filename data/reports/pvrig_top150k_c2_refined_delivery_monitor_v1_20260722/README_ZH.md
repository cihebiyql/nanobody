# C2 精排 Top7500 本地交付监控

该 delivery-only monitor 不再仅等待打分 terminal，而是等待 Node1 的
C2_REFINED_TOP7500_PUBLICATION_VERIFIED.json。远端 publication verifier 已递归闭合：

- Stage1 与 NBB2 staging receipt；
- 32 个 C2 shard manifest、raw feature、target/hash receipt；
- 36D→32D C2 closure；
- V2.11 adapter/model/code；
- 最终 7500 TSV、FASTA、high-confidence core 与零 truth access。

通过后才以 tar 流复制最终目录到本地 experiments/phase2_5080_v1/prepared/，并再次验证
SHA256SUMS、7500 行、最终 receipt 与 publication receipt。该 monitor 不参与模型打分。

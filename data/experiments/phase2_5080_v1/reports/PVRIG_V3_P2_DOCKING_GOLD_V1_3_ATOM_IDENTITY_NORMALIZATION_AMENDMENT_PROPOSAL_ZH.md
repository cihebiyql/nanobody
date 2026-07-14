# PVRIG V1.3 ATOM identity 差异审计与窄化 normalization 修订提案

## 结论

本次仅执行只读坐标 identity 审计，没有运行 docking、selector、几何评分或训练标签生成。

状态：`PASS_V1_3_ATOM_IDENTITY_TERMINAL_OXT_ONLY_SUPPORTED`

审计覆盖 `68` 个 V1.3 目标 runs、`544` 个 fixed Top-8 poses：

- exact-reuse ledger 64 个旧 Pilot64 runs：512 poses；
- V1.3 新 boundary4：32 poses；
- 总闭包：`64 × 8 + 4 × 8 = 544` poses。

核心结果：

| chain | comparisons | residue exact | raw atom exact | OXT-normalized exact | non-OXT differences |
|---|---:|---:|---:|---:|---:|
| A / VHH | 544 | 544 | 0 | 544 | 0 |
| B / PVRIG | 544 | 544 | 544 | 544 | 0 |

按 docking receptor 和 chain 分层：

| receptor | chain | comparisons | residue exact | raw atom exact | OXT-normalized exact | non-OXT differences |
|---|---|---:|---:|---:|---:|---:|
| 8X6B | A | 272 | 272 | 0 | 272 | 0 |
| 8X6B | B | 272 | 272 | 272 | 272 | 0 |
| 9E6Y | A | 272 | 272 | 0 | 272 | 0 |
| 9E6Y | B | 272 | 272 | 272 | 272 | 0 |

观察到的 raw atom identity 差异仅为 VHH C 端终止残基 `OXT` 在 frozen monomer 中存在、在 HADDOCK pose 中缺失。所有 residue identity 与所有非 `OXT` heavy-ATOM identity 均完全一致；PVRIG chain B 为 raw exact match。

## 建议冻结的最窄规则

建议另行预注册、审查并冻结以下规则，**当前脚本和现有 preregistration 不自动启用**：

```text
只允许链末端最后一个 ATOM residue 上 atom_name == OXT 的存在/缺失差异；
比较 residue identity 时不做任何归一化；
比较 atom identity 时仅移除 terminal OXT 后再比较；
任何非末端 OXT、任何其他 atom、residue、chain、resname、resseq、icode、altloc 或 element 差异均 fail-closed。
```

该规则不允许任意删去氧原子，也不允许忽略 HETATM、残基缺失、侧链缺原子或 chain swap。它仅描述本次数据中观察到的 HADDOCK terminal topology 变化。

## 方法与边界

- identity 输入仅使用 `ATOM` heavy atoms；坐标、serial、occupancy 和 B-factor 不参与 identity。
- residue key：`(resseq, icode, resname)`。
- atom key：`(resseq, icode, resname, atom_name, altloc, element)`。
- 旧 exact-reuse64 与新 boundary4 均从各自冻结 remote root 只读归档，并分别验证 remote/local inventory hash-chain 相等。
- 审计不证明 binding、affinity 或 blocking，也不使 V1.3 training/formal Gold 合格。

## 可复核产物

- Audit：`data/experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_3_atom_identity_difference_audit.json`
- Audit SHA256：`57058e8a0fab81380372b0c4e19967b47cff5d8c5f0d9c411ed3e9acaa2c1545`
- 审计脚本：`data/experiments/phase2_5080_v1/src/audit_phase2_v3_p2_v1_3_atom_identity_differences.py`
- 审计脚本 SHA256：`f2a2c487bb1b9dffe5bb363beaaa8fd862625cc7b2fe088ab6b8167453464f07`
- Exact-reuse64 remote inventory chain：`7944c79dda27401b6e637d6d9611578a3b862b693a8f76e7018f7ff8bc8cf285`
- Boundary4 remote inventory chain：`580590a1d55f6f684ecb732dcd3112250d921a016864f146040ee0334d0a1819`

完整 per-run、per-pose、per-chain 差异记录见 audit JSON。

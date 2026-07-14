# PVRIG V1.3 ATOM/OXT 与 heavy-HETATM identity 证据 addendum

## 结论

本次仅执行只读坐标 identity 审计，没有运行 docking、selector、scoring、几何评分或训练标签生成。

状态：`PASS_V1_3_ATOM_OXT_AND_HETATM_ZERO_EVIDENCE`

审计覆盖 `68` 个 V1.3 目标 runs、`544` 个 fixed Top-8 poses：

- exact-reuse ledger 64 个旧 Pilot64 runs：512 poses；
- V1.3 新 boundary4：32 poses；
- 总闭包：`64 × 8 + 4 × 8 = 544` poses。

重用 v1 ATOM/OXT 结论：

| chain | comparisons | residue exact | raw ATOM exact | OXT-normalized exact | non-OXT differences |
|---|---:|---:|---:|---:|---:|
| A / VHH | 544 | 544 | 0 | 544 | 0 |
| B / PVRIG | 544 | 544 | 544 | 544 | 0 |

heavy `HETATM` 新证据：

| chain | comparisons | ref identity total | pose identity total | ref nonzero | pose nonzero | raw exact | missing | extra |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A / VHH | 544 | 0 | 0 | 0 | 0 | 544 | 0 | 0 |
| B / PVRIG | 544 | 0 | 0 | 0 | 0 | 544 | 0 | 0 |

544 个 pose 及其 chain A/B reference 中 heavy `HETATM` 计数均为 0。因此最窄的可冻结规则是：reference 和 pose 的 chain A/B heavy `HETATM` 计数必须同时为 0，任何注入均 fail-closed。

按 docking receptor 和 chain 分层：

| receptor | chain | comparisons | residue exact | raw ATOM exact | OXT-normalized exact | non-OXT diff | ref HETATM | pose HETATM | HETATM exact | HETATM missing | HETATM extra |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8X6B | A | 272 | 272 | 0 | 272 | 0 | 0 | 0 | 272 | 0 | 0 |
| 8X6B | B | 272 | 272 | 272 | 272 | 0 | 0 | 0 | 272 | 0 | 0 |
| 9E6Y | A | 272 | 272 | 0 | 272 | 0 | 0 | 0 | 272 | 0 | 0 |
| 9E6Y | B | 272 | 272 | 272 | 272 | 0 | 0 | 0 | 272 | 0 | 0 |

观察到的 raw `ATOM` identity 差异仅为 VHH C 端终止残基 `OXT` 在 frozen monomer 中存在、在 HADDOCK pose 中缺失。所有 residue identity 与所有非 `OXT` heavy-`ATOM` identity 均完全一致；PVRIG chain B 为 raw exact match。

## 建议冻结的最窄规则

本 addendum 提供修订证据，**不改写现有 preregistration，也不自动启用 selector**：

```text
只允许链末端最后一个 ATOM residue 上 atom_name == OXT 的存在/缺失差异；
比较 residue identity 时不做任何归一化；
比较 ATOM identity 时仅移除 terminal OXT 后再比较；
OXT normalization 仅作用于 ATOM，绝不作用于 HETATM；
heavy HETATM policy = require_zero_on_reference_and_pose_chains_A_and_B；
任何非末端 OXT、任何其他 ATOM、HETATM、residue、chain、resname、resseq、icode、altloc 或 element 差异均 fail-closed。
```

该规则不允许任意删去氧原子，也不允许忽略 heavy `HETATM`、残基缺失、侧链缺原子或 chain swap。它仅描述本次数据中观察到的 HADDOCK terminal topology 变化及 heavy-`HETATM` zero evidence。

## 方法与边界

- `ATOM` identity 输入使用 chain A/B heavy atoms；坐标、serial、occupancy 和 B-factor 不参与 identity。
- `HETATM` identity 独立使用 chain A/B heavy atoms，不与 `ATOM` 集合合并。
- residue key：`(resseq, icode, resname)`。
- ATOM/HETATM atom key：`(resseq, icode, resname, atom_name, altloc, element)`。
- 旧 exact-reuse64 与新 boundary4 均从各自冻结 remote root 只读归档，并分别验证 remote/local inventory hash-chain 相等。
- 审计不证明 binding、affinity 或 blocking，也不使 V1.3 training/formal Gold/P2 合格。

## 可复核产物

- Audit：`data/experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_3_atom_hetatm_identity_addendum_audit.json`
- Audit SHA256：`5288e2b87612d06ca263914c10463d2abbb387c8d187c7174d62487dafc0f325`
- 审计脚本：`data/experiments/phase2_5080_v1/src/audit_phase2_v3_p2_v1_3_atom_hetatm_identity_addendum.py`
- 审计脚本 SHA256：`becf88f2dad5afa43bbf11b1ea8748036d6ba6447f4cff8efbb7393265479222`
- Exact-reuse64 remote inventory chain：`7944c79dda27401b6e637d6d9611578a3b862b693a8f76e7018f7ff8bc8cf285`
- Boundary4 remote inventory chain：`580590a1d55f6f684ecb732dcd3112250d921a016864f146040ee0334d0a1819`

完整 per-run、per-pose、per-chain 差异记录见 audit JSON。

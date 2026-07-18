# Frozen receptor-specific contact composite

V2.4 contact scalar 不从 outer results 调权，固定为：

```text
contact_score_Rr
= 0.5 * hotspot_contact_mass_Rr
+ 0.5 * interface_specificity_Rr
```

R8 和 R9 使用完全相同的公式与权重。两个输入必须在 `[0,1]` 内，不加截距，不做 clipping。

冻结公式：`contact_score_formula_v1.json`。feature contract 必须通过该文件的 SHA256 绑定 formula receipt。

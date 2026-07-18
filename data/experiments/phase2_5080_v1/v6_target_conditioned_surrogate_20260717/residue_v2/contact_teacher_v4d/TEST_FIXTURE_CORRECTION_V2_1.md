# V4D contact teacher V2 测试夹具修正记录

## 结论

本修正仅改变合成测试 PDB 的 gzip 写法，不改变：

- `extract_v4d_contact_teacher_v2.py`；
- `CONTRACT_V2.json`；
- 真实 V4D 输入；
- 接触定义、Top-8、seed 聚合或任何输出语义。

## 原因

原合成夹具使用 `gzip.open(..., "wt")`，会把当前时间写入 gzip header。若两个测试根目录恰好跨越一秒创建，pose 压缩字节 SHA256 不同，进而使 pose inventory 的字节确定性测试出现假失败。远端生产前测试在同一秒内完成，因此未触发该夹具问题。

修正后合成 pose 使用 `gzip.GzipFile(..., mtime=0)`，确保不同根目录和不同 worker 数下输入字节一致。

## 证据边界

远端 V2 生产产物仍由启动时冻结的 extractor、contract 和真实输入哈希解释；本记录不追溯改变生产版本，也不把测试夹具修正表述为模型或教师标签改进。

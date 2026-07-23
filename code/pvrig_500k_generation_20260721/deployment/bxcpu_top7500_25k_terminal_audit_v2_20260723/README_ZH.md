# Top7500 25k Docking 终态审计 V2

本目录只修复终态审计，不修改、重启或重排任何冻结的 Docking 任务。

V1 仅把 `SUCCESS` 和 `FAILED_MAX_ATTEMPTS` 计为终态，但实际技术失败写成 `FAILED`，会导致所有任务完成后仍误报 `INCOMPLETE`。V2 将：

- `SUCCESS` 计为技术成功；
- `FAILED` / `FAILED_MAX_ATTEMPTS` 计为终态技术 `NA`；
- `MISSING` / `RUNNING` / 损坏 JSON 仍 fail-closed；
- 明确声明该 25k campaign 是旧 priority/S0 Top7500，不是最新 C2 Top7500 的整体前瞻评估。

测试：

```bash
python -m unittest -v test_technical_status_top7500_25k_v2.py
```

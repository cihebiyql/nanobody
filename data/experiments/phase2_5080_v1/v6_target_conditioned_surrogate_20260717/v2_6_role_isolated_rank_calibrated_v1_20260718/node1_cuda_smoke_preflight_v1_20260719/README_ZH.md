# V2.6 Node1 CUDA smoke/deployment 预检 V1

## 状态

```text
PASS_READONLY_PREFLIGHT_BUILT
NONLAUNCHING
REMOTE_STATE_MODIFIED = false
```

本目录只准备 Node1 CUDA/BF16 smoke 的冻结接口、结果验证器和后续授权条件，**没有启动任务、没有复制包到 Node1，也没有触碰正在运行的 V2.5 DAG**。

## 已绑定的实现

| 项目 | SHA256 |
|---|---|
| real1507 integration freeze | `8c6bd627b1f7381c76a97a821f9eafdf3115c1859bc4120890a7239c999e5d76` |
| real1507 trainer | `8625e7f27091f05dae3ef9cbb52a88efa87acc16daad4494c89752f64a947a02` |
| rank V1.1 freeze | `fe276bd1601c77b07440e6f1960d13a75bf81ee7769a30c8bb0229a0ee3d77ac` |
| rank V1.1 core | `b420766a7769a546418a68367b71742eb3ea7872dd2411a48609139a985ef2ec` |
| live V2.5 job graph | `ea1c4c1eedf189d9542e3e73b0c0368777b4073468fd4e39535b28fd7fa24185` |

## 未来 smoke 的固定内容

```text
GPU1: B/E matched CUDA-BF16 20-step trajectory
GPU2: gradient_accumulation=2 closure/replay
GPU4: F shared-gated kappa=0.25 telemetry
GPU5: exact-min and evidence-firewall audit
```

必须证明：

- B/E scalar+shared 参数最大差值 `<=1e-7`；
- 20 optimizer steps、每步 2 个 microbatches，共 40 microbatches；
- F 每步均输出 gradient-cap telemetry，20/20 事件、0 次 budget violation；
- BF16/CUDA 所有 loss、梯度和 optimizer state 有限；
- contact RNG 每步恢复；
- 只直接训练 `R8/R9`，推理 `Rdual=exact_min(R8,R9)`，误差 `<=1e-12`；
- V4-F/test32、score truth、outer metrics、candidate Docking pose 输入访问均为 0。

## 当前 Node1 只读检查

- `/data1` 可用约 `179G`，通过本 smoke 的 `100 GiB` 最低门，但余量偏低；
- `pvrig-v6-tc`：Python 3.11.14、Torch 2.6.0+cu124、CUDA 12.4、BF16 支持；
- GPU 1/2/4/5 均为 RTX 4090，但当前各有一个 V2.5 worker；
- V2.5 快照：107 completed、4 running、190 pending、0 V4-F/test32 access；
- 所以现在不允许启动 V2.6 smoke。

## 后续授权条件

详见 `AUTHORIZATION_CONDITIONS_V1.json`。最关键的四项是：

1. 新建并冻结独立 Node1 CUDA smoke driver；
2. V2.5 301-job DAG 以精确 graph hash 正常 PASS，scheduler/workers 已退出；
3. 启动瞬间重新确认 1/2/4/5 四张卡空闲及 `/data1 >=100 GiB`；
4. 新建独立授权 overlay，绑定 package、integration、rank 和 driver freeze 哈希。

`AUTHORIZATION_TEMPLATE_NONLAUNCHING.json` 永远保持 `execution_authorized=false`，不能原地修改成授权文件。

## 验证

```bash
python3 -m unittest discover \
  -s node1_cuda_smoke_preflight_v1_20260719/tests \
  -p 'test_*.py' -v
```

科学边界：该 smoke 只验证训练动力学和计算几何代理的数值契约，不产生结合、Kd、实验阻断、Docking Gold 或提交真值结论。

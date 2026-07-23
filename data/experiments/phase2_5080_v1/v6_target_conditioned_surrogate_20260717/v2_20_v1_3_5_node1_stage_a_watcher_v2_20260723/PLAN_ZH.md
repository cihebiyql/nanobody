# V2.20 V1.3.5 Node1 Stage-A watcher V2

## 目的

仅执行已独立批准的 Stage-A 技术预检：Node1 上的 148 项测试与五折 shared-calibration materialize/load-only 验证。该 watcher 不包含训练启动器，不创建 optimizer，不调用训练 fold runner，也不授权训练。

## V1 被拒绝的原因

1. V1 在远端 tmux 已创建后若 SSH 断开，可能退出且不能可靠接管既有 session。
2. V1 对 `rc=0` 只下载 receipt 文本，未验证 sidecar、content-addressed copy、receipt schema、148 tests、五折 exact-once 和全部 no-training 字段。

V1 已在任何 Node1 远端动作发生前停止；V2 使用独立的新路径和 tmux 名称。

## V2 状态机

```text
CLEAN
  -> immutable archive upload
ARCHIVE_READY
  -> atomic extraction to unique stage
STAGED_PACKAGE
  -> exact allowlist/hash validation -> atomic stage-to-final rename
READY
  -> exact package/controller validation -> one Stage-A tmux
RUNNING
  -> reconnect/adopt same session; verify exact pane start command; never relaunch
TERMINAL
  -> rc!=0 fail closed
  -> rc==0 remote regular/non-symlink proof
          -> atomic local bundle download
          -> local full receipt validator
          -> PASS waiting separate training review
```

所有类型冲突、final+stage 并存、无 package 却有执行状态、无 rc 的部分 runtime/evidence、成功 rc 却缺 runtime 等状态均 `FAIL_CLOSED_AMBIGUOUS_REMOTE_STATE`。

## 固定远端身份

```text
package:
/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_3_5_technical_recovery_watcher_v2_20260723

runtime:
/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_3_5_preflight_runtime_v2_20260723

evidence:
/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_3_5_stage_a_evidence_v2_20260723

tmux:
v220_v135_stagea_preflight_v2
```

## 成功门

- frozen package SHA256 `07c846...0804` 且 20-file allowlist 完全闭合；
- independent Stage-A-only approval SHA256 `91fc04...97c8`；
- preregistration SHA256 `574919...9562`；
- remote receipt、sidecar、content copy 均 regular、non-symlink、稳定且字节一致；
- local validator 证明 102 legacy + 46 V1.3.5 = 148 tests；
- 五折各恰好一次 calibrator、C0/C1 同字节；
- optimizer/backward/training/run_fold_core/training output 全部为 false/zero。

成功状态只允许：

```text
PASS_VALIDATED_NODE1_STAGE_A_WAITING_INDEPENDENT_TRAINING_REVIEW
```

训练仍需单独的独立 Stage-B/training authorization，V2 watcher 本身不能跨越该门。

# Top150K M2 / Graph 恢复 V1

本目录只修复两个运行环境/路径级启动故障，不修改任何冻结模型、评分权重、候选顺序或输入数据：

1. M2 原 launcher 错用系统 `python3`，缺少 NumPy；恢复脚本改用冻结的 `pvrig-v6-tc` Python。
2. 图构建器的 label-free 路径防火墙拒绝项目祖先目录中的 `fixed_pose` 字符串；恢复脚本在同一文件系统建立 150,000 条逐行 inode 校验的硬链接镜像，再从不含 `pose/dock/complex` 的路径构图。

恢复成功后仍发布原有 canonical terminal 文件，使既有四模型与 C2 watcher 自动继续。所有流程保持零 teacher/Docking truth 输入。

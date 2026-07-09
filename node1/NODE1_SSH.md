# node1 稳定 SSH 连接说明

更新时间：2026-07-06
当前本地目录：`/mnt/d/work/抗体/node1`

## 目标

从 Windows OpenSSH 稳定免密连接集群 `node1`，供后续 AI/脚本直接在节点上执行只读检查或训练相关操作。

## 已修复的问题

原 Windows SSH 配置中：

- `qlyu-node1` 通过 `qlyu-admin` 跳板访问内网主机 `node1`。
- `qlyu-admin` 写死了旧的校园网源地址：`BindAddress 10.101.253.55`。
- 当前 Windows WLAN 地址已变为 `10.101.149.77`，因此旧配置会报：`bind 10.101.253.55: Unknown error`。

## 当前稳定方案

已备份并更新 Windows SSH 配置：

- 配置文件：`C:\Users\ciheb\.ssh\config`
- 备份文件：`C:\Users\ciheb\.ssh\config.backup-node1-stable-20260706-223843`
- 动态代理脚本：`C:\Users\ciheb\.ssh\qlyu-node1-proxy.cmd`

关键变化：

- `Host qlyu-node1 node1`：现在 `ssh.exe node1` 和 `ssh.exe qlyu-node1` 都指向同一连接。
- `ProxyCommand C:/Users/ciheb/.ssh/qlyu-node1-proxy.cmd %h %p`：每次连接时自动读取 Windows `WLAN` 接口上的 `10.101.x.x` 地址，并用它绑定到跳板。
- 这样后续校园网 IP 变化时，不需要手动改 `BindAddress`，只要 Windows 仍连接在能访问 `172.21.43.18:322` 的校园网/VPN 上即可。

## 常用命令

在 WSL/Codex 里：

```bash
ssh.exe node1 'hostname && whoami && date -Is'
ssh.exe node1 'nvidia-smi'
ssh.exe node1
```

在 Windows PowerShell/CMD 里：

```powershell
ssh node1 "hostname && whoami && date -Is"
ssh node1 "nvidia-smi"
ssh node1
```

## 验证结果

配置更新后已验证：

```text
ssh.exe node1       -> stable_node1_ok host=node1 user=qlyu
ssh.exe qlyu-node1  -> stable_qlyu_node1_ok host=node1 user=qlyu
```

## 排障

如果后续连接失败：

1. 确认 Windows 已连接校园网/VPN，且能看到 `10.101.x.x` 的 WLAN 地址：

   ```powershell
   Get-NetIPAddress -InterfaceAlias WLAN -AddressFamily IPv4
   ```

2. 确认跳板端口可达：

   ```powershell
   Test-NetConnection 172.21.43.18 -Port 322
   ```

3. 查看最终 SSH 解析：

   ```bash
   ssh.exe -G node1 | findstr /i "hostname user proxycommand identityfile"
   ```

4. 如果需要恢复旧配置，用备份覆盖：

   ```bash
   cp /mnt/c/Users/ciheb/.ssh/config.backup-node1-stable-20260706-223843 /mnt/c/Users/ciheb/.ssh/config
   ```

## 后续 AI 使用约定

后续需要在 `node1` 上执行命令时，默认使用：

```bash
ssh.exe node1 '<remote command>'
```

除非明确需要进入跳板本身，不再直接使用 `qlyu-admin`。

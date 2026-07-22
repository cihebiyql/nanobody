#!/usr/bin/env bash
set -euo pipefail

# Bridge WSL rsync/scp to the Windows OpenSSH configuration that contains the
# campus-network-aware ProxyCommand for node1.
exec /mnt/c/Windows/System32/OpenSSH/ssh.exe \
  -F C:/Users/ciheb/.ssh/config \
  -o BatchMode=yes \
  -o ConnectTimeout=20 \
  "$@"

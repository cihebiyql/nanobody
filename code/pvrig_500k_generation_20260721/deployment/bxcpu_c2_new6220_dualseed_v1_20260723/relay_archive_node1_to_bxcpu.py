#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import math
import os
import pathlib
import subprocess
import time


NODE1_SSH = "/mnt/c/Windows/System32/OpenSSH/ssh.exe"
REMOTE = (
    "/data1/qlyu/projects/pvrig_top7500_c2_gap_recovery_v1_20260723/"
    "archives/pvrig_c2_new6220_dualreceptor_2seed_handoffs_v2_20260723.tar.gz"
)
NAME = pathlib.Path(REMOTE).name
LOCAL_ROOT = pathlib.Path(
    "/mnt/d/work/抗体/node1/pvrig_c2_new6220_bxcpu_stage_20260723"
)
LOCAL = LOCAL_ROOT / NAME
CHUNKS = LOCAL_ROOT / "chunks_8m"
CHUNK_SIZE = 8 * 1024 * 1024
BXCPU_REMOTE = f"/publicfs04/fs04-al/home/als001821/{NAME}"


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def node1(command: str, *, stdout=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            NODE1_SSH,
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=30",
            "node1",
            command,
        ],
        stdout=stdout,
        stderr=subprocess.PIPE,
        check=False,
    )


def remote_anchor() -> tuple[int, str]:
    command = f"stat -c '%s' '{REMOTE}'; sha256sum '{REMOTE}'"
    for _ in range(10):
        result = node1(command, stdout=subprocess.PIPE)
        if result.returncode == 0:
            lines = result.stdout.decode().splitlines()
            return int(lines[0]), lines[1].split()[0]
        time.sleep(3)
    raise RuntimeError("unable to read Node1 archive anchor")


def fetch_chunks(size: int) -> None:
    CHUNKS.mkdir(parents=True, exist_ok=True)
    count = math.ceil(size / CHUNK_SIZE)
    for index in range(count):
        expected = min(CHUNK_SIZE, size - index * CHUNK_SIZE)
        final = CHUNKS / f"chunk_{index:04d}.bin"
        if final.is_file() and final.stat().st_size == expected:
            continue
        for attempt in range(1, 11):
            partial = CHUNKS / f"chunk_{index:04d}.attempt_{attempt}.partial"
            with partial.open("wb") as handle:
                result = node1(
                    f"dd if='{REMOTE}' bs={CHUNK_SIZE} skip={index} count=1 status=none",
                    stdout=handle,
                )
            if result.returncode == 0 and partial.stat().st_size == expected:
                os.replace(partial, final)
                break
            time.sleep(2)
        else:
            raise RuntimeError(f"chunk {index} failed after retries")
        print(f"chunk {index + 1}/{count} ready", flush=True)


def assemble(size: int, expected_sha: str) -> None:
    partial = LOCAL.with_suffix(LOCAL.suffix + ".assembling")
    with partial.open("wb") as output:
        for chunk in sorted(CHUNKS.glob("chunk_*.bin")):
            with chunk.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    output.write(block)
    assert partial.stat().st_size == size
    actual = sha256(partial)
    assert actual == expected_sha, (actual, expected_sha)
    os.replace(partial, LOCAL)
    (LOCAL_ROOT / f"{NAME}.sha256").write_text(f"{expected_sha}  {NAME}\n")


def upload(expected_sha: str) -> None:
    subprocess.run(
        [
            "rsync",
            "-a",
            "--partial",
            "--append-verify",
            "--timeout=600",
            str(LOCAL),
            f"bxcpu:{BXCPU_REMOTE}",
        ],
        check=True,
    )
    subprocess.run(
        [
            "rsync",
            "-a",
            "--timeout=600",
            str(LOCAL_ROOT / f"{NAME}.sha256"),
            f"bxcpu:{BXCPU_REMOTE}.sha256",
        ],
        check=True,
    )
    result = subprocess.run(
        [
            "ssh",
            "bxcpu",
            (
                f"test \"$(stat -c %s '{BXCPU_REMOTE}')\" = '{LOCAL.stat().st_size}' "
                f"&& test \"$(sha256sum '{BXCPU_REMOTE}' | cut -d' ' -f1)\" "
                f"= '{expected_sha}'"
            ),
        ],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    print(f"bxcpu verified size={LOCAL.stat().st_size} sha256={expected_sha}")
    assert expected_sha in (LOCAL_ROOT / f"{NAME}.sha256").read_text()


def main() -> None:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    size, expected_sha = remote_anchor()
    print(f"remote size={size} sha256={expected_sha}", flush=True)
    if not (LOCAL.is_file() and LOCAL.stat().st_size == size and sha256(LOCAL) == expected_sha):
        fetch_chunks(size)
        assemble(size, expected_sha)
    upload(expected_sha)


if __name__ == "__main__":
    main()

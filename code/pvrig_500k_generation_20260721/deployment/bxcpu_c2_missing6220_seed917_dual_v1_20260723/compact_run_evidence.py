#!/usr/bin/env python3
"""Create a compact, auditable HADDOCK evidence archive for one successful job."""
from __future__ import annotations
import argparse, hashlib, io, json, os, pathlib, shutil, tarfile, time


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def required_members(root: pathlib.Path, job_id: str) -> tuple[dict, list[str]]:
    result_path = root / "results" / job_id / "job_result.json"
    result = json.loads(result_path.read_text())
    if result.get("state") != "SUCCESS" or result.get("job_id") != job_id:
        raise RuntimeError("job_result is not a matching SUCCESS")
    selected = [str(value) for value in result.get("selected_models", [])]
    if not selected:
        raise RuntimeError("SUCCESS result has no selected models")
    prefix = f"runs/{job_id}"
    members = [
        f"{prefix}/job.json",
        f"{prefix}/haddock3.cfg",
        f"{prefix}/data/air.tbl",
        f"{prefix}/haddock.stdout.log",
        f"{prefix}/haddock.stderr.log",
        f"{prefix}/SCRATCH_PROVENANCE.json",
        f"{prefix}/haddock_run/6_seletopclusts/io.json",
        *selected,
    ]
    return result, sorted(set(members))


def add_manifest(tar: tarfile.TarFile, job_id: str, result: dict, files: dict[str, str]) -> None:
    payload = {
        "schema_version": "pvrig_compact_haddock_evidence_v1",
        "job_id": job_id,
        "job_hash": result.get("job_hash"),
        "protocol_core_sha256": result.get("protocol_core_sha256"),
        "selected_model_count": result.get("selected_model_count"),
        "files_sha256": files,
        "created_epoch": time.time(),
        "claim_boundary": "Selected Docking pose evidence only; not affinity or experimental blocking.",
    }
    data=(json.dumps(payload,indent=2,sort_keys=True)+"\n").encode()
    info=tarfile.TarInfo(f"runs/{job_id}/COMPACT_EVIDENCE.json")
    info.size=len(data); info.mtime=int(time.time()); info.mode=0o640
    tar.addfile(info,io.BytesIO(data))


def add_bytes(tar: tarfile.TarFile, relative: str, data: bytes, mode: int = 0o640) -> None:
    info = tarfile.TarInfo(relative)
    info.size = len(data)
    info.mtime = int(time.time())
    info.mode = mode
    tar.addfile(info, io.BytesIO(data))


def add_full_result(tar: tarfile.TarFile, root: pathlib.Path, job_id: str, hashes: dict[str, str]) -> None:
    """Store the full scoring result once, compressed inside the evidence archive.

    job_result.json already embeds the complete per-pose score dictionaries, so
    the separate pose_scores/*.json files would be a second redundant copy.
    """
    relative = f"results/{job_id}/job_result.json"
    path = root / relative
    data = path.read_bytes()
    hashes[relative] = sha256_bytes(data)
    info = tar.gettarinfo(str(path), arcname=relative)
    with path.open("rb") as handle:
        tar.addfile(info, handle)


def minimize_published_result(output: pathlib.Path, job_id: str, result: dict) -> None:
    """Replace the shared-filesystem result copy with a tiny resume stub.

    The worker writes the terminal status only after this function returns, so
    the relay can never observe a SUCCESS marker before the full result is safe
    inside the validated archive.
    """
    if output.parent.name != "compressed_queue":
        return
    publish_root = output.parent.parent
    result_dir = publish_root / "results" / job_id
    result_path = result_dir / "job_result.json"
    if not result_path.is_file():
        return
    stub = {
        "state": "SUCCESS",
        "job_id": job_id,
        "job_hash": result.get("job_hash"),
        "protocol_core_sha256": result.get("protocol_core_sha256"),
        "selected_model_count": result.get("selected_model_count"),
        "selected_models": result.get("selected_models", []),
        "full_result_in_compact_archive": True,
        "offloaded_to_node1": False,
    }
    tmp_dir = result_dir.with_name(f".{job_id}.compact-result.{os.getpid()}")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    (tmp_dir / "job_result.json").write_text(json.dumps(stub, sort_keys=True) + "\n")
    old_dir = result_dir.with_name(f".{job_id}.full-result.{os.getpid()}")
    os.replace(result_dir, old_dir)
    os.replace(tmp_dir, result_dir)
    shutil.rmtree(old_dir)


def compact_directory(root: pathlib.Path, job_id: str, output: pathlib.Path) -> None:
    result, members = required_members(root, job_id)
    hashes={}
    with tarfile.open(output,"w:gz",compresslevel=3) as dst:
        add_full_result(dst, root, job_id, hashes)
        for relative in members:
            path=root/relative
            if not path.is_file():
                if relative.endswith(("SCRATCH_PROVENANCE.json","io.json","haddock.stdout.log","haddock.stderr.log")):
                    continue
                raise FileNotFoundError(path)
            data=path.read_bytes(); hashes[relative]=sha256_bytes(data)
            info=dst.gettarinfo(str(path),arcname=relative)
            with path.open("rb") as handle: dst.addfile(info,handle)
        add_manifest(dst,job_id,result,hashes)


def compact_existing(root: pathlib.Path, job_id: str, source: pathlib.Path, output: pathlib.Path) -> None:
    result, members = required_members(root, job_id)
    wanted=set(members); hashes={}; found=set()
    with tarfile.open(source,"r:gz") as src, tarfile.open(output,"w:gz",compresslevel=3) as dst:
        add_full_result(dst, root, job_id, hashes)
        for member in src:
            if member.name not in wanted or not member.isfile(): continue
            handle=src.extractfile(member)
            if handle is None: continue
            data=handle.read(); hashes[member.name]=sha256_bytes(data); found.add(member.name)
            member.size=len(data); dst.addfile(member,io.BytesIO(data))
        required={m for m in wanted if not m.endswith(("SCRATCH_PROVENANCE.json","io.json","haddock.stdout.log","haddock.stderr.log"))}
        missing=required-found
        if missing: raise RuntimeError(f"source archive missing required evidence: {sorted(missing)}")
        add_manifest(dst,job_id,result,hashes)


def validate(path: pathlib.Path, job_id: str) -> None:
    with tarfile.open(path,"r:gz") as tar:
        names=set(tar.getnames())
        if f"runs/{job_id}/COMPACT_EVIDENCE.json" not in names:
            raise RuntimeError("compact manifest missing")
        if f"results/{job_id}/job_result.json" not in names:
            raise RuntimeError("full job result missing")
        if not any("/6_seletopclusts/" in name and name.endswith((".pdb",".pdb.gz")) for name in names):
            raise RuntimeError("selected PDB evidence missing")


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--project-root",type=pathlib.Path,required=True)
    p.add_argument("--job-id",required=True)
    p.add_argument("--output",type=pathlib.Path,required=True)
    p.add_argument("--source-archive",type=pathlib.Path)
    a=p.parse_args(); a.output.parent.mkdir(parents=True,exist_ok=True)
    if a.source_archive: compact_existing(a.project_root,a.job_id,a.source_archive,a.output)
    else: compact_directory(a.project_root,a.job_id,a.output)
    validate(a.output,a.job_id)
    minimize_published_result(a.output, a.job_id, json.loads((a.project_root / "results" / a.job_id / "job_result.json").read_text()))
    print(json.dumps({"status":"PASS","job_id":a.job_id,"bytes":a.output.stat().st_size},sort_keys=True))
    return 0


if __name__=="__main__": raise SystemExit(main())

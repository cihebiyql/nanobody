#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from build_top5000_unstarted_seed42_3047_two_node_handoff_v1 import (
    ACTIVE_SEEDS,
    CONFORMATIONS,
    EXPECTED_CANDIDATES_PER_NODE,
    EXPECTED_JOBS_PER_NODE,
    EXPECTED_SELECTED_CANDIDATES,
    EXPECTED_SELECTED_JOBS,
    EXPECTED_SOURCE_CANDIDATES,
    EXPECTED_SOURCE_SHARDS,
    PACKAGE_VERSION,
    SELECTED_PER_SOURCE_SHARD,
    SOURCE_SEEDS,
    build_handoff,
    sha256_file,
)


CREATED_AT = "2026-07-24T12:00:00+08:00"
CANDIDATE_FIELDS = [
    "release_rank",
    "candidate_id",
    "monomer_source",
    "monomer_sha256",
    "synthetic_note",
]
JOB_FIELDS = [
    "job_id",
    "job_hash",
    "entity_id",
    "seed",
    "conformation",
    "monomer_source",
    "priority",
    "candidate_priority_rank",
    "receptor_pdb",
    "cfg_hash",
    "job_hash_basis",
]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_sha256sums(root: Path) -> None:
    paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    (root / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(root).as_posix()}\n"
            for path in paths
        ),
        encoding="utf-8",
    )


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def verify_sha256sums(root: Path) -> None:
    entries: dict[str, str] = {}
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        entries[relative] = digest
        if sha256_file(root / relative) != digest:
            raise AssertionError(f"SHA256SUMS mismatch: {relative}")
    expected = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if set(entries) != expected:
        raise AssertionError("SHA256SUMS is not exact package file closure")


def synthetic_job_id(candidate_id: str, seed: str, conformation: str) -> str:
    return f"J_{candidate_id}_{seed}_{conformation}"


def create_exact_source_package(root: Path) -> dict[str, object]:
    candidate_rows: list[dict[str, str]] = []
    job_rows: list[dict[str, str]] = []
    shard_rows: dict[int, list[dict[str, str]]] = defaultdict(list)
    source_jobs_by_id: dict[str, dict[str, str]] = {}
    first_candidate_by_shard: dict[int, str] = {}
    monomer_payload = b"ATOM      1  CA  GLY L   1       0.000   0.000   0.000\nEND\n"
    monomer_sha256 = sha256_bytes(monomer_payload)

    for index in range(EXPECTED_SOURCE_CANDIDATES):
        candidate_id = f"C{index:05d}"
        shard_index = index % EXPECTED_SOURCE_SHARDS
        first_candidate_by_shard.setdefault(shard_index, candidate_id)
        monomer_relative = f"inputs/candidate_monomers/{candidate_id}.pdb"
        monomer_path = root / monomer_relative
        monomer_path.parent.mkdir(parents=True, exist_ok=True)
        monomer_path.write_bytes(monomer_payload)
        candidate_rows.append(
            {
                "release_rank": str(index + 1),
                "candidate_id": candidate_id,
                "monomer_source": monomer_relative,
                "monomer_sha256": monomer_sha256,
                "synthetic_note": f"source-row-{index}",
            }
        )
        for seed in ("917", "1931", "42", "3047"):
            for conformation in ("8x6b", "9e6y"):
                job_id = synthetic_job_id(candidate_id, seed, conformation)
                job_hash_basis = (
                    f"{candidate_id}|{seed}|{conformation}|{monomer_sha256}"
                )
                row = {
                    "job_id": job_id,
                    "job_hash": sha256_bytes(job_hash_basis.encode("utf-8")),
                    "entity_id": candidate_id,
                    "seed": seed,
                    "conformation": conformation,
                    "monomer_source": monomer_relative,
                    "priority": str(index * 8 + len(job_rows) % 8 + 1),
                    "candidate_priority_rank": str(index + 1),
                    "receptor_pdb": (
                        f"inputs/normalized/{conformation}_pvrig_receptor.pdb"
                    ),
                    "cfg_hash": sha256_bytes(
                        f"cfg|{seed}|{conformation}".encode("utf-8")
                    ),
                    "job_hash_basis": job_hash_basis,
                }
                job_rows.append(row)
                shard_rows[shard_index].append(row)
                source_jobs_by_id[job_id] = row

    write_tsv(root / "inputs/top5000_candidates.tsv", CANDIDATE_FIELDS, candidate_rows)
    write_tsv(root / "manifests/docking_jobs.tsv", JOB_FIELDS, job_rows)
    for shard_index in range(EXPECTED_SOURCE_SHARDS):
        write_tsv(
            root
            / "manifests/shards_exact_8"
            / f"shard_{shard_index:02d}.tsv",
            JOB_FIELDS,
            shard_rows[shard_index],
        )

    protocol_lock = {
        "schema_version": "synthetic.protocol.lock.v1",
        "status": "CORE_LOCKED",
        "protocol_core_sha256": sha256_bytes(b"synthetic protocol"),
    }
    write_json(root / "PROTOCOL_CORE_LOCK.json", protocol_lock)
    cfg_hashes = {
        seed: {
            conformation: sha256_bytes(
                f"cfg|{seed}|{conformation}".encode("utf-8")
            )
            for conformation in ("8x6b", "9e6y")
        }
        for seed in ("917", "1931", "42", "3047")
    }
    cfg_payloads = {
        seed: {
            conformation: {
                "seed": int(seed),
                "conformation": conformation,
                "ncores": 4,
            }
            for conformation in ("8x6b", "9e6y")
        }
        for seed in ("917", "1931", "42", "3047")
    }
    write_json(
        root / "config/FOUR_SEED_CFG_LOCK.json",
        {
            "schema_version": "pvrig.four_seed_cfg_lock.v1",
            "status": "LOCKED",
            "protocol_core_sha256": protocol_lock["protocol_core_sha256"],
            "seeds": [917, 1931, 42, 3047],
            "conformations": ["8x6b", "9e6y"],
            "cfg_hashes": cfg_hashes,
            "cfg_payloads": cfg_payloads,
        },
    )
    write_json(root / "config/protocol_spec.json", {"ncores": 4, "sampling": 40})
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts/run_job.py").write_text(
        "#!/usr/bin/env python3\nprint('synthetic')\n", encoding="utf-8"
    )
    (root / "scripts/common.py").write_text(
        "SYNTHETIC = True\n", encoding="utf-8"
    )
    for conformation in ("8x6b", "9e6y"):
        receptor = root / f"inputs/normalized/{conformation}_pvrig_receptor.pdb"
        receptor.parent.mkdir(parents=True, exist_ok=True)
        receptor.write_text(f"RECEPTOR {conformation}\n", encoding="utf-8")
    (root / "inputs/source").mkdir(parents=True, exist_ok=True)
    (root / "inputs/source/source_note.txt").write_text(
        "synthetic portable source\n", encoding="utf-8"
    )

    receipt = {
        "schema_version": "pvrig.top5000.dualreceptor_4seed.handoff.v1",
        "package_version": "synthetic_top5000_dualreceptor_4seed_source_v1",
        "status": "READY_FOR_EXTERNAL_DOCKING_SUBMISSION",
        "production": True,
        "docking_started": False,
    }
    write_json(root / "HANDOFF_RECEIPT.json", receipt)
    ready = {
        "schema_version": "pvrig.handoff.ready.v1",
        "status": "READY_FOR_EXTERNAL_DOCKING_SUBMISSION",
        "production": True,
        "docking_started": False,
        "candidates": EXPECTED_SOURCE_CANDIDATES,
        "jobs": len(job_rows),
        "shards": EXPECTED_SOURCE_SHARDS,
        "handoff_receipt_sha256": sha256_file(root / "HANDOFF_RECEIPT.json"),
        "job_manifest_sha256": sha256_file(root / "manifests/docking_jobs.tsv"),
    }
    write_json(root / "READY.json", ready)
    write_sha256sums(root)
    return {
        "candidate_rows": candidate_rows,
        "job_rows": job_rows,
        "source_jobs_by_id": source_jobs_by_id,
        "first_candidate_by_shard": first_candidate_by_shard,
    }


class UnstartedTwoNodeHandoffBuilderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source_root = cls.root / "source"
        cls.source_root.mkdir()
        cls.source = create_exact_source_package(cls.source_root)
        cls.unstarted_path = cls.root / "UNSTARTED_CANDIDATES.tsv"
        write_tsv(
            cls.unstarted_path,
            ["candidate_id"],
            [
                {"candidate_id": row["candidate_id"]}
                for row in cls.source["candidate_rows"]
            ],
        )
        cls.started_path = cls.root / "STARTED_JOB_IDS.json"
        cls.started_job_ids = {
            synthetic_job_id(candidate_id, "917", "8x6b")
            for candidate_id in cls.source["first_candidate_by_shard"].values()
        }
        write_json(
            cls.started_path,
            {"started_job_ids": sorted(cls.started_job_ids)},
        )
        cls.builder_path = Path(__file__).with_name(
            "build_top5000_unstarted_seed42_3047_two_node_handoff_v1.py"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def run_cli(self, output_root: Path) -> dict:
        command = [
            sys.executable,
            str(self.builder_path),
            "--source-package-root",
            str(self.source_root),
            "--unstarted-candidates",
            str(self.unstarted_path),
            "--started-job-ids",
            str(self.started_path),
            "--output-root",
            str(output_root),
            "--created-at",
            CREATED_AT,
            "--expected-source-ready-sha256",
            sha256_file(self.source_root / "READY.json"),
            "--expected-unstarted-sha256",
            sha256_file(self.unstarted_path),
            "--expected-started-sha256",
            sha256_file(self.started_path),
        ]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_cli_builds_exact_reproducible_hash_closed_handoff(self) -> None:
        output_a = self.root / "handoff_a"
        output_b = self.root / "handoff_b"
        source_before = tree_hashes(self.source_root)

        cli_result = self.run_cli(output_a)
        second_result = self.run_cli(output_b)

        self.assertEqual(cli_result, second_result | {"output_root": str(output_a)})
        self.assertEqual(cli_result["package_version"], PACKAGE_VERSION)
        self.assertEqual(cli_result["selected_candidates"], 2_000)
        self.assertEqual(cli_result["selected_jobs"], 8_000)
        self.assertEqual(cli_result["started_job_overlap"], 0)
        self.assertEqual(source_before, tree_hashes(self.source_root))
        self.assertEqual(tree_hashes(output_a), tree_hashes(output_b))
        verify_sha256sums(output_a)

        required = {
            "READY.json",
            "HANDOFF_RECEIPT.json",
            "DOCKING_PLAN.json",
            "SHA256SUMS",
            "README.md",
            "PROTOCOL_CORE_LOCK.json",
            "config/TWO_SEED_CFG_LOCK.json",
            "selection/SELECTED_CANDIDATES.tsv",
            "selection/EXCLUDED_CANDIDATES.tsv",
            "selection/SOURCE_SHARD_SELECTION_SUMMARY.tsv",
            "selection/STARTED_JOB_OVERLAP.tsv",
            "manifests/docking_jobs.tsv",
            "manifests/nodes_exact_2/node_00.tsv",
            "manifests/nodes_exact_2/node_01.tsv",
            "manifests/nodes_exact_2/NODE_RECEIPT.json",
        }
        output_files = {
            path.relative_to(output_a).as_posix()
            for path in output_a.rglob("*")
            if path.is_file()
        }
        self.assertTrue(required.issubset(output_files))

        selected_rows = read_tsv(output_a / "selection/SELECTED_CANDIDATES.tsv")
        excluded_rows = read_tsv(output_a / "selection/EXCLUDED_CANDIDATES.tsv")
        summary_rows = read_tsv(
            output_a / "selection/SOURCE_SHARD_SELECTION_SUMMARY.tsv"
        )
        self.assertEqual(len(selected_rows), EXPECTED_SELECTED_CANDIDATES)
        self.assertEqual(
            len(excluded_rows),
            EXPECTED_SOURCE_CANDIDATES - EXPECTED_SELECTED_CANDIDATES,
        )
        self.assertEqual(len(summary_rows), EXPECTED_SOURCE_SHARDS)
        self.assertEqual(
            Counter(row["source_shard"] for row in selected_rows),
            Counter({str(index): SELECTED_PER_SOURCE_SHARD for index in range(8)}),
        )
        self.assertEqual(
            {row["selected_candidates"] for row in summary_rows}, {"250"}
        )
        self.assertEqual(
            {row["node_index"] for row in selected_rows[:1000]}, {"0"}
        )
        self.assertEqual(
            {row["node_index"] for row in selected_rows[1000:]}, {"1"}
        )

        candidates_by_id = {
            row["candidate_id"]: row for row in self.source["candidate_rows"]
        }
        for shard_index in range(8):
            expected_eligible = sorted(
                (
                    row
                    for row in self.source["candidate_rows"]
                    if (int(row["release_rank"]) - 1) % 8 == shard_index
                    and row["candidate_id"]
                    != self.source["first_candidate_by_shard"][shard_index]
                ),
                key=lambda row: (
                    int(row["release_rank"]),
                    row["candidate_id"],
                ),
            )[:SELECTED_PER_SOURCE_SHARD]
            observed_ids = [
                row["candidate_id"]
                for row in selected_rows
                if int(row["source_shard"]) == shard_index
            ]
            self.assertEqual(
                observed_ids,
                [row["candidate_id"] for row in expected_eligible],
            )
            self.assertEqual(
                [int(candidates_by_id[value]["release_rank"]) for value in observed_ids],
                sorted(
                    int(candidates_by_id[value]["release_rank"])
                    for value in observed_ids
                ),
            )

        output_jobs = read_tsv(output_a / "manifests/docking_jobs.tsv")
        self.assertEqual(len(output_jobs), EXPECTED_SELECTED_JOBS)
        self.assertEqual({row["seed"] for row in output_jobs}, ACTIVE_SEEDS)
        self.assertEqual(
            {row["conformation"] for row in output_jobs}, CONFORMATIONS
        )
        self.assertFalse(
            {row["job_id"] for row in output_jobs}.intersection(
                self.started_job_ids
            )
        )
        source_jobs_by_id = self.source["source_jobs_by_id"]
        for row in output_jobs:
            self.assertEqual(row, source_jobs_by_id[row["job_id"]])

        selected_candidate_ids = {row["candidate_id"] for row in selected_rows}
        output_candidates = read_tsv(output_a / "inputs/selected_candidates.tsv")
        self.assertEqual(
            {row["candidate_id"] for row in output_candidates},
            selected_candidate_ids,
        )
        monomers = list((output_a / "inputs/candidate_monomers").glob("*.pdb"))
        self.assertEqual(len(monomers), EXPECTED_SELECTED_CANDIDATES)
        for row in output_candidates:
            self.assertEqual(
                sha256_file(output_a / row["monomer_source"]),
                row["monomer_sha256"],
            )

        for node_index in range(2):
            node_jobs = read_tsv(
                output_a
                / "manifests/nodes_exact_2"
                / f"node_{node_index:02d}.tsv"
            )
            self.assertEqual(len(node_jobs), EXPECTED_JOBS_PER_NODE)
            self.assertEqual(
                len({row["entity_id"] for row in node_jobs}),
                EXPECTED_CANDIDATES_PER_NODE,
            )
            expected_source_shards = (
                {0, 1, 2, 3} if node_index == 0 else {4, 5, 6, 7}
            )
            candidate_shards = {
                (int(row["candidate_priority_rank"]) - 1) % 8
                for row in node_jobs
            }
            self.assertEqual(candidate_shards, expected_source_shards)

        overlap_rows = read_tsv(
            output_a / "selection/STARTED_JOB_OVERLAP.tsv"
        )
        self.assertEqual(overlap_rows, [])
        ready = json.loads((output_a / "READY.json").read_text(encoding="utf-8"))
        receipt = json.loads(
            (output_a / "HANDOFF_RECEIPT.json").read_text(encoding="utf-8")
        )
        plan = json.loads(
            (output_a / "DOCKING_PLAN.json").read_text(encoding="utf-8")
        )
        self.assertEqual(ready["started_job_overlap"], 0)
        self.assertEqual(receipt["counts"]["started_job_overlap"], 0)
        self.assertEqual(plan["started_job_overlap"], 0)
        self.assertEqual(
            ready["handoff_receipt_sha256"],
            sha256_file(output_a / "HANDOFF_RECEIPT.json"),
        )
        self.assertEqual(
            ready["job_manifest_sha256"],
            sha256_file(output_a / "manifests/docking_jobs.tsv"),
        )
        two_seed_lock = json.loads(
            (output_a / "config/TWO_SEED_CFG_LOCK.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(two_seed_lock["seeds"], [42, 3047])
        self.assertEqual(set(two_seed_lock["cfg_hashes"]), ACTIVE_SEEDS)
        self.assertEqual(
            sha256_file(output_a / "scripts/run_job.py"),
            sha256_file(self.source_root / "scripts/run_job.py"),
        )

    def test_rejects_source_shard_with_fewer_than_250_fully_unstarted(self) -> None:
        insufficient_path = self.root / "UNSTARTED_CANDIDATES_INSUFFICIENT.txt"
        shard_zero_eligible = [
            row["candidate_id"]
            for row in self.source["candidate_rows"]
            if (int(row["release_rank"]) - 1) % 8 == 0
            and row["candidate_id"]
            != self.source["first_candidate_by_shard"][0]
        ][:249]
        all_other_shards = [
            row["candidate_id"]
            for row in self.source["candidate_rows"]
            if (int(row["release_rank"]) - 1) % 8 != 0
        ]
        insufficient_path.write_text(
            "".join(
                f"{candidate_id}\n"
                for candidate_id in shard_zero_eligible + all_other_shards
            ),
            encoding="utf-8",
        )
        output_root = self.root / "must_not_exist"
        with self.assertRaisesRegex(
            ValueError,
            "source shard 0 has only 249 fully unstarted candidates",
        ):
            build_handoff(
                self.source_root,
                insufficient_path,
                self.started_path,
                output_root,
                CREATED_AT,
            )
        self.assertFalse(output_root.exists())


if __name__ == "__main__":
    unittest.main()

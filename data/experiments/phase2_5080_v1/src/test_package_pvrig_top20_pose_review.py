#!/usr/bin/env python3
from __future__ import annotations

import csv
import copy
import gzip
import hashlib
import importlib.util
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
MODULE_PATH = Path(__file__).with_name("package_pvrig_top20_pose_review.py")
REAL_SCHEMA_FIXTURE = (
    Path(__file__).with_name("test_fixtures")
    / "pvrig_v4d_real_job_schema_v1.json"
)
REAL_SCHEMA_FIXTURE_SHA256 = (
    "8bf2a5e195a13e6e3877f3e13bdf60360d091f675c229ea69834bc87bfed6888"
)
SPEC = importlib.util.spec_from_file_location(
    "package_pvrig_top20_pose_review", MODULE_PATH
)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def geometry(reference_id: str, offset: int) -> dict[str, object]:
    return {
        "reference_id": reference_id,
        "hotspot_overlap": {
            "full": {"count": 14 + offset, "residues": ["ignored-large-field"]},
            "anchor": {"count": 8 + offset},
            "holdout": {"count": 6 + offset},
        },
        "vhh_pvrl2_occlusion": {
            "residue_pair_count": 500 + offset,
            "by_vhh_region_pair_count": {"cdr3": 100 + offset},
            "cdr3_fraction": 0.15 + offset / 1000,
            "residue_pairs": [["ignored", "large", "list"]],
        },
        "clashes_2p5a": {
            "atom_pair_count": 99 + offset,
            "residue_pair_count": 9 + offset,
            "atom_pairs": [["must", "not", "enter", "tsv"]],
            "residue_pairs": [["must", "not", "enter", "tsv"]],
            "vhh_pvrig": {
                "residue_pair_count": 2 + offset,
                "atom_pairs": [["must", "not", "enter", "tsv"]],
            },
            "vhh_pvrl2": {
                "residue_pair_count": 3 + offset,
                "atom_pairs": [["must", "not", "enter", "tsv"]],
            },
        },
        "overlay": {"t_ca_rmsd_a": 0.5 + offset / 100},
    }


def build_fixture(
    root: Path,
    candidate: str = "open_1",
    split: str = "OPEN_TRAIN",
    models: int = 4,
) -> tuple[Path, Path, Path, Path, Path]:
    project = root / "project"
    results = project / "results"
    runs = project / "runs"
    results.mkdir(parents=True)
    runs.mkdir()
    shortlist = root / "shortlist50.tsv"
    split_manifest = root / "fullqc290_split_manifest.tsv"
    job_manifest = project / "manifests" / "docking_jobs.tsv"
    write_tsv(shortlist, [{"candidate_id": candidate, "rank": "1"}])
    write_tsv(
        split_manifest, [{"candidate_id": candidate, "model_split": split}]
    )
    jobs: list[dict[str, str]] = []
    for conformation in MOD.CONFORMATIONS:
        for seed in MOD.SEEDS:
            job_id = f"job_{conformation}_{seed}"
            job_hash = hashlib.sha256(job_id.encode("ascii")).hexdigest()
            jobs.append(
                {
                    "job_id": job_id,
                    "entity_type": "candidate",
                    "entity_id": candidate,
                    "conformation": conformation,
                    "seed": seed,
                    "job_hash": job_hash,
                    "unused_production_field": "preserved",
                }
            )
            pose_scores = []
            run_dir = runs / job_id
            run_dir.mkdir()
            for index in range(models):
                pose = run_dir / f"cluster_1_model_{index + 1}.pdb.gz"
                with gzip.GzipFile(filename=str(pose), mode="wb", mtime=0) as handle:
                    handle.write(f"MODEL {index + 1}\nEND\n".encode("ascii"))
                pose_scores.append(
                    {
                        "pose": str(pose.resolve()),
                        "haddock_io": {
                            "score": [-10.0, -30.0, -20.0, -5.0][index]
                            if index < 4 else float(index),
                            "unw_energies.air": 0.0,
                        },
                        "scores": [geometry("8x6b", index), geometry("9e6y", index + 1)],
                    }
                )
            result_dir = results / job_id
            result_dir.mkdir()
            (result_dir / "job_result.json").write_text(
                json.dumps(
                    {
                        "state": "SUCCESS",
                        "job_id": job_id,
                        "job_hash": job_hash,
                        "entity_type": "candidate",
                        "entity_id": candidate,
                        "dock_conformation": conformation,
                        "seed": int(seed),
                        "selected_model_count": models,
                        "pose_scores": pose_scores,
                    }
                ),
                encoding="utf-8",
            )
    write_tsv(job_manifest, jobs)
    return shortlist, split_manifest, job_manifest, results, project


def run_args(
    shortlist: Path,
    split_manifest: Path,
    jobs: Path,
    results: Path,
    project: Path,
    outdir: Path,
    expected_count: int = 1,
) -> list[str]:
    return [
        "--shortlist", str(shortlist),
        "--split-manifest", str(split_manifest),
        "--job-manifest", str(jobs),
        "--results-root", str(results),
        "--project-root", str(project),
        "--outdir", str(outdir),
        "--expected-count", str(expected_count),
        "--models-per-job", "4",
    ]


class PoseReviewBundleTests(unittest.TestCase):
    def test_prospective_candidate_fails_before_raw_result_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root, split="PROSPECTIVE_COMPUTATIONAL_TEST")
            raw = inputs[3] / "job_8x6b_917" / "job_result.json"
            raw.write_text("not JSON", encoding="utf-8")
            with self.assertRaisesRegex(
                MOD.ContractError, "prospective computational test"
            ):
                MOD.run(MOD.parse_args(run_args(*inputs, root / "bundle")))

    def test_requires_exact_six_real_seed_jobs_and_success_identity_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root)
            jobs_path = inputs[2]
            with jobs_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            write_tsv(jobs_path, rows[:-1])
            with self.assertRaisesRegex(MOD.ContractError, "Six-job closure failed"):
                MOD.run(MOD.parse_args(run_args(*inputs, root / "missing_job")))

            inputs = build_fixture(root / "second")
            result = inputs[3] / "job_8x6b_917" / "job_result.json"
            payload = json.loads(result.read_text(encoding="utf-8"))
            payload["job_hash"] = "wrong"
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MOD.ContractError, "job_hash mismatch"):
                MOD.run(MOD.parse_args(run_args(*inputs, root / "hash_mismatch")))

            inputs = build_fixture(root / "third")
            result = inputs[3] / "job_8x6b_917" / "job_result.json"
            payload = json.loads(result.read_text(encoding="utf-8"))
            payload["entity_id"] = "different_candidate"
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MOD.ContractError, "entity_id identity mismatch"):
                MOD.run(MOD.parse_args(run_args(*inputs, root / "identity_mismatch")))

            inputs = build_fixture(root / "fourth")
            result = inputs[3] / "job_8x6b_917" / "job_result.json"
            payload = json.loads(result.read_text(encoding="utf-8"))
            payload["state"] = "FAILED"
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MOD.ContractError, "not SUCCESS"):
                MOD.run(MOD.parse_args(run_args(*inputs, root / "failed_state")))

    def test_requires_four_complete_2x2_pose_scores(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root, models=3)
            with self.assertRaisesRegex(MOD.ContractError, "fewer than 4"):
                MOD.run(MOD.parse_args(run_args(*inputs, root / "too_few")))

            inputs = build_fixture(root / "second")
            result = inputs[3] / "job_8x6b_917" / "job_result.json"
            payload = json.loads(result.read_text(encoding="utf-8"))
            payload["pose_scores"][0]["scores"] = payload["pose_scores"][0]["scores"][:1]
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MOD.ContractError, r"scores\[2\]"):
                MOD.run(MOD.parse_args(run_args(*inputs, root / "incomplete_2x2")))

    def test_missing_pvrl2_specific_clash_metric_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root)
            result = inputs[3] / "job_8x6b_917" / "job_result.json"
            payload = json.loads(result.read_text(encoding="utf-8"))
            for score in payload["pose_scores"][0]["scores"]:
                del score["clashes_2p5a"]["vhh_pvrl2"]
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                MOD.ContractError, "Missing vhh_pvrl2 residue-pair clashes"
            ):
                MOD.run(MOD.parse_args(run_args(*inputs, root / "missing_pvrl2")))

    def test_top3_compact_geometry_compressed_copy_hash_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root)
            outdir = root / "bundle"
            argv = run_args(*inputs, outdir)
            project_index = argv.index("--project-root")
            del argv[project_index : project_index + 2]
            audit = MOD.run(MOD.parse_args(argv))
            with (outdir / "pose_review_manifest.tsv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 18)
            top = [
                row for row in rows
                if row["conformation"] == "8x6b" and row["seed"] == "917"
            ]
            self.assertEqual(
                [row["model"] for row in top],
                ["cluster_1_model_2.pdb.gz", "cluster_1_model_3.pdb.gz", "cluster_1_model_1.pdb.gz"],
            )
            for row in rows:
                target = outdir / row["bundle_relpath"]
                self.assertTrue(target.name.endswith(".pdb.gz"))
                self.assertEqual(row["source_sha256"], row["target_sha256"])
                self.assertEqual(
                    row["target_sha256"], hashlib.sha256(target.read_bytes()).hexdigest()
                )
                for field in ("geometry_8x6b_summary", "geometry_9e6y_summary"):
                    summary = json.loads(row[field])
                    self.assertEqual(
                        set(summary),
                        {
                            "reference_id", "hotspot_full_count",
                            "hotspot_anchor_count", "hotspot_holdout_count",
                            "total_occlusion", "cdr3_occlusion", "cdr3_fraction",
                            "vhh_pvrig_clash_residue_pairs",
                            "vhh_pvrl2_clash_residue_pairs", "overlay_rmsd_a",
                        },
                    )
                    self.assertNotIn("atom_pairs", row[field])
                    self.assertNotIn("ignored-large-field", row[field])
                    self.assertNotIn('[["ignored"', row[field])
            self.assertEqual(audit["successful_job_count"], 6)
            self.assertEqual(
                audit["input_sha256"]["packager"],
                hashlib.sha256(MODULE_PATH.read_bytes()).hexdigest(),
            )
            self.assertEqual(audit["project_root"], str(inputs[4].resolve()))
            self.assertIn("pose_review_manifest.tsv", (outdir / "SHA256SUMS").read_text())
            with tarfile.open(outdir / "pose_review_bundle.tar.gz", "r:gz") as archive:
                self.assertIn("SHA256SUMS", archive.getnames())

    def test_pose_must_remain_inside_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root)
            outside = root / "outside.pdb.gz"
            outside.write_bytes(b"outside")
            result = inputs[3] / "job_8x6b_917" / "job_result.json"
            payload = json.loads(result.read_text(encoding="utf-8"))
            payload["pose_scores"][0]["pose"] = str(outside.resolve())
            result.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MOD.ContractError, "escapes project root"):
                MOD.run(MOD.parse_args(run_args(*inputs, root / "bundle")))

    def test_hash_fixed_real_v4d_schema_fixture(self) -> None:
        self.assertEqual(
            hashlib.sha256(REAL_SCHEMA_FIXTURE.read_bytes()).hexdigest(),
            REAL_SCHEMA_FIXTURE_SHA256,
        )
        fixture = json.loads(REAL_SCHEMA_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            fixture["provenance"]["source_job_result_sha256"],
            "07d028f5a55855164319d0910ecc23823a81adca1f8ac3b789b52958f159eed5",
        )
        template = fixture["job_result"]
        candidate = template["entity_id"]

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            results = project / "results"
            jobs_path = project / "manifests" / "docking_jobs.tsv"
            shortlist = root / "shortlist.tsv"
            split_manifest = root / "split.tsv"
            write_tsv(shortlist, [{"candidate_id": candidate, "rank": "1"}])
            write_tsv(
                split_manifest,
                [{"candidate_id": candidate, "model_split": "OPEN_TRAIN"}],
            )

            jobs = []
            for conformation in MOD.CONFORMATIONS:
                for seed in MOD.SEEDS:
                    job_id = f"REAL_SCHEMA_{conformation}_{seed}"
                    job_hash = hashlib.sha256(job_id.encode("ascii")).hexdigest()
                    payload = copy.deepcopy(template)
                    payload.update(
                        {
                            "dock_conformation": conformation,
                            "job_hash": job_hash,
                            "job_id": job_id,
                            "seed": int(seed),
                        }
                    )
                    payload["selected_models"] = [
                        path.replace("__JOB_ID__", job_id)
                        for path in payload["selected_models"]
                    ]
                    for pose in payload["pose_scores"]:
                        pose_path = Path(
                            pose["pose"]
                            .replace("__PROJECT_ROOT__", str(project))
                            .replace("__JOB_ID__", job_id)
                        )
                        pose_path.parent.mkdir(parents=True, exist_ok=True)
                        with gzip.GzipFile(
                            filename=str(pose_path), mode="wb", mtime=0
                        ) as handle:
                            handle.write(b"MODEL 1\nEND\n")
                        pose["pose"] = str(pose_path)
                        pose["haddock_io"]["path"] = (
                            pose["haddock_io"]["path"]
                            .replace("__PROJECT_ROOT__", str(project))
                            .replace("__JOB_ID__", job_id)
                        )
                    result = results / job_id / "job_result.json"
                    result.parent.mkdir(parents=True, exist_ok=True)
                    result.write_text(json.dumps(payload), encoding="utf-8")
                    jobs.append(
                        {
                            "job_id": job_id,
                            "entity_type": "candidate",
                            "entity_id": candidate,
                            "conformation": conformation,
                            "seed": seed,
                            "job_hash": job_hash,
                        }
                    )
            write_tsv(jobs_path, jobs)

            outdir = root / "bundle"
            audit = MOD.run(
                MOD.parse_args(
                    run_args(
                        shortlist,
                        split_manifest,
                        jobs_path,
                        results,
                        project,
                        outdir,
                    )
                )
            )
            self.assertEqual(audit["successful_job_count"], 6)
            with (outdir / "pose_review_manifest.tsv").open(
                encoding="utf-8", newline=""
            ) as handle:
                self.assertEqual(len(list(csv.DictReader(handle, delimiter="\t"))), 18)

    @unittest.skipUnless(
        all(
            os.environ.get(name)
            for name in (
                "PVRIG_V4D_SHORTLIST", "PVRIG_V4D_SPLIT_MANIFEST",
                "PVRIG_V4D_JOB_MANIFEST", "PVRIG_V4D_RESULTS_ROOT",
            )
        ),
        "set PVRIG_V4D_* paths to run the production-schema smoke",
    )
    def test_production_schema_smoke(self) -> None:
        """Run one real open candidate through all six V4-D jobs when configured."""
        with tempfile.TemporaryDirectory() as temporary:
            results = Path(os.environ["PVRIG_V4D_RESULTS_ROOT"])
            project = Path(os.environ.get("PVRIG_V4D_PROJECT_ROOT", results.parent))
            argv = run_args(
                Path(os.environ["PVRIG_V4D_SHORTLIST"]),
                Path(os.environ["PVRIG_V4D_SPLIT_MANIFEST"]),
                Path(os.environ["PVRIG_V4D_JOB_MANIFEST"]),
                results,
                project,
                Path(temporary) / "production_smoke_bundle",
                expected_count=int(os.environ.get("PVRIG_V4D_SMOKE_COUNT", "1")),
            )
            audit = MOD.run(MOD.parse_args(argv))
            self.assertEqual(
                audit["successful_job_count"],
                audit["candidate_count"] * 6,
            )


if __name__ == "__main__":
    unittest.main()

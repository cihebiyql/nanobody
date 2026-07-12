#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHER = ROOT / "scripts/watch_and_finalize_geometry4.py"
spec = importlib.util.spec_from_file_location("geometry4_watcher", WATCHER)
watcher = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(watcher)


def write_csv(path: Path, rows: list[dict[str, str]], delimiter: str = ",") -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


class PostWaiterFinalizeTests(unittest.TestCase):
    def test_waiter_decision_fails_closed_on_stale_or_terminal_state(self) -> None:
        self.assertEqual(
            watcher.waiter_decision({"state": "WAITING_FOR_LOAD", "session_running": "1"}),
            "WAIT",
        )
        self.assertEqual(watcher.waiter_decision({"state": "COMPLETE", "session_running": "0"}), "PROCEED")
        for status in (
            {"state": "WAITING_FOR_LOAD", "session_running": "0"},
            {"state": "TIMED_OUT", "session_running": "0"},
            {"state": "FAILED", "session_running": "0"},
            {"state": "COMPLETE ", "session_running": "0"},
            {"state": "complete", "session_running": "0"},
            {"state": "RUNNER_COMPLETE", "session_running": "0"},
            {"state": "UNKNOWN", "session_running": "1"},
        ):
            with self.subTest(status=status):
                with self.assertRaises(watcher.FinalizeError):
                    watcher.waiter_decision(status)

    def test_status_parser_rejects_malformed_or_duplicate_keys(self) -> None:
        self.assertEqual(
            watcher.parse_env_text("session_running=1\nstate=WAITING_FOR_LOAD\ndetail=a=b\n"),
            {"session_running": "1", "state": "WAITING_FOR_LOAD", "detail": "a=b"},
        )
        for text in ("state\n", "bad-key=value\n", "state=A\nstate=B\n"):
            with self.subTest(text=text):
                with self.assertRaises(watcher.FinalizeError):
                    watcher.parse_env_text(text)

    def test_run_completeness_requires_consensus_and_nonempty_top_pose(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            (run / "traceback").mkdir(parents=True)
            (run / "6_seletopclusts").mkdir()
            (run / "traceback/consensus.tsv").write_text("rank\n1\n", encoding="ascii")
            self.assertFalse(watcher.run_complete(run))
            pose = run / "6_seletopclusts/cluster_1_model_1.pdb"
            pose.write_text("", encoding="ascii")
            self.assertFalse(watcher.run_complete(run))
            pose.write_text("ATOM\n", encoding="ascii")
            self.assertTrue(watcher.run_complete(run))

    def test_postprocess_validation_requires_all_four_dual_baseline_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audit = root / "audit.csv"
            finalize = root / "finalize.csv"
            status = root / "status.json"
            rows = []
            for candidate_id, source_id in watcher.EXPECTED_CANDIDATES.items():
                sequence_sha = hashlib.sha256(source_id.encode()).hexdigest()
                source_hashes = {
                    "input_vhh_sequence_sha256": sequence_sha,
                    "manifest_vhh_seq_sha256": sequence_sha,
                }
                payload_json = json.dumps(
                    {
                        "blocker_class": "CONSENSUS_BINDER_LIKE_C",
                        "candidate_id": candidate_id,
                        "source_candidate_id": source_id,
                        "source_hashes": source_hashes,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                rows.append(
                    {
                        "candidate_id": candidate_id,
                        "source_candidate_id": source_id,
                        "run_status": "RUN",
                        "baseline_count": "2",
                        "blocker_class": "CONSENSUS_BINDER_LIKE_C",
                        "import_status": "IMPORTED",
                        "hotspot_overlap_count": "3",
                        "total_vhh_pvrl2_residue_pair_occlusion": "20",
                        "cdr3_pvrl2_residue_pair_occlusion": "4",
                        "cdr3_occlusion_fraction": "0.2",
                        "source_hashes_json": json.dumps(source_hashes, sort_keys=True, separators=(",", ":")),
                        "payload_json": payload_json,
                        "payload_sha256": hashlib.sha256(payload_json.encode()).hexdigest(),
                    }
                )
            valid_rows = [dict(row) for row in rows]
            write_csv(audit, rows)
            write_csv(finalize, rows)
            digest = hashlib.sha256(finalize.read_bytes()).hexdigest()
            status.write_text(
                json.dumps(
                    {
                        "candidate_count": 4,
                        "importable_candidate_count": 4,
                        "candidate_status": [
                            {"candidate_id": candidate_id, "status": "POSTPROCESS_COMPLETE"}
                            for candidate_id in watcher.EXPECTED_CANDIDATES
                        ],
                        "finalize_csv_sha256": digest,
                    }
                ),
                encoding="ascii",
            )
            validated = watcher.validate_postprocess_outputs(status, audit, finalize)
            self.assertEqual(validated["finalize_csv_sha256"], digest)

            rows[0]["baseline_count"] = "1"
            write_csv(audit, rows)
            with self.assertRaises(watcher.FinalizeError):
                watcher.validate_postprocess_outputs(status, audit, finalize)

            write_csv(audit, valid_rows)
            tampered_finalize = [dict(row) for row in valid_rows]
            tampered_finalize[0]["source_hashes_json"] = "[]"
            write_csv(finalize, tampered_finalize)
            tampered_digest = hashlib.sha256(finalize.read_bytes()).hexdigest()
            status_payload = json.loads(status.read_text(encoding="ascii"))
            status_payload["finalize_csv_sha256"] = tampered_digest
            status.write_text(json.dumps(status_payload), encoding="ascii")
            with self.assertRaises(watcher.FinalizeError):
                watcher.validate_postprocess_outputs(status, audit, finalize)

            rows = [dict(row) for row in valid_rows]
            write_csv(audit, rows)
            write_csv(finalize, rows)
            status_payload["finalize_csv_sha256"] = hashlib.sha256(finalize.read_bytes()).hexdigest()
            status.write_text(json.dumps(status_payload), encoding="ascii")
            valid_row = dict(rows[0])
            sequence_sha = json.loads(valid_row["source_hashes_json"])["manifest_vhh_seq_sha256"]
            bad_hash_cases = (
                [],
                {},
                {"input_vhh_sequence_sha256": sequence_sha},
                {
                    "input_vhh_sequence_sha256": "not-a-sha256",
                    "manifest_vhh_seq_sha256": "not-a-sha256",
                },
                {
                    "input_vhh_sequence_sha256": "0" * 64,
                    "manifest_vhh_seq_sha256": "1" * 64,
                },
            )
            for bad_hashes in bad_hash_cases:
                with self.subTest(bad_hashes=bad_hashes):
                    rows[0] = {**valid_row, "source_hashes_json": json.dumps(bad_hashes)}
                    write_csv(audit, rows)
                    with self.assertRaises(watcher.FinalizeError):
                        watcher.validate_postprocess_outputs(status, audit, finalize)

            rows[0] = dict(valid_row)
            bad_payload = json.loads(valid_row["payload_json"])
            bad_payload["source_candidate_id"] = "wrong_source"
            rows[0]["payload_json"] = json.dumps(bad_payload, sort_keys=True, separators=(",", ":"))
            rows[0]["payload_sha256"] = hashlib.sha256(rows[0]["payload_json"].encode()).hexdigest()
            write_csv(audit, rows)
            with self.assertRaises(watcher.FinalizeError):
                watcher.validate_postprocess_outputs(status, audit, finalize)

    def test_cascade_validation_rejects_incomplete_docking_labels(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [
                {
                    "candidate_id": candidate_id,
                    "docking_evidence_status": "IMPORTED",
                    "final_blocker_label": "FINAL_BINDER_NOT_BLOCKER",
                }
                for candidate_id in watcher.EXPECTED_CANDIDATES
            ]
            write_csv(root / "final_blocker_screen.tsv", rows, delimiter="\t")
            (root / "cascade_state.json").write_text(
                json.dumps(
                    {
                        "stages": {
                            "finalize": {
                                "status": "complete",
                                "geometry_candidates": 4,
                                "docking_imported": 4,
                                "final_positive_high": 0,
                            }
                        }
                    }
                ),
                encoding="ascii",
            )
            validated = watcher.validate_cascade_outputs(root)
            self.assertEqual(validated["label_counts"], {"FINAL_BINDER_NOT_BLOCKER": 4})

            rows[0]["final_blocker_label"] = "FINAL_INCOMPLETE_NEEDS_DOCKING"
            write_csv(root / "final_blocker_screen.tsv", rows, delimiter="\t")
            with self.assertRaises(watcher.FinalizeError):
                watcher.validate_cascade_outputs(root)

            rows[0]["final_blocker_label"] = "UNEXPECTED_LABEL"
            write_csv(root / "final_blocker_screen.tsv", rows, delimiter="\t")
            with self.assertRaises(watcher.FinalizeError):
                watcher.validate_cascade_outputs(root)

    def test_remote_finalize_script_is_locked_atomic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_root = root / "run"
            tool_root = root / "tools"
            cascade = run_root / "cascade"
            cascade.mkdir(parents=True)
            (run_root / "panel_blinded.fasta").write_text(">x\nAAAA\n", encoding="ascii")
            (cascade / "cascade_state.json").write_text("{}\n", encoding="ascii")
            (cascade / "final_blocker_screen.tsv").write_text("candidate_id\nold\n", encoding="ascii")
            (cascade / "final_positive_high.fasta").write_text("", encoding="ascii")
            (cascade / "CASCADE_RUN_REPORT.md").write_text("old\n", encoding="ascii")

            calls = root / "calls.txt"
            fake_tool = tool_root / "bin/vhh-large-scale-screen"
            fake_tool.parent.mkdir(parents=True)
            fake_tool.write_text(
                r"""#!/usr/bin/env bash
set -euo pipefail
out=
while [[ $# -gt 0 ]]; do
  if [[ $1 == -o ]]; then out=$2; shift 2; else shift; fi
done
printf 'call\n' >> "$FAKE_CALLS"
mkdir -p "$out"
python3 - "$out" "$FAKE_IDS" <<'PY'
import csv
import json
import sys
from pathlib import Path
out = Path(sys.argv[1])
ids = sys.argv[2].split(',')
state = {'stages': {'finalize': {'status': 'complete', 'geometry_candidates': 4, 'docking_imported': 4, 'final_positive_high': 1}}}
(out / 'cascade_state.json').write_text(json.dumps(state))
with (out / 'final_blocker_screen.tsv').open('w', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=['candidate_id', 'docking_evidence_status', 'final_blocker_label'], delimiter='\t')
    writer.writeheader()
    for index, candidate_id in enumerate(ids):
        writer.writerow({'candidate_id': candidate_id, 'docking_evidence_status': 'IMPORTED', 'final_blocker_label': 'FINAL_POSITIVE_HIGH' if index == 0 else 'FINAL_BINDER_NOT_BLOCKER'})
(out / 'final_positive_high.fasta').write_text('>positive\nAAAA\n')
(out / 'CASCADE_RUN_REPORT.md').write_text('complete\n')
PY
""",
                encoding="ascii",
            )
            fake_tool.chmod(0o755)
            expected_ids = ",".join(sorted(watcher.EXPECTED_CANDIDATES))
            target = run_root / "docking.csv"
            env = {**os.environ, "FAKE_CALLS": str(calls), "FAKE_IDS": expected_ids}

            def execute(stamp: str) -> subprocess.CompletedProcess[str]:
                incoming = run_root / f"incoming.{stamp}.csv"
                incoming.write_text("candidate_id\nexample\n", encoding="ascii")
                digest = hashlib.sha256(incoming.read_bytes()).hexdigest()
                return subprocess.run(
                    [
                        "bash",
                        "-s",
                        "--",
                        str(run_root),
                        str(tool_root),
                        str(incoming),
                        str(target),
                        digest,
                        stamp,
                        expected_ids,
                    ],
                    input=watcher.REMOTE_FINALIZE_SCRIPT,
                    text=True,
                    capture_output=True,
                    env=env,
                    timeout=20,
                )

            first = execute("20260711_010101")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("remote_finalize_mode=FINALIZED", first.stdout)
            self.assertTrue((run_root / "pre_geometry4_complete_finalize_20260711_010101").is_dir())
            self.assertTrue((run_root / "geometry4_complete_finalize_stage_20260711_010101").is_dir())
            self.assertEqual(calls.read_text().splitlines(), ["call"])

            second = execute("20260711_010102")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("remote_finalize_mode=REUSED", second.stdout)
            self.assertFalse((run_root / "pre_geometry4_complete_finalize_20260711_010102").exists())
            self.assertEqual(calls.read_text().splitlines(), ["call"])

    def test_remote_finalize_failure_never_mutates_live_cascade(self) -> None:
        for mode in ("tool_failure", "unsupported_label"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                run_root = root / "run"
                tool_root = root / "tools"
                cascade = run_root / "cascade"
                cascade.mkdir(parents=True)
                (run_root / "panel_blinded.fasta").write_text(">x\nAAAA\n", encoding="ascii")
                live_files = {
                    "cascade_state.json": '{"stages":{"finalize":{"status":"complete","geometry_candidates":4,"docking_imported":1,"final_positive_high":1}}}\n',
                    "final_blocker_screen.tsv": "candidate_id\tdocking_evidence_status\tfinal_blocker_label\nold\tIMPORTED\tFINAL_POSITIVE_HIGH\n",
                    "final_positive_high.fasta": ">old\nAAAA\n",
                    "CASCADE_RUN_REPORT.md": "old\n",
                }
                for name, content in live_files.items():
                    (cascade / name).write_text(content, encoding="ascii")
                before = {name: hashlib.sha256((cascade / name).read_bytes()).hexdigest() for name in live_files}

                fake_tool = tool_root / "bin/vhh-large-scale-screen"
                fake_tool.parent.mkdir(parents=True)
                fake_tool.write_text(
                    r"""#!/usr/bin/env bash
set -euo pipefail
out=
while [[ $# -gt 0 ]]; do
  if [[ $1 == -o ]]; then out=$2; shift 2; else shift; fi
done
if [[ $FAKE_MODE == tool_failure ]]; then
  printf 'corrupt\n' > "$out/final_blocker_screen.tsv"
  exit 9
fi
python3 - "$out" "$FAKE_IDS" <<'PY'
import csv
import json
import sys
from pathlib import Path
out = Path(sys.argv[1])
ids = sys.argv[2].split(',')
state = {'stages': {'finalize': {'status': 'complete', 'geometry_candidates': 4, 'docking_imported': 4, 'final_positive_high': 0}}}
(out / 'cascade_state.json').write_text(json.dumps(state))
with (out / 'final_blocker_screen.tsv').open('w', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=['candidate_id', 'docking_evidence_status', 'final_blocker_label'], delimiter='\t')
    writer.writeheader()
    for candidate_id in ids:
        writer.writerow({'candidate_id': candidate_id, 'docking_evidence_status': 'IMPORTED', 'final_blocker_label': 'UNEXPECTED_LABEL'})
(out / 'final_positive_high.fasta').write_text('')
(out / 'CASCADE_RUN_REPORT.md').write_text('bad label\n')
PY
""",
                    encoding="ascii",
                )
                fake_tool.chmod(0o755)
                expected_ids = ",".join(sorted(watcher.EXPECTED_CANDIDATES))
                incoming = run_root / "incoming.csv"
                incoming.write_text("candidate_id\nexample\n", encoding="ascii")
                digest = hashlib.sha256(incoming.read_bytes()).hexdigest()
                target = run_root / "docking.csv"
                result = subprocess.run(
                    [
                        "bash",
                        "-s",
                        "--",
                        str(run_root),
                        str(tool_root),
                        str(incoming),
                        str(target),
                        digest,
                        "20260711_020202",
                        expected_ids,
                    ],
                    input=watcher.REMOTE_FINALIZE_SCRIPT,
                    text=True,
                    capture_output=True,
                    env={**os.environ, "FAKE_MODE": mode, "FAKE_IDS": expected_ids},
                    timeout=20,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(target.exists())
                self.assertEqual(
                    {name: hashlib.sha256((cascade / name).read_bytes()).hexdigest() for name in live_files},
                    before,
                )
                self.assertFalse((run_root / "pre_geometry4_complete_finalize_20260711_020202").exists())

    def test_watcher_uses_atomic_staging_and_never_deletes_completed_runs(self) -> None:
        source = WATCHER.read_text(encoding="utf-8")
        self.assertIn("os.replace(stage, final_run)", source)
        self.assertIn("refusing incomplete existing local run", source)
        self.assertIn('finalize_state.get("docking_imported") != 4', source)
        self.assertIn("flock -n 9", source)
        self.assertNotIn("rm -rf", source)


if __name__ == "__main__":
    unittest.main()

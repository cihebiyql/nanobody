#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COVERED = {'zym_test_9743', 'zym_test_108006'}
EXPECTED_IDS = [
    'zym_test_359954',
    'zym_test_5495',
    'zym_test_21966',
    'zym_test_3633872',
    'zym_test_8787',
    'zym_test_665332',
    'zym_test_2510237',
    'zym_test_6823',
]
BOUNDARY = 'computational_pose_qc_proxy_not_binding_or_blocker_proof'


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline='') as f:
        return list(csv.DictReader(f, delimiter='\t'))


class V25PackageTest(unittest.TestCase):
    def test_manifest_selection_and_claim_boundary(self) -> None:
        rows = read_tsv(ROOT / 'manifests/selected_candidates_manifest.tsv')
        self.assertEqual([row['candidate_id'] for row in rows], EXPECTED_IDS)
        self.assertTrue(COVERED.isdisjoint({row['candidate_id'] for row in rows}))
        for index, row in enumerate(rows, start=1):
            self.assertEqual(row['selection_rank'], str(index))
            self.assertEqual(row['evidence_boundary'], BOUNDARY)
            self.assertEqual(row['target_chain'], 'B')
            self.assertEqual(hashlib.sha256(row['vhh_seq'].encode()).hexdigest(), row['vhh_seq_sha256'])
            self.assertEqual(hashlib.sha256(row['candidate_payload_json'].encode()).hexdigest(), row['candidate_payload_sha256'])

    def test_input_hash_manifest_matches_files(self) -> None:
        rows = read_tsv(ROOT / 'manifests/input_file_sha256.tsv')
        self.assertGreaterEqual(len(rows), 5)
        for row in rows:
            path = ROOT / row['path']
            self.assertTrue(path.exists(), row['path'])
            self.assertEqual(sha256_file(path), row['sha256'])

    def test_fasta_and_cdr_ranges_match_manifest(self) -> None:
        manifest = {row['candidate_id']: row for row in read_tsv(ROOT / 'manifests/selected_candidates_manifest.tsv')}
        ranges = read_tsv(ROOT / 'inputs/candidate_cdr_ranges.tsv')
        fasta_text = (ROOT / 'inputs/v2_5_pose_batch_vhh.fasta').read_text()
        for row in ranges:
            cid = row['candidate_id']
            seq = manifest[cid]['vhh_seq']
            self.assertIn(f'>{cid} ', fasta_text)
            self.assertIn(seq, fasta_text)
            for label in ('cdr1', 'cdr2', 'cdr3'):
                cdr = row[f'{label}_seq']
                start, end = [int(x) for x in row[f'{label}_range'].split('-')]
                self.assertEqual(seq[start - 1:end], cdr)

    def test_asset_generator_outputs_haddock_inputs(self) -> None:
        subprocess.run(['python3', str(ROOT / 'scripts/make_candidate_haddock_assets.py')], check=True, cwd=ROOT)
        for cid in EXPECTED_IDS:
            data_dir = ROOT / 'haddock3' / cid / 'data'
            cfg = ROOT / 'haddock3' / cid / f'{cid}_pvrig_hotspot.cfg'
            ambig = data_dir / f'{cid}_cdr_to_pvrig_hotspot_ambig.tbl'
            residues = data_dir / f'cdr_residues_{cid}_seq_numbering.txt'
            self.assertTrue(cfg.exists(), cfg)
            self.assertTrue(ambig.exists(), ambig)
            self.assertTrue(residues.exists(), residues)
            self.assertIn(f'run_{cid}_pvrig_hotspot', cfg.read_text())
            self.assertIn('segid A', ambig.read_text())
            self.assertIn('segid B', ambig.read_text())


    def test_local_project_hash_manifest_matches_files(self) -> None:
        rows = []
        for line in (ROOT / 'manifests/local_project_sha256.tsv').read_text().splitlines():
            sha, path = line.split(maxsplit=1)
            rows.append({'sha256': sha, 'path': path})
        self.assertGreaterEqual(len(rows), 50)
        paths = {row['path'] for row in rows}
        self.assertIn('README.md', paths)
        self.assertIn('COMMANDS.md', paths)
        self.assertNotIn('manifests/local_project_sha256.tsv', paths)
        for row in rows:
            path = ROOT / row['path']
            self.assertTrue(path.exists(), row['path'])
            self.assertEqual(sha256_file(path), row['sha256'])

    def test_remote_script_is_gated_not_production_default(self) -> None:
        script = ROOT / 'scripts/run_node1_v2_5_pose_batch.sh'
        text = script.read_text()
        self.assertIn('/data/qlyu/projects/pvrig_v2_5_pose_batch', text)
        self.assertIn('V2_5_RUN_HADDOCK3:-0', text)
        self.assertIn('LOAD_GATE_REFUSE', text)
        self.assertIn('HADDOCK3_GATED_SKIP', text)
        self.assertIn('computational_pose_qc_proxy_not_binding_or_blocker_proof', text)
        subprocess.run(['bash', '-n', str(script)], check=True, cwd=ROOT)

    def test_manifest_json_matches_tsv_ids(self) -> None:
        tsv_ids = [row['candidate_id'] for row in read_tsv(ROOT / 'manifests/selected_candidates_manifest.tsv')]
        json_rows = json.loads((ROOT / 'manifests/selected_candidates_manifest.json').read_text())
        self.assertEqual([row['candidate_id'] for row in json_rows], tsv_ids)


if __name__ == '__main__':
    unittest.main()

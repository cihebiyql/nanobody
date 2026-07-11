#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

REPO_DATA = Path('/mnt/d/work/抗体/data')
ROOT = Path(__file__).resolve().parents[1]
ENSEMBLE = REPO_DATA / 'experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_ai_prior_v2_4_multiseed_ensemble.csv'
P3_MANIFEST = REPO_DATA / 'experiments/phase2_5080_v1/data_splits/p3_optional_pose_manifest_v1.csv'
SEED67 = REPO_DATA / 'experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_ai_prior_v2_4_seed67.csv'
PHASE2_FULL = REPO_DATA / 'experiments/phase2_5080_v1/predictions/pvrig_top_candidates_phase2_v2_2_full2277.csv'
COVERED = {'zym_test_9743', 'zym_test_108006'}
SCHEMA = 'pvrig_vhh_node1_v2_5_pose_batch_manifest_v1'
BOUNDARY = 'computational_pose_qc_proxy_not_binding_or_blocker_proof'


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_by_id(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline='') as f:
        return {row['candidate_id']: row for row in csv.DictReader(f)}


def read_ordered(path: Path) -> list[dict[str, str]]:
    with path.open(newline='') as f:
        return list(csv.DictReader(f))


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_DATA))


def cdr_range(seq: str, cdr: str) -> str:
    start0 = seq.find(cdr)
    if start0 < 0:
        raise ValueError(f'CDR {cdr!r} not found in sequence')
    return f'{start0 + 1}-{start0 + len(cdr)}'


def main() -> None:
    ensemble_rows = read_ordered(ENSEMBLE)
    p3 = read_by_id(P3_MANIFEST)
    seed = read_by_id(SEED67)
    phase2 = read_by_id(PHASE2_FULL)

    selected = [r for r in ensemble_rows if r['candidate_id'] not in COVERED][:8]
    if len(selected) != 8:
        raise SystemExit(f'expected 8 selected candidates, got {len(selected)}')

    manifest_rows: list[dict[str, str]] = []
    cdr_rows: list[dict[str, str]] = []
    fasta_lines: list[str] = []

    source_hashes = {
        rel(ENSEMBLE): sha256_file(ENSEMBLE),
        rel(P3_MANIFEST): sha256_file(P3_MANIFEST),
        rel(SEED67): sha256_file(SEED67),
        rel(PHASE2_FULL): sha256_file(PHASE2_FULL),
    }

    for r in selected:
        cid = r['candidate_id']
        p3_row = p3[cid]
        seed_row = seed[cid]
        phase2_row = phase2[cid]
        seq = p3_row['vhh_seq'] or seed_row['vhh_sequence']
        cdr1 = seed_row['cdr1_candidate'] or seed_row['cdr1']
        cdr2 = seed_row['cdr2_candidate'] or seed_row['cdr2']
        cdr3 = p3_row['cdr3_seq'] or seed_row['cdr3_candidate'] or seed_row['cdr3']
        vhh_hash = sha256_text(seq)
        if seed_row.get('vhh_sequence_sha256') and vhh_hash != seed_row['vhh_sequence_sha256']:
            raise ValueError(f'{cid} sequence hash mismatch')
        cdrs = {
            'cdr1_range': cdr_range(seq, cdr1),
            'cdr2_range': cdr_range(seq, cdr2),
            'cdr3_range': cdr_range(seq, cdr3),
        }
        payload = {
            'v2_4_multiseed_ensemble': r,
            'phase2_v2_2_full2277': phase2_row,
            'cdr_annotation_seed67': {k: seed_row.get(k, '') for k in ['source_input_rank', 'source_v2_2_rank', 'cdr1_candidate', 'cdr2_candidate', 'cdr3_candidate', 'source_score_candidate']},
        }
        payload_json = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        manifest_rows.append({
            'schema_version': SCHEMA,
            'selection_rank': str(len(manifest_rows) + 1),
            'candidate_id': cid,
            'excluded_covered_candidates': ';'.join(sorted(COVERED)),
            'selection_rule': 'top_8_from_v2_4_multiseed_ensemble_excluding_v2_4_top2_covered',
            'consensus_rank': r['consensus_rank'],
            'rank_mean': r['rank_mean'],
            'rank_std': r['rank_std'],
            'rank_stability': r['rank_stability'],
            'phase2_v2_4_sequence_ensemble_score': r['phase2_v2_4_sequence_ensemble_score'],
            'pair_ranking_logit_mean': r['pair_ranking_logit_mean'],
            'ai_prior_mean': r['ai_prior_mean'],
            'target_baseline': p3_row['target_baseline'],
            'vhh_chain': 'A',
            'target_chain': 'B',
            'vhh_seq': seq,
            'vhh_seq_sha256': vhh_hash,
            'cdr1_seq': cdr1,
            'cdr2_seq': cdr2,
            'cdr3_seq': cdr3,
            'cdr1_start_1based': cdrs['cdr1_range'].split('-')[0],
            'cdr1_end_1based': cdrs['cdr1_range'].split('-')[1],
            'cdr2_start_1based': cdrs['cdr2_range'].split('-')[0],
            'cdr2_end_1based': cdrs['cdr2_range'].split('-')[1],
            'cdr3_start_1based': cdrs['cdr3_range'].split('-')[0],
            'cdr3_end_1based': cdrs['cdr3_range'].split('-')[1],
            'cdr_source': 'phase2_v2_4_seed67_candidate_annotation_plus_p3_cdr3',
            'leakage_label': p3_row['leakage_label'],
            'calibration_role': 'candidate_screening_pose_qc_batch',
            'leakage_role': p3_row['leakage_role'],
            'pose_status': 'no_pose_supplied_build_monomer_then_qc_on_node1',
            'evidence_boundary': BOUNDARY,
            'source_candidate_csv_path': rel(ENSEMBLE),
            'source_manifest_path': rel(P3_MANIFEST),
            'source_phase2_full_path': rel(PHASE2_FULL),
            'source_hashes_json': json.dumps(source_hashes, sort_keys=True),
            'candidate_payload_json': payload_json,
            'candidate_payload_sha256': sha256_text(payload_json),
        })
        cdr_rows.append({'candidate_id': cid, **cdrs, 'cdr1_seq': cdr1, 'cdr2_seq': cdr2, 'cdr3_seq': cdr3})
        fasta_lines.extend([f'>{cid} vhh_seq_sha256={vhh_hash} consensus_rank={r["consensus_rank"]} cdr3={cdr3} cdr3_range={cdrs["cdr3_range"]}', seq])

    manifest_tsv = ROOT / 'manifests/selected_candidates_manifest.tsv'
    manifest_json = ROOT / 'manifests/selected_candidates_manifest.json'
    cdr_tsv = ROOT / 'inputs/candidate_cdr_ranges.tsv'
    fasta = ROOT / 'inputs/v2_5_pose_batch_vhh.fasta'

    manifest_tsv.parent.mkdir(parents=True, exist_ok=True)
    with manifest_tsv.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(manifest_rows[0]), delimiter='\t')
        w.writeheader(); w.writerows(manifest_rows)
    manifest_json.write_text(json.dumps(manifest_rows, indent=2) + '\n')
    with cdr_tsv.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['candidate_id', 'cdr1_range', 'cdr2_range', 'cdr3_range', 'cdr1_seq', 'cdr2_seq', 'cdr3_seq'], delimiter='\t')
        w.writeheader(); w.writerows(cdr_rows)
    fasta.write_text('\n'.join(fasta_lines) + '\n')

    input_files = sorted((ROOT / 'inputs').glob('*'))
    with (ROOT / 'manifests/input_file_sha256.tsv').open('w') as f:
        f.write('sha256\tpath\n')
        for path in input_files:
            f.write(f'{sha256_file(path)}\t{path.relative_to(ROOT)}\n')

    print(json.dumps({'selected': [r['candidate_id'] for r in manifest_rows], 'excluded': sorted(COVERED), 'manifest': str(manifest_tsv)}, indent=2))


if __name__ == '__main__':
    main()

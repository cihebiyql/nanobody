#!/usr/bin/env python3
"""Controlled PLAbDab-nano VHH scaffold import and Phase I-b gate scoring.

This script intentionally does not vendor the raw PLAbDab-nano CSV/GZ file. It
streams/downloads the public VHH CSV, imports a bounded unique subset, runs
ANARCI/IMGT, applies scaffold-quality gates, clusters kept scaffolds, and writes
Phase I-b scaffold artifacts.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import math
import os
import re
import statistics
import subprocess
import tempfile
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLDS = ROOT / 'scaffolds'
REPORTS = ROOT / 'reports'
ENV_BIN = ROOT / '.conda-envs' / 'ab-data-validator' / 'bin'
ANARCI = ENV_BIN / 'ANARCI'
PLABNANO_VHH_URL = 'https://opig.stats.ox.ac.uk/webapps/plabdab-nano/static/downloads/vhh_sequences.csv.gz'
LICENSE_NOTE = 'PLAbDab-nano_public_download_dataset_license_not_explicit; local_internal_screening_only; do_not_redistribute_raw_csv'
AA_RE = re.compile(r'^[ACDEFGHIKLMNPQRSTVWY]+$')
POSITION_RE = re.compile(r'^(?P<position>\d+)(?P<insertion>[A-Za-z]*)$')
HYDROPHOBIC = set('AILMFWYV')
POSITIVE = set('KRH')
NEGATIVE = set('DE')

QUALITY_FIELDS = [
    'sequence_id', 'record_id', 'source', 'source_accession', 'source_release', 'source_url_or_path',
    'license_or_use_terms', 'sequence_aa', 'sequence_len', 'species', 'antigen_or_target',
    'patent_or_literature_source', 'chain_class', 'raw_import_status', 'provenance_status',
    'license_gate_status', 'numbering_tool', 'numbering_scheme', 'numbering_status', 'anarci_species',
    'anarci_chain_type', 'fr1_range', 'cdr1_range', 'fr2_range', 'cdr2_range', 'fr3_range',
    'cdr3_range', 'fr4_range', 'cdr1', 'cdr2', 'cdr3', 'cdr1_len', 'cdr2_len', 'cdr3_len',
    'is_vhh', 'framework_health_status', 'developability_status', 'ptm_risk_flags',
    'free_cys_risk', 'low_complexity_score', 'hydrophobic_fraction', 'net_charge',
    'max_cdr_identity_to_HR151_Tab5', 'max_cdr_identity_detail', 'target_related_similarity_status',
    'mechanism_orientation_status', 'cluster_id', 'cluster_member_count', 'score_completeness',
    'score_framework_health', 'score_developability', 'score_cdr_designability', 'score_naturalness',
    'score_novelty', 'score_diversity', 'score_v1_1', 'keep_or_drop', 'drop_reason', 'notes',
]

METADATA_FIELDS = [
    'sequence_id', 'source', 'original_id', 'model', 'type', 'sequence', 'sequence_len', 'species',
    'antigen_or_target', 'patent_or_literature_source', 'reference_authors', 'reference_title',
    'definition', 'update_date', 'source_url', 'source_release', 'license_or_use_terms',
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=2000, help='maximum unique PLAbDab-nano VHH/sdAb records to import')
    parser.add_argument('--url', default=PLABNANO_VHH_URL)
    parser.add_argument('--cluster-threshold', type=float, default=0.90)
    parser.add_argument('--top-n', type=int, default=200)
    args = parser.parse_args()

    if not ANARCI.exists():
        raise SystemExit(f'missing ANARCI binary: {ANARCI}') 

    SCAFFOLDS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    source_release = fetch_last_modified(args.url)
    records, source_row_count = import_records(args.url, args.limit, source_release)
    write_raw_outputs(records)

    anarci_rows = run_anarci_batch(SCAFFOLDS / 'raw_vhh_scaffold_pool.fasta')
    positives = load_positive_heavy_cdrs()
    quality = build_quality_rows(records, anarci_rows, positives, args.url, source_release)
    assign_clusters_and_scores(quality, args.cluster_threshold)
    write_quality_outputs(quality, args.top_n, args.cluster_threshold)
    write_summary(quality, source_row_count, args.limit, args.top_n, args.cluster_threshold, source_release)
    update_source_registry(source_release, len(records), quality)
    print_summary(quality, source_row_count, len(records), args.top_n)


def fetch_last_modified(url: str) -> str:
    req = urllib.request.Request(url, method='HEAD')
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.headers.get('Last-Modified', '')


def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'Accept-Encoding': 'identity', 'User-Agent': 'pvrig-phase-i-b/1.0'})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()


def decode_csv_bytes(blob: bytes) -> str:
    if blob.startswith(b'\x1f\x8b'):
        return gzip.decompress(blob).decode('utf-8-sig')
    return blob.decode('utf-8-sig')


def import_records(url: str, limit: int, source_release: str) -> tuple[list[dict[str, str]], int]:
    text = decode_csv_bytes(download_bytes(url))
    reader = csv.DictReader(text.splitlines())
    records = []
    seen_sequences: set[str] = set()
    total = 0
    for raw in reader:
        total += 1
        seq = normalize_sequence(raw.get('sequence', ''))
        typ = (raw.get('type') or '').strip()
        if typ not in {'VHH', 'VHH/sdAb'}:
            continue
        if not seq or seq in seen_sequences or not AA_RE.match(seq):
            continue
        seen_sequences.add(seq)
        idx = len(records) + 1
        source = (raw.get('source') or 'PLAbDab-nano').strip()
        original_id = (raw.get('ID') or raw.get('model') or f'row_{total}').strip()
        sequence_id = f'PLDNANO_VHH_{idx:05d}'
        records.append({
            'sequence_id': sequence_id,
            'source': f'PLAbDab-nano:{source}',
            'original_id': original_id,
            'model': (raw.get('model') or '').strip(),
            'type': typ,
            'sequence': seq,
            'sequence_len': str(len(seq)),
            'species': (raw.get('organism') or '').strip(),
            'antigen_or_target': (raw.get('targets_mentioned') or '').strip(),
            'patent_or_literature_source': (raw.get('reference_title') or raw.get('definition') or '').strip(),
            'reference_authors': (raw.get('reference_authors') or '').strip(),
            'reference_title': (raw.get('reference_title') or '').strip(),
            'definition': (raw.get('definition') or '').strip(),
            'update_date': (raw.get('update_date') or '').strip(),
            'source_url': url,
            'source_release': source_release,
            'license_or_use_terms': LICENSE_NOTE,
        })
        if len(records) >= limit:
            break
    return records, total


def normalize_sequence(seq: str) -> str:
    return re.sub(r'[^A-Za-z]', '', seq or '').upper()


def write_raw_outputs(records: list[dict[str, str]]) -> None:
    fasta = SCAFFOLDS / 'raw_vhh_scaffold_pool.fasta'
    with fasta.open('w') as handle:
        for row in records:
            # Keep FASTA IDs stable/simple so ANARCI CSV rows can be joined back.
            handle.write(f">{row['sequence_id']}\n{row['sequence']}\n")
    with (SCAFFOLDS / 'raw_vhh_scaffold_metadata.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=METADATA_FIELDS)
        writer.writeheader()
        writer.writerows(records)


def run_anarci_batch(fasta: Path) -> dict[str, dict[str, str]]:
    with tempfile.TemporaryDirectory(prefix='plabnano_anarci_') as tmp_s:
        prefix = Path(tmp_s) / 'anarci'
        env = os.environ.copy()
        env['PATH'] = f'{ENV_BIN}:{env.get("PATH", "")}'
        cmd = [str(ANARCI), '-i', str(fasta), '-o', str(prefix), '--scheme', 'imgt', '--csv']
        result = subprocess.run(cmd, cwd=ROOT, env=env, check=False, capture_output=True, text=True)
        (REPORTS / 'plabdab_nano_anarci.stdout').write_text(result.stdout)
        (REPORTS / 'plabdab_nano_anarci.stderr').write_text(result.stderr)
        if result.returncode != 0:
            raise SystemExit(f'ANARCI failed with exit code {result.returncode}; see reports/plabdab_nano_anarci.stderr')
        csv_path = Path(f'{prefix}_H.csv')
        if not csv_path.exists():
            csv_path = prefix.with_suffix('.H.csv')
        if not csv_path.exists():
            raise SystemExit('ANARCI did not produce an H-chain CSV')
        with csv_path.open(newline='') as handle:
            return {row['Id']: row for row in csv.DictReader(handle)}


def load_positive_heavy_cdrs() -> dict[str, dict[str, str]]:
    positives: dict[str, dict[str, str]] = {}
    with (ROOT / 'positives' / 'known_positive_CDR_table.csv').open(newline='') as handle:
        for row in csv.DictReader(handle):
            if row['chain'] in {'VH', 'VHH'}:
                positives[row['record_id']] = {'cdr1': row['cdr1'], 'cdr2': row['cdr2'], 'cdr3': row['cdr3']}
    return positives


def build_quality_rows(records: list[dict[str, str]], anarci_rows: dict[str, dict[str, str]], positives: dict[str, dict[str, str]], url: str, source_release: str) -> list[dict[str, str]]:
    quality = []
    for rec in records:
        seq = rec['sequence']
        arow = anarci_rows.get(rec['sequence_id'])
        drop: list[str] = []
        notes: list[str] = []
        raw_ok = bool(seq and AA_RE.match(seq))
        provenance_ok = bool(rec['source'] and rec['original_id'] and rec['source_url'])
        if not raw_ok:
            drop.append('invalid_raw_sequence')
        if not provenance_ok:
            drop.append('missing_provenance')

        residues = parse_anarci_row(arow) if arow else []
        cdr1, cdr2, cdr3 = extract_region(residues, 27, 38), extract_region(residues, 56, 65), extract_region(residues, 105, 117)
        fr1, fr2, fr3, fr4 = extract_region(residues, 1, 26), extract_region(residues, 39, 55), extract_region(residues, 66, 104), extract_region(residues, 118, 128)
        numbering_status = 'anarci_success' if arow and residues else 'anarci_failed'
        if numbering_status != 'anarci_success':
            drop.append('anarci_failed')
        if not (cdr1 and cdr2 and cdr3 and fr1 and fr2 and fr3 and fr4):
            drop.append('incomplete_imgt_regions')

        is_vhh = rec['type'] in {'VHH', 'VHH/sdAb'} and (not arow or arow.get('chain_type') == 'H')
        if not is_vhh:
            drop.append('not_vhh_or_sdAb')

        framework_status, framework_score, fw_notes = framework_health(residues, seq)
        develop_status, develop_score, ptm_flags, free_cys_risk, low_complexity, hydrophobic_fraction, net_charge, dev_notes = developability(seq, cdr1 + cdr2 + cdr3)
        cdr_design_score, cdr_notes = cdr_designability(cdr1, cdr2, cdr3)
        naturalness = naturalness_score(seq, rec, cdr1, cdr2, cdr3)
        max_identity, max_detail = max_positive_cdr_identity({'cdr1': cdr1, 'cdr2': cdr2, 'cdr3': cdr3}, positives)
        novelty = novelty_score(max_identity)

        if framework_status.startswith('fail'):
            drop.append(framework_status)
        if develop_status.startswith('fail'):
            drop.append(develop_status)
        if max_identity >= 80.0:
            drop.append('positive_cdr_identity_ge_80pct')
        if not (8 <= len(cdr3) <= 26):
            drop.append('cdr3_length_outside_designable_range')

        # Phase I-b is scaffold-only: mechanism orientation means the hotspot set is available for later redesign.
        mechanism_status = 'hotspot_set_v1_available_no_docking_in_phase_i_b'
        notes.extend(fw_notes + dev_notes + cdr_notes)
        row = {
            'sequence_id': rec['sequence_id'],
            'record_id': rec['sequence_id'],
            'source': rec['source'],
            'source_accession': rec['original_id'],
            'source_release': source_release,
            'source_url_or_path': url,
            'license_or_use_terms': LICENSE_NOTE,
            'sequence_aa': seq,
            'sequence_len': str(len(seq)),
            'species': rec['species'],
            'antigen_or_target': rec['antigen_or_target'],
            'patent_or_literature_source': rec['patent_or_literature_source'],
            'chain_class': rec['type'],
            'raw_import_status': 'raw_sequence_ok' if raw_ok else 'raw_sequence_failed',
            'provenance_status': 'provenance_ok' if provenance_ok else 'provenance_incomplete',
            'license_gate_status': 'use_term_caveat_recorded_local_internal_screening_only',
            'numbering_tool': 'ANARCI',
            'numbering_scheme': 'IMGT',
            'numbering_status': numbering_status,
            'anarci_species': arow.get('hmm_species', '') if arow else '',
            'anarci_chain_type': arow.get('chain_type', '') if arow else '',
            'fr1_range': '1-26' if fr1 else '',
            'cdr1_range': '27-38' if cdr1 else '',
            'fr2_range': '39-55' if fr2 else '',
            'cdr2_range': '56-65' if cdr2 else '',
            'fr3_range': '66-104' if fr3 else '',
            'cdr3_range': '105-117' if cdr3 else '',
            'fr4_range': '118-128' if fr4 else '',
            'cdr1': cdr1,
            'cdr2': cdr2,
            'cdr3': cdr3,
            'cdr1_len': str(len(cdr1)),
            'cdr2_len': str(len(cdr2)),
            'cdr3_len': str(len(cdr3)),
            'is_vhh': 'yes' if is_vhh else 'no',
            'framework_health_status': framework_status,
            'developability_status': develop_status,
            'ptm_risk_flags': ';'.join(ptm_flags),
            'free_cys_risk': free_cys_risk,
            'low_complexity_score': f'{low_complexity:.3f}',
            'hydrophobic_fraction': f'{hydrophobic_fraction:.3f}',
            'net_charge': str(net_charge),
            'max_cdr_identity_to_HR151_Tab5': f'{max_identity:.1f}',
            'max_cdr_identity_detail': max_detail,
            'target_related_similarity_status': 'pass_positive_leakage_gate' if max_identity < 80.0 else 'fail_positive_leakage_gate',
            'mechanism_orientation_status': mechanism_status,
            'cluster_id': '',
            'cluster_member_count': '',
            'score_completeness': f'{completeness_score(numbering_status, cdr1, cdr2, cdr3, fr1, fr2, fr3, fr4):.3f}',
            'score_framework_health': f'{framework_score:.3f}',
            'score_developability': f'{develop_score:.3f}',
            'score_cdr_designability': f'{cdr_design_score:.3f}',
            'score_naturalness': f'{naturalness:.3f}',
            'score_novelty': f'{novelty:.3f}',
            'score_diversity': '0.000',
            'score_v1_1': '0.000',
            'keep_or_drop': 'drop' if drop else 'keep',
            'drop_reason': ';'.join(sorted(set(drop))),
            'notes': ';'.join(notes),
        }
        quality.append(row)
    return quality


def parse_anarci_row(row: dict[str, str] | None) -> list[tuple[int, str, str]]:
    if not row:
        return []
    residues = []
    for key, value in row.items():
        m = POSITION_RE.match(key or '')
        if not m:
            continue
        aa = (value or '').strip()
        if not aa or aa in {'-', '.'}:
            continue
        residues.append((int(m.group('position')), m.group('insertion'), aa))
    return sorted(residues, key=lambda x: (x[0], x[1]))


def extract_region(residues: list[tuple[int, str, str]], start: int, end: int) -> str:
    return ''.join(aa for pos, _ins, aa in residues if start <= pos <= end and aa not in {'-', '.'})


def residue_at(residues: list[tuple[int, str, str]], pos: int) -> str:
    vals = [aa for p, _ins, aa in residues if p == pos]
    return vals[0] if vals else ''


def framework_health(residues: list[tuple[int, str, str]], seq: str) -> tuple[str, float, list[str]]:
    score = 1.0
    notes: list[str] = []
    if residues:
        if residue_at(residues, 23) != 'C':
            score -= 0.35
            notes.append('missing_imgt_cys23')
        if residue_at(residues, 104) != 'C':
            score -= 0.35
            notes.append('missing_imgt_cys104')
        # Advisory VHH hallmark-like checks; not hard failures because numbering conventions differ.
        if residue_at(residues, 44) not in {'E', 'Q'}:
            score -= 0.05
            notes.append('fr2_44_not_E_or_Q')
        if residue_at(residues, 45) not in {'R', 'K', 'L'}:
            score -= 0.05
            notes.append('fr2_45_unusual')
        if residue_at(residues, 47) not in {'G', 'L', 'W', 'F'}:
            score -= 0.05
            notes.append('fr2_47_unusual')
    total_cys = seq.count('C')
    if total_cys % 2 == 1:
        score -= 0.25
        notes.append('odd_total_cys')
    if total_cys > 4:
        score -= 0.20
        notes.append('more_than_four_cys')
    score = max(0.0, score)
    status = 'pass_framework_health' if score >= 0.70 else 'fail_framework_health'
    return status, score, notes


def developability(seq: str, cdrs: str) -> tuple[str, float, list[str], str, float, float, int, list[str]]:
    score = 1.0
    flags: list[str] = []
    notes: list[str] = []
    glyco_all = find_n_glyco(seq)
    glyco_cdr = find_n_glyco(cdrs)
    if glyco_all:
        score -= 0.10
        flags.append('n_glyco_motif')
    if glyco_cdr:
        score -= 0.35
        flags.append('cdr_n_glyco_motif')
    if re.search(r'N[GSTNQ]', cdrs):
        score -= 0.10
        flags.append('cdr_deamidation_motif')
    total_cys = seq.count('C')
    free_cys_risk = 'low'
    if total_cys % 2 == 1:
        score -= 0.25
        free_cys_risk = 'high_odd_cys_count'
    elif total_cys > 4:
        score -= 0.15
        free_cys_risk = 'medium_many_cys'
    hyd = sum(aa in HYDROPHOBIC for aa in seq) / len(seq)
    if hyd > 0.46:
        score -= 0.25
        flags.append('high_hydrophobic_fraction')
    elif hyd > 0.42:
        score -= 0.10
        flags.append('moderate_hydrophobic_fraction')
    low_complexity = max(Counter(seq).values()) / len(seq)
    if low_complexity > 0.22:
        score -= 0.20
        flags.append('low_complexity')
    charge = sum(aa in POSITIVE for aa in seq) - sum(aa in NEGATIVE for aa in seq)
    if abs(charge) > 24:
        score -= 0.15
        flags.append('extreme_net_charge')
    score = max(0.0, score)
    hard_fail = bool(glyco_cdr) or low_complexity > 0.28 or hyd > 0.52 or total_cys % 2 == 1
    status = 'fail_developability' if hard_fail else 'pass_developability'
    if flags:
        notes.append('developability_flags=' + '|'.join(flags))
    return status, score, flags, free_cys_risk, low_complexity, hyd, charge, notes


def find_n_glyco(seq: str) -> list[str]:
    hits = []
    for i in range(len(seq) - 2):
        tri = seq[i:i + 3]
        if tri[0] == 'N' and tri[1] != 'P' and tri[2] in {'S', 'T'}:
            hits.append(f'{tri}@{i+1}')
    return hits


def cdr_designability(cdr1: str, cdr2: str, cdr3: str) -> tuple[float, list[str]]:
    score = 1.0
    notes: list[str] = []
    cdr3_len = len(cdr3)
    if 10 <= cdr3_len <= 22:
        pass
    elif 8 <= cdr3_len <= 26:
        score -= 0.15
        notes.append('cdr3_length_borderline')
    else:
        score -= 0.45
        notes.append('cdr3_length_outside_designable_range')
    if cdr3:
        cdr3_hyd = sum(aa in HYDROPHOBIC for aa in cdr3) / len(cdr3)
        if cdr3_hyd > 0.50:
            score -= 0.20
            notes.append('cdr3_hydrophobic')
        gp = (cdr3.count('G') + cdr3.count('P')) / len(cdr3)
        if gp > 0.55:
            score -= 0.15
            notes.append('cdr3_high_gly_pro')
    if not (cdr1 and cdr2 and cdr3):
        score = 0.0
    return max(0.0, score), notes


def naturalness_score(seq: str, rec: dict[str, str], cdr1: str, cdr2: str, cdr3: str) -> float:
    score = 0.75
    if rec['source'].startswith('PLAbDab-nano:'):
        score += 0.15
    if 105 <= len(seq) <= 135:
        score += 0.05
    if 5 <= len(cdr1) <= 12 and 3 <= len(cdr2) <= 12 and 8 <= len(cdr3) <= 26:
        score += 0.05
    return min(1.0, score)


def completeness_score(numbering_status: str, cdr1: str, cdr2: str, cdr3: str, fr1: str, fr2: str, fr3: str, fr4: str) -> float:
    if numbering_status != 'anarci_success':
        return 0.0
    parts = [cdr1, cdr2, cdr3, fr1, fr2, fr3, fr4]
    return sum(bool(p) for p in parts) / len(parts)


def global_identity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    match, mismatch, gap = 2, -1, -2
    n, m = len(a), len(b)
    score = [[0] * (m + 1) for _ in range(n + 1)]
    trace = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = score[i - 1][0] + gap
        trace[i][0] = 'U'
    for j in range(1, m + 1):
        score[0][j] = score[0][j - 1] + gap
        trace[0][j] = 'L'
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = score[i - 1][j - 1] + (match if a[i - 1] == b[j - 1] else mismatch)
            up = score[i - 1][j] + gap
            left = score[i][j - 1] + gap
            best = max(diag, up, left)
            score[i][j] = best
            trace[i][j] = 'D' if best == diag else ('U' if best == up else 'L')
    i, j = n, m
    matches = 0
    aligned = 0
    while i > 0 or j > 0:
        t = trace[i][j]
        if t == 'D':
            matches += int(a[i - 1] == b[j - 1])
            aligned += 1
            i -= 1
            j -= 1
        elif t == 'U':
            aligned += 1
            i -= 1
        else:
            aligned += 1
            j -= 1
    return 100.0 * matches / aligned if aligned else 0.0


def max_positive_cdr_identity(cdrs: dict[str, str], positives: dict[str, dict[str, str]]) -> tuple[float, str]:
    best = (0.0, '')
    for positive_id, pcdrs in positives.items():
        for key in ['cdr1', 'cdr2', 'cdr3']:
            ident = global_identity(cdrs.get(key, ''), pcdrs.get(key, ''))
            if ident > best[0]:
                best = (ident, f'{positive_id}:{key}')
    return best


def novelty_score(max_identity: float) -> float:
    if max_identity >= 80.0:
        return 0.0
    if max_identity >= 70.0:
        return 0.60
    if max_identity >= 60.0:
        return 0.80
    return 1.0


def assign_clusters_and_scores(rows: list[dict[str, str]], threshold: float) -> None:
    kept = [r for r in rows if r['keep_or_drop'] == 'keep']
    reps: list[dict[str, str]] = []
    members: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in kept:
        assigned = ''
        for rep in reps:
            if simple_sequence_identity(row['sequence_aa'], rep['sequence_aa']) >= threshold:
                assigned = rep['cluster_id']
                break
        if not assigned:
            assigned = f'C{len(reps) + 1:04d}'
            row['cluster_id'] = assigned
            reps.append(row)
        row['cluster_id'] = assigned
        members[assigned].append(row)

    for cluster_id, cluster_rows in members.items():
        size = len(cluster_rows)
        diversity = 1.0 / math.sqrt(size)
        for row in cluster_rows:
            row['cluster_member_count'] = str(size)
            row['score_diversity'] = f'{diversity:.3f}'
            row['score_v1_1'] = f'{weighted_score(row):.3f}'

    for row in rows:
        if row['keep_or_drop'] != 'keep':
            row['score_v1_1'] = f'{weighted_score(row):.3f}'


def weighted_score(row: dict[str, str]) -> float:
    return (
        0.25 * float(row['score_completeness'])
        + 0.20 * float(row['score_framework_health'])
        + 0.20 * float(row['score_developability'])
        + 0.15 * float(row['score_naturalness'])
        + 0.10 * float(row['score_cdr_designability'])
        + 0.05 * float(row['score_novelty'])
        + 0.05 * float(row['score_diversity'])
    )


def simple_sequence_identity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    matches = sum(x == y for x, y in zip(a, b))
    return matches / max(len(a), len(b))


def write_quality_outputs(rows: list[dict[str, str]], top_n: int, threshold: float) -> None:
    with (SCAFFOLDS / 'vhh_scaffold_quality_table.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=QUALITY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    kept = sorted([r for r in rows if r['keep_or_drop'] == 'keep'], key=lambda r: (-float(r['score_v1_1']), r['cluster_id'], r['sequence_id']))
    write_fasta(SCAFFOLDS / 'clean_vhh_scaffold_library.fasta', kept)
    selected = select_top_diverse(kept, top_n)
    write_fasta(SCAFFOLDS / 'top_200_vhh_scaffolds_for_design.fasta', selected)
    with (SCAFFOLDS / 'top_200_vhh_scaffolds_for_design.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=QUALITY_FIELDS)
        writer.writeheader()
        writer.writerows(selected)
    write_cluster_table(kept, selected, threshold)


def select_top_diverse(kept: list[dict[str, str]], top_n: int) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    used_clusters: set[str] = set()
    for row in kept:
        if row['cluster_id'] not in used_clusters:
            selected.append(row)
            used_clusters.add(row['cluster_id'])
            if len(selected) >= top_n:
                return selected
    for row in kept:
        if row not in selected:
            selected.append(row)
            if len(selected) >= top_n:
                break
    return selected


def write_fasta(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open('w') as handle:
        for row in rows:
            handle.write(f">{row['sequence_id']}|score={row['score_v1_1']}|cluster={row['cluster_id']}|source={row['source_accession']}\n{row['sequence_aa']}\n")


def write_cluster_table(kept: list[dict[str, str]], selected: list[dict[str, str]], threshold: float) -> None:
    by_cluster: dict[str, list[dict[str, str]]] = defaultdict(list)
    selected_ids = {r['sequence_id'] for r in selected}
    for row in kept:
        by_cluster[row['cluster_id']].append(row)
    fields = ['cluster_id', 'representative_record_id', 'member_count', 'sources_present', 'max_pairwise_identity', 'mean_score_v1_1', 'selected_for_top_200', 'selection_reason', 'diversity_notes']
    with (SCAFFOLDS / 'vhh_scaffold_cluster_table.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for cluster_id in sorted(by_cluster):
            rows = sorted(by_cluster[cluster_id], key=lambda r: -float(r['score_v1_1']))
            max_pair = max_pairwise_identity(rows[:50]) if len(rows) > 1 else 1.0
            selected_cluster_ids = [r['sequence_id'] for r in rows if r['sequence_id'] in selected_ids]
            writer.writerow({
                'cluster_id': cluster_id,
                'representative_record_id': rows[0]['sequence_id'],
                'member_count': len(rows),
                'sources_present': ';'.join(sorted({r['source'] for r in rows})),
                'max_pairwise_identity': f'{max_pair:.3f}',
                'mean_score_v1_1': f'{statistics.mean(float(r["score_v1_1"]) for r in rows):.3f}',
                'selected_for_top_200': 'yes' if selected_cluster_ids else 'no',
                'selection_reason': 'top_scoring_cluster_representative' if selected_cluster_ids else 'not_selected',
                'diversity_notes': f'greedy_sequence_identity_threshold_{threshold:.2f}',
            })


def max_pairwise_identity(rows: list[dict[str, str]]) -> float:
    best = 0.0
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            best = max(best, simple_sequence_identity(rows[i]['sequence_aa'], rows[j]['sequence_aa']))
    return best


def write_summary(rows: list[dict[str, str]], source_row_count: int, limit: int, top_n: int, threshold: float, source_release: str) -> None:
    imported = len(rows)
    kept = [r for r in rows if r['keep_or_drop'] == 'keep']
    drops = Counter(reason for row in rows for reason in row['drop_reason'].split(';') if reason)
    clusters = {r['cluster_id'] for r in kept if r['cluster_id']}
    top_count = min(top_n, len(kept))
    text = [
        '# PLAbDab-nano Scaffold Gate Summary',
        '',
        '## Scope',
        '',
        f'- Source file: `{PLABNANO_VHH_URL}`',
        f'- Source release marker: `{source_release}`',
        f'- Source rows scanned until import limit: {source_row_count}',
        f'- Unique imported VHH/sdAb records: {imported}',
        f'- Top-N target: {top_n}',
        f'- Cluster identity threshold: {threshold:.2f}',
        '',
        '## Gate Results',
        '',
        f'- ANARCI/IMGT success: {sum(r["numbering_status"] == "anarci_success" for r in rows)}',
        f'- VHH/sdAb classified: {sum(r["is_vhh"] == "yes" for r in rows)}',
        f'- Dropped records: {imported - len(kept)}',
        f'- Clean scaffold records retained: {len(kept)}',
        f'- Clusters among retained scaffolds: {len(clusters)}',
        f'- Top scaffold records written: {top_count}',
        '',
        '## Drop Reasons',
        '',
    ]
    if drops:
        for reason, count in drops.most_common():
            text.append(f'- {reason}: {count}')
    else:
        text.append('- none')
    text.extend([
        '',
        '## Output Files',
        '',
        '- `scaffolds/raw_vhh_scaffold_pool.fasta`',
        '- `scaffolds/raw_vhh_scaffold_metadata.csv`',
        '- `scaffolds/vhh_scaffold_quality_table.csv`',
        '- `scaffolds/clean_vhh_scaffold_library.fasta`',
        '- `scaffolds/vhh_scaffold_cluster_table.csv`',
        '- `scaffolds/top_200_vhh_scaffolds_for_design.fasta`',
        '- `scaffolds/top_200_vhh_scaffolds_for_design.csv`',
        '',
        '## Constraints',
        '',
        '- These scaffolds are not PVRIG binders or blockers.',
        '- No docking, RFantibody, AntiFold, or final Top 50 candidate generation was performed.',
        '- PLAbDab-nano raw CSV/GZ is not vendored; imported rows retain the local-screening use-term caveat.',
    ])
    (REPORTS / 'plabdab_nano_scaffold_gate_summary.md').write_text('\n'.join(text) + '\n')


def update_source_registry(source_release: str, imported_count: int, rows: list[dict[str, str]]) -> None:
    path = SCAFFOLDS / 'source_registry.csv'
    registry = list(csv.DictReader(path.open(newline='')))
    kept = sum(r['keep_or_drop'] == 'keep' for r in rows)
    for row in registry:
        if row['source'] == 'PLAbDab-nano':
            row['status'] = 'controlled_import_completed_local_screening_only'
            row['use_terms_status'] = 'public_csv_download_available; dataset_license_not_explicit_on_page; local_internal_screening_only; do_not_redistribute_raw_csv'
            row['notes'] = f'Controlled import from vhh_sequences.csv.gz release "{source_release}" imported {imported_count} unique rows and retained {kept} clean scaffolds; raw PLAbDab-nano CSV/GZ not vendored.'
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=registry[0].keys())
        writer.writeheader()
        writer.writerows(registry)


def print_summary(rows: list[dict[str, str]], source_rows: int, imported: int, top_n: int) -> None:
    kept = [r for r in rows if r['keep_or_drop'] == 'keep']
    print(f'source_rows_scanned={source_rows}')
    print(f'imported_unique={imported}')
    print(f'anarci_success={sum(r["numbering_status"] == "anarci_success" for r in rows)}')
    print(f'clean_kept={len(kept)}')
    print(f'clusters={len({r["cluster_id"] for r in kept if r["cluster_id"]})}')
    print(f'top_written={min(top_n, len(kept))}')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Four-layer VHH/nanobody screening pipeline for node1.

Layer 1 is a hard gate: unstable numbering or incomplete conserved framework
signals stop downstream expensive evaluation for that sequence.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
from Bio import SeqIO

ROOT = Path('/data/qlyu/software/vhh_eval_tools')
BIN = ROOT / 'bin'
BOLTZ_BIN = Path('/data/qlyu/anaconda3/envs/boltz/bin')

HYDROPHOBIC = set('AVILMFWY')
FR4_STRONG_RE = re.compile(r'^WG.GT.*VTVSS$')
SAFE_ID_RE = re.compile(r'[^A-Za-z0-9_.-]+')


@dataclass
class Candidate:
    seq_id: str
    sequence: str
    vhh_eval: Dict[str, str] = field(default_factory=dict)
    numbering: Dict[str, Dict[str, str]] = field(default_factory=dict)
    sapiens: Dict[str, str] = field(default_factory=dict)
    abnativ: Dict[str, str] = field(default_factory=dict)
    tnp: Dict[str, object] = field(default_factory=dict)
    structure: Dict[str, object] = field(default_factory=dict)
    layer_status: Dict[str, str] = field(default_factory=dict)
    layer_reasons: Dict[str, List[str]] = field(default_factory=lambda: {'L1': [], 'L2': [], 'L3': [], 'L4': []})


def safe_id(seq_id: str) -> str:
    return SAFE_ID_RE.sub('_', seq_id).strip('_') or 'seq'


def as_float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        if value in (None, '', 'NA'):
            return default
        return float(value)
    except Exception:
        return default


def as_int(value, default: int = 0) -> int:
    try:
        if value in (None, '', 'NA'):
            return default
        return int(float(value))
    except Exception:
        return default


def run_cmd(cmd: List[str], log_path: Path, env: Optional[Dict[str, str]] = None, cwd: Optional[Path] = None) -> bool:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    with log_path.open('w') as log:
        log.write('$ ' + ' '.join(cmd) + '\n\n')
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(cwd) if cwd else None, env=merged_env)
        log.write(f'\n[exit_code] {proc.returncode}\n')
    return proc.returncode == 0


def read_tsv(path: Path) -> Dict[str, Dict[str, str]]:
    with path.open(newline='') as handle:
        return {row['id']: row for row in csv.DictReader(handle, delimiter='\t')}


def read_csv_by_id(path: Path, id_col: str = 'seq_id') -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline='') as handle:
        return {row[id_col]: row for row in csv.DictReader(handle)}


def write_fasta(records: Iterable[Candidate], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as handle:
        for c in records:
            handle.write(f'>{c.seq_id}\n{c.sequence}\n')


def read_candidates(fasta: Path) -> Dict[str, Candidate]:
    out: Dict[str, Candidate] = {}
    for rec in SeqIO.parse(str(fasta), 'fasta'):
        seq = re.sub(r'[^A-Za-z]', '', str(rec.seq)).upper()
        out[rec.id] = Candidate(seq_id=rec.id, sequence=seq)
    if not out:
        raise SystemExit(f'No FASTA records found: {fasta}')
    return out


def numbered_aa(c: Candidate, scheme: str, pos: str) -> str:
    return c.numbering.get(scheme, {}).get(pos, '')


def add_reason(c: Candidate, layer: str, severity: str, message: str) -> None:
    c.layer_reasons[layer].append(f'{severity}:{message}')


def layer1_numbering_integrity(c: Candidate) -> str:
    row = c.vhh_eval
    fail = False
    warn = False

    for scheme in ('imgt', 'kabat'):
        if str(row.get(f'{scheme}_ok', '')).lower() != 'true':
            fail = True
            add_reason(c, 'L1', 'FAIL', f'{scheme} numbering failed')
        if row.get(f'{scheme}_chain_type') not in ('H', 'heavy'):
            fail = True
            add_reason(c, 'L1', 'FAIL', f'{scheme} chain_type={row.get(f"{scheme}_chain_type", "NA")}')

    length = as_int(row.get('length'))
    if length < 95 or length > 160:
        fail = True
        add_reason(c, 'L1', 'FAIL', f'length_outside_absolute_range={length}')
    elif length < 105 or length > 145:
        warn = True
        add_reason(c, 'L1', 'WARN', f'length_unusual_for_VHH={length}')

    for key in ('fr1', 'cdr1', 'fr2', 'cdr2', 'fr3', 'cdr3', 'fr4'):
        if not row.get(f'imgt_{key}'):
            fail = True
            add_reason(c, 'L1', 'FAIL', f'missing_imgt_{key}')

    cys23 = numbered_aa(c, 'imgt', 'H23')
    cys104 = numbered_aa(c, 'imgt', 'H104')
    if cys23 != 'C' or cys104 != 'C':
        fail = True
        add_reason(c, 'L1', 'FAIL', f'conserved_cys_not_found_imgt_H23={cys23 or "NA"}_H104={cys104 or "NA"}')

    fr4 = row.get('imgt_fr4') or row.get('kabat_fr4') or ''
    if not (fr4.startswith('W') and fr4.endswith('TVSS')):
        fail = True
        add_reason(c, 'L1', 'FAIL', f'fr4_motif_not_typical={fr4 or "NA"}')
    elif not FR4_STRONG_RE.match(fr4):
        warn = True
        add_reason(c, 'L1', 'WARN', f'fr4_motif_weak_match={fr4}')

    cdr1_len = len(row.get('imgt_cdr1', ''))
    cdr2_len = len(row.get('imgt_cdr2', ''))
    cdr3_len = len(row.get('imgt_cdr3', ''))
    if cdr3_len < 5 or cdr3_len > 30:
        fail = True
        add_reason(c, 'L1', 'FAIL', f'cdr3_length_unreasonable={cdr3_len}')
    if not (4 <= cdr1_len <= 12):
        warn = True
        add_reason(c, 'L1', 'WARN', f'cdr1_length_unusual={cdr1_len}')
    if not (3 <= cdr2_len <= 15):
        warn = True
        add_reason(c, 'L1', 'WARN', f'cdr2_length_unusual={cdr2_len}')
    if 24 < cdr3_len <= 30:
        warn = True
        add_reason(c, 'L1', 'WARN', f'cdr3_length_long={cdr3_len}')

    status = 'FAIL' if fail else ('WARN' if warn else 'PASS')
    c.layer_status['L1'] = status
    return status


def layer2_vhh_features(c: Candidate) -> str:
    fail = False
    warn = False
    row = c.vhh_eval

    score = as_float(row.get('fr2_hallmark_score'))
    if score is None:
        fail = True
        add_reason(c, 'L2', 'FAIL', 'fr2_hallmark_score_missing')
    elif score < 0.50:
        fail = True
        add_reason(c, 'L2', 'FAIL', f'fr2_hallmark_score_low={score}')
    elif score < 0.75:
        warn = True
        add_reason(c, 'L2', 'WARN', f'fr2_hallmark_score_borderline={score}')

    h44 = numbered_aa(c, 'kabat', 'H44')
    h45 = numbered_aa(c, 'kabat', 'H45')
    h47 = numbered_aa(c, 'kabat', 'H47')
    interface_hydrophobic_count = sum(1 for aa in (h44, h45, h47) if aa in HYDROPHOBIC)
    c.structure['fr2_interface_hydrophobic_count'] = interface_hydrophobic_count
    c.structure['fr2_interface_residues'] = f'H44={h44 or "NA"};H45={h45 or "NA"};H47={h47 or "NA"}'
    if not (h44 in set('EQ') and h45 in set('RK')):
        fail = True
        add_reason(c, 'L2', 'FAIL', f'missing_key_hydrophilic_fr2_substitutions_H44={h44 or "NA"}_H45={h45 or "NA"}')
    if interface_hydrophobic_count >= 3:
        fail = True
        add_reason(c, 'L2', 'FAIL', f'vl_interface_too_hydrophobic_count={interface_hydrophobic_count}')
    elif interface_hydrophobic_count == 2:
        warn = True
        add_reason(c, 'L2', 'WARN', f'vl_interface_hydrophobic_count={interface_hydrophobic_count}')

    ab_score = as_float(c.abnativ.get('AbNatiV VHH Score'))
    if ab_score is None:
        warn = True
        add_reason(c, 'L2', 'WARN', 'abnativ_vhh_score_not_available')
    elif ab_score < 0.55:
        fail = True
        add_reason(c, 'L2', 'FAIL', f'abnativ_vhh_score_low={ab_score:.3f}')
    elif ab_score < 0.70:
        warn = True
        add_reason(c, 'L2', 'WARN', f'abnativ_vhh_score_borderline={ab_score:.3f}')

    single_domain_ok = (score is not None and score >= 0.75 and h44 in set('EQ') and h45 in set('RK') and interface_hydrophobic_count <= 1 and (ab_score is None or ab_score >= 0.70))
    c.structure['single_domain_suitability'] = 'good' if single_domain_ok else ('poor' if fail else 'borderline')

    status = 'FAIL' if fail else ('WARN' if warn else 'PASS')
    c.layer_status['L2'] = status
    return status


def tnp_flags(c: Candidate) -> Dict[str, str]:
    flags = c.tnp.get('Flags') if isinstance(c.tnp, dict) else None
    return flags if isinstance(flags, dict) else {}


def layer3_developability(c: Candidate) -> str:
    fail = False
    warn = False
    row = c.vhh_eval

    flags = tnp_flags(c)
    if not flags:
        warn = True
        add_reason(c, 'L3', 'WARN', 'tnp_flags_not_available')
    for key, value in flags.items():
        val = str(value).lower()
        if val in ('red', 'fail', 'failed'):
            fail = True
            add_reason(c, 'L3', 'FAIL', f'tnp_{key}_flag={value}')
        elif val in ('amber', 'yellow', 'warn', 'orange'):
            warn = True
            add_reason(c, 'L3', 'WARN', f'tnp_{key}_flag={value}')

    charge = as_float(row.get('charge_pH7_4'), 0.0) or 0.0
    pI = as_float(row.get('pI'))
    if abs(charge) > 12:
        fail = True
        add_reason(c, 'L3', 'FAIL', f'net_charge_extreme_pH7_4={charge:.2f}')
    elif abs(charge) > 8:
        warn = True
        add_reason(c, 'L3', 'WARN', f'net_charge_high_pH7_4={charge:.2f}')
    if pI is None:
        warn = True
        add_reason(c, 'L3', 'WARN', 'pI_not_available')
    elif pI < 4.5 or pI > 10.5:
        fail = True
        add_reason(c, 'L3', 'FAIL', f'pI_extreme={pI:.2f}')
    elif pI < 5.0 or pI > 9.5:
        warn = True
        add_reason(c, 'L3', 'WARN', f'pI_unusual={pI:.2f}')

    nglyc = as_int(row.get('nglyc_motif_count'))
    if nglyc:
        warn = True
        add_reason(c, 'L3', 'WARN', f'nglyc_motif_count={nglyc}:{row.get("nglyc_motif_hits", "")}')

    cys_count = as_int(row.get('cys_count'))
    if cys_count % 2 == 1:
        fail = True
        add_reason(c, 'L3', 'FAIL', f'odd_cys_count={cys_count}')
    elif cys_count != 2:
        warn = True
        add_reason(c, 'L3', 'WARN', f'noncanonical_cys_count={cys_count}')

    for key in ('deamidation_NG_NS_NT', 'deamidation_NH', 'isomerization_DG_DS_DD_DT', 'acid_cleavage_DP'):
        count = as_int(row.get(f'{key}_count'))
        if count:
            warn = True
            add_reason(c, 'L3', 'WARN', f'{key}_count={count}:{row.get(f"{key}_hits", "")}')
    hydrophobic_runs = as_int(row.get('hydrophobic_5_count'))
    if hydrophobic_runs:
        fail = True
        add_reason(c, 'L3', 'FAIL', f'hydrophobic_run_5_count={hydrophobic_runs}:{row.get("hydrophobic_5_hits", "")}')
    for key in ('poly_basic_4', 'poly_acidic_4', 'integrin_RGD'):
        count = as_int(row.get(f'{key}_count'))
        if count:
            warn = True
            add_reason(c, 'L3', 'WARN', f'{key}_count={count}:{row.get(f"{key}_hits", "")}')

    psh_flag = str(flags.get('PSH', '')).lower()
    ppc_flag = str(flags.get('PPC', '')).lower()
    high_charge = abs(charge) > 8 or (pI is not None and pI > 9.5)
    if psh_flag == 'red' or ppc_flag == 'red' or (high_charge and hydrophobic_runs):
        poly = 'high'
    elif high_charge or psh_flag in ('amber', 'yellow') or ppc_flag in ('amber', 'yellow') or as_int(row.get('poly_basic_4_count')):
        poly = 'moderate'
        warn = True
        add_reason(c, 'L3', 'WARN', f'polyreactivity_proxy={poly}')
    else:
        poly = 'low'
    c.structure['polyreactivity_proxy'] = poly

    status = 'FAIL' if fail else ('WARN' if warn else 'PASS')
    c.layer_status['L3'] = status
    return status


def region_indices(c: Candidate, region_prefix: str = 'imgt') -> Dict[str, List[int]]:
    row = c.vhh_eval
    pos = 0
    out: Dict[str, List[int]] = {}
    for name in ('fr1', 'cdr1', 'fr2', 'cdr2', 'fr3', 'cdr3', 'fr4'):
        seq = row.get(f'{region_prefix}_{name}', '') or ''
        out[name] = list(range(pos, pos + len(seq)))
        pos += len(seq)
    if pos != len(c.sequence):
        # Fall back to full FR/CDR-unaware indexing if AbNumber region stitching differs.
        out['all'] = list(range(len(c.sequence)))
    return out


def parse_ca_coords(pdb_path: Path) -> List[Optional[np.ndarray]]:
    coords: List[Optional[np.ndarray]] = []
    seen = set()
    if not pdb_path.exists():
        return coords
    with pdb_path.open(errors='ignore') as handle:
        for line in handle:
            if not line.startswith('ATOM'):
                continue
            atom = line[12:16].strip()
            if atom != 'CA':
                continue
            try:
                chain = line[21].strip() or ' '
                resseq = int(line[22:26])
                icode = line[26].strip()
                key = (chain, resseq, icode)
                if key in seen:
                    continue
                x = float(line[30:38]); y = float(line[38:46]); z = float(line[46:54])
            except Exception:
                continue
            seen.add(key)
            coords.append(np.array([x, y, z], dtype=float))
    return coords


def kabsch_rmsd(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) == 0 or len(a) != len(b):
        return float('nan')
    a0 = a - a.mean(axis=0)
    b0 = b - b.mean(axis=0)
    cov = a0.T @ b0
    v, _s, wt = np.linalg.svd(cov)
    d = np.sign(np.linalg.det(v @ wt))
    u = v @ np.diag([1.0, 1.0, d]) @ wt
    ar = a0 @ u
    return float(np.sqrt(np.mean(np.sum((ar - b0) ** 2, axis=1))))


def rmsd_for_indices(coords_a: List[Optional[np.ndarray]], coords_b: List[Optional[np.ndarray]], indices: List[int]) -> Optional[float]:
    paired_a = []
    paired_b = []
    for idx in indices:
        if idx < len(coords_a) and idx < len(coords_b):
            paired_a.append(coords_a[idx])
            paired_b.append(coords_b[idx])
    if len(paired_a) < 10:
        return None
    return kabsch_rmsd(np.vstack(paired_a), np.vstack(paired_b))


def load_existing_tnp(c: Candidate, json_path: Path) -> bool:
    if not json_path.is_file() or json_path.stat().st_size == 0:
        return False
    try:
        data = json.loads(json_path.read_text())
        result = data.get(safe_id(c.seq_id)) or next(iter(data.values()))
        if not isinstance(result, dict):
            return False
        c.tnp = result
        return True
    except Exception:
        return False


def run_tnp(
    c: Candidate,
    out_dir: Path,
    ncores: int,
    gpu: Optional[str] = None,
) -> None:
    sid = safe_id(c.seq_id)
    tnp_dir = out_dir / 'layer3_tnp' / sid
    json_path = tnp_dir / f'TNP_Results_SingleSeqEntry_{sid}.json'
    if load_existing_tnp(c, json_path):
        return
    single_thread_env = {
        'OMP_NUM_THREADS': '1',
        'MKL_NUM_THREADS': '1',
        'OPENBLAS_NUM_THREADS': '1',
        'NUMEXPR_NUM_THREADS': '1',
        'TORCH_NUM_THREADS': '1',
    }
    if gpu is not None:
        single_thread_env['CUDA_VISIBLE_DEVICES'] = gpu
    ok = run_cmd(
        [
            str(BIN / 'TNP'),
            '--seq',
            c.sequence,
            '--name',
            sid,
            '--output',
            str(tnp_dir),
            '--ncores',
            str(ncores),
        ],
        out_dir / 'logs' / f'tnp_{sid}.log',
        env=single_thread_env,
    )
    if not ok:
        c.tnp = {'error': f'TNP failed; see {out_dir / "logs" / f"tnp_{sid}.log"}'}
        return
    if not json_path.exists():
        c.tnp = {'error': f'TNP JSON missing: {json_path}'}
        return
    try:
        data = json.loads(json_path.read_text())
        c.tnp = data.get(sid) or next(iter(data.values()))
    except Exception as exc:
        c.tnp = {'error': f'cannot parse TNP JSON: {exc}'}


def run_structure_tools(c: Candidate, out_dir: Path, tools: List[str], gpu: str, nbb_threads: int, igfold_models: int) -> None:
    sid = safe_id(c.seq_id)
    seq_fasta = out_dir / 'structures' / sid / f'{sid}.fasta'
    seq_fasta.parent.mkdir(parents=True, exist_ok=True)
    seq_fasta.write_text(f'>{sid}\n{c.sequence}\n')
    model_paths: Dict[str, str] = {}
    env = {'CUDA_VISIBLE_DEVICES': gpu, 'PATH': f'{BOLTZ_BIN}:{os.environ.get("PATH", "")}' }

    if 'igfold' in tools:
        pdb = out_dir / 'structures' / sid / 'igfold.pdb'
        ok = run_cmd([str(BIN / 'igfold-predict'), str(seq_fasta), '-o', str(pdb), '--models', str(igfold_models)], out_dir / 'logs' / f'structure_{sid}_igfold.log', env=env)
        if ok and pdb.exists():
            model_paths['igfold'] = str(pdb)
    if 'nanonet' in tools:
        nn_dir = out_dir / 'structures' / sid / 'nanonet'
        ok = run_cmd([str(BIN / 'nanonet-predict'), str(seq_fasta), '-o', str(nn_dir)], out_dir / 'logs' / f'structure_{sid}_nanonet.log', env=env)
        pdb = nn_dir / f'{sid}_nanonet_backbone_cb.pdb'
        if ok and pdb.exists():
            model_paths['nanonet'] = str(pdb)
    if 'nanobodybuilder2' in tools or 'abodybuilder2' in tools:
        pdb = out_dir / 'structures' / sid / 'nanobodybuilder2.pdb'
        ok = run_cmd([str(BOLTZ_BIN / 'NanoBodyBuilder2'), '-H', c.sequence, '-o', str(pdb), '--n_threads', str(nbb_threads)], out_dir / 'logs' / f'structure_{sid}_nanobodybuilder2.log', env=env)
        if ok and pdb.exists():
            model_paths['nanobodybuilder2'] = str(pdb)

    c.structure['model_paths'] = model_paths


def layer4_structure(c: Candidate, requested_tools: List[str]) -> str:
    if not requested_tools:
        c.layer_status['L4'] = 'NOT_RUN'
        add_reason(c, 'L4', 'INFO', 'structure_modeling_not_requested')
        return 'NOT_RUN'

    fail = False
    warn = False
    model_paths = c.structure.get('model_paths') or {}
    if not model_paths:
        fail = True
        add_reason(c, 'L4', 'FAIL', 'no_structure_models_generated')
    coords_by_tool: Dict[str, List[Optional[np.ndarray]]] = {}
    for tool, path in model_paths.items():
        coords = parse_ca_coords(Path(path))
        coords_by_tool[tool] = coords
        coverage = len(coords) / max(1, len(c.sequence))
        c.structure[f'{tool}_ca_count'] = len(coords)
        c.structure[f'{tool}_coverage'] = round(coverage, 3)
        if coverage < 0.90:
            fail = True
            add_reason(c, 'L4', 'FAIL', f'{tool}_coverage_low={coverage:.2f}')
        elif coverage < 0.97:
            warn = True
            add_reason(c, 'L4', 'WARN', f'{tool}_coverage_borderline={coverage:.2f}')

    regs = region_indices(c)
    fr_idx = regs.get('fr1', []) + regs.get('fr2', []) + regs.get('fr3', []) + regs.get('fr4', [])
    cdr3_idx = regs.get('cdr3', [])
    rmsd_values = {}
    for a, b in combinations(sorted(coords_by_tool), 2):
        rmsd = rmsd_for_indices(coords_by_tool[a], coords_by_tool[b], fr_idx)
        if rmsd is None:
            warn = True
            add_reason(c, 'L4', 'WARN', f'fr_rmsd_{a}_vs_{b}=NA')
            continue
        key = f'fr_rmsd_{a}_vs_{b}'
        rmsd_values[key] = round(rmsd, 3)
        if {'igfold', 'nanobodybuilder2'} == {a, b} and rmsd > 4.0:
            fail = True
            add_reason(c, 'L4', 'FAIL', f'{key}_high={rmsd:.2f}A')
        elif rmsd > 5.0:
            warn = True
            add_reason(c, 'L4', 'WARN', f'{key}_high_cross_tool={rmsd:.2f}A')
        elif rmsd > 3.0:
            warn = True
            add_reason(c, 'L4', 'WARN', f'{key}_borderline={rmsd:.2f}A')
    c.structure.update(rmsd_values)

    # Target-specific orientation and graft stability need a parent scaffold or antigen complex.
    if cdr3_idx and coords_by_tool:
        first_tool = sorted(coords_by_tool)[0]
        coords = coords_by_tool[first_tool]
        anchors = [idx for idx in (cdr3_idx[0], cdr3_idx[-1]) if idx < len(coords)]
        if len(anchors) == 2:
            dist = float(np.linalg.norm(coords[anchors[0]] - coords[anchors[1]]))
            c.structure['cdr3_anchor_ca_distance'] = round(dist, 3)
    c.structure['multi_seed_fr_consistency'] = 'not_assessed_cross_tool_only'
    c.structure['cdr_graft_fold_impact'] = 'not_assessed_requires_parent_scaffold'
    c.structure['cdr3_exit_epitope_fit'] = 'not_assessed_requires_antigen_or_complex_model'
    c.structure['alphafold_status'] = 'not_deployed_in_vhh_screen'
    c.structure['rosettaantibody_status'] = 'not_deployed_in_vhh_screen'
    c.structure['abodybuilder_status'] = 'NanoBodyBuilder2/ImmuneBuilder used if requested'

    status = 'FAIL' if fail else ('WARN' if warn else 'PASS')
    c.layer_status['L4'] = status
    return status


def final_verdict(c: Candidate) -> str:
    if c.layer_status.get('L1') == 'FAIL':
        return 'REJECT_NUMBERING_OR_FRAMEWORK'
    if c.layer_status.get('L2') == 'FAIL':
        return 'REJECT_NOT_VHH_LIKE'
    if c.layer_status.get('L3') == 'FAIL':
        return 'DEPRIORITIZE_DEVELOPABILITY'
    if c.layer_status.get('L4') == 'FAIL':
        return 'DEPRIORITIZE_STRUCTURE'
    if any(v == 'WARN' for v in c.layer_status.values()):
        return 'REVIEW'
    return 'PASS'


def collect_summary(c: Candidate) -> Dict[str, object]:
    row = c.vhh_eval
    flags = tnp_flags(c)
    return {
        'id': c.seq_id,
        'final_verdict': final_verdict(c),
        'L1_numbering_integrity': c.layer_status.get('L1', 'NA'),
        'L2_vhh_features': c.layer_status.get('L2', 'NA'),
        'L3_developability': c.layer_status.get('L3', 'NA'),
        'L4_structure_stability': c.layer_status.get('L4', 'NA'),
        'length': row.get('length', ''),
        'imgt_ok': row.get('imgt_ok', ''),
        'kabat_ok': row.get('kabat_ok', ''),
        'imgt_chain_type': row.get('imgt_chain_type', ''),
        'imgt_cdr1_len': len(row.get('imgt_cdr1', '')),
        'imgt_cdr2_len': len(row.get('imgt_cdr2', '')),
        'imgt_cdr3_len': len(row.get('imgt_cdr3', '')),
        'conserved_cys_imgt_H23_H104': f'{numbered_aa(c, "imgt", "H23") or "NA"}/{numbered_aa(c, "imgt", "H104") or "NA"}',
        'fr4': row.get('imgt_fr4', ''),
        'fr2_hallmark_score': row.get('fr2_hallmark_score', ''),
        'fr2_hallmark_residues': row.get('fr2_hallmark_residues', ''),
        'fr2_interface_residues': c.structure.get('fr2_interface_residues', ''),
        'fr2_interface_hydrophobic_count': c.structure.get('fr2_interface_hydrophobic_count', ''),
        'single_domain_suitability': c.structure.get('single_domain_suitability', ''),
        'abnativ_vhh_score': c.abnativ.get('AbNatiV VHH Score', ''),
        'abnativ_fr_vhh_score': c.abnativ.get('AbNatiV FR-VHH Score', ''),
        'sapiens_mean_self_probability': c.sapiens.get('mean_self_probability', ''),
        'sapiens_num_suggested_mutations': c.sapiens.get('num_suggested_mutations', ''),
        'mw': row.get('mw', ''),
        'pI': row.get('pI', ''),
        'gravy': row.get('gravy', ''),
        'charge_pH7_4': row.get('charge_pH7_4', ''),
        'nglyc_motif_count': row.get('nglyc_motif_count', ''),
        'nglyc_motif_hits': row.get('nglyc_motif_hits', ''),
        'cys_count': row.get('cys_count', ''),
        'deamidation_NG_NS_NT_count': row.get('deamidation_NG_NS_NT_count', ''),
        'isomerization_DG_DS_DD_DT_count': row.get('isomerization_DG_DS_DD_DT_count', ''),
        'acid_cleavage_DP_count': row.get('acid_cleavage_DP_count', ''),
        'hydrophobic_5_count': row.get('hydrophobic_5_count', ''),
        'polyreactivity_proxy': c.structure.get('polyreactivity_proxy', ''),
        'tnp_L_flag': flags.get('L', ''),
        'tnp_L3_flag': flags.get('L3', ''),
        'tnp_C_flag': flags.get('C', ''),
        'tnp_PSH_flag': flags.get('PSH', ''),
        'tnp_PPC_flag': flags.get('PPC', ''),
        'tnp_PNC_flag': flags.get('PNC', ''),
        'tnp_PSH': c.tnp.get('PSH', '') if isinstance(c.tnp, dict) else '',
        'tnp_PPC': c.tnp.get('PPC', '') if isinstance(c.tnp, dict) else '',
        'tnp_PNC': c.tnp.get('PNC', '') if isinstance(c.tnp, dict) else '',
        'igfold_coverage': c.structure.get('igfold_coverage', ''),
        'nanonet_coverage': c.structure.get('nanonet_coverage', ''),
        'nanobodybuilder2_coverage': c.structure.get('nanobodybuilder2_coverage', ''),
        'fr_rmsd_igfold_vs_nanobodybuilder2': c.structure.get('fr_rmsd_igfold_vs_nanobodybuilder2', ''),
        'fr_rmsd_igfold_vs_nanonet': c.structure.get('fr_rmsd_igfold_vs_nanonet', ''),
        'fr_rmsd_nanobodybuilder2_vs_nanonet': c.structure.get('fr_rmsd_nanobodybuilder2_vs_nanonet', ''),
        'cdr3_anchor_ca_distance': c.structure.get('cdr3_anchor_ca_distance', ''),
        'L1_reasons': ';'.join(c.layer_reasons['L1']),
        'L2_reasons': ';'.join(c.layer_reasons['L2']),
        'L3_reasons': ';'.join(c.layer_reasons['L3']),
        'L4_reasons': ';'.join(c.layer_reasons['L4']),
    }


def write_summary(candidates: Dict[str, Candidate], out_dir: Path) -> None:
    rows = [collect_summary(c) for c in candidates.values()]
    fields: List[str] = []
    seen = set()
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k); fields.append(k)
    with (out_dir / 'screen_summary.tsv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter='\t')
        writer.writeheader(); writer.writerows(rows)
    details = {
        'schema': {
            'L1': 'Numbering and framework integrity hard gate',
            'L2': 'VHH hallmark and single-domain suitability gate',
            'L3': 'Developability risk using TNP, ProtParam, liability motifs',
            'L4': 'Optional structure model completeness and cross-tool FR RMSD',
        },
        'candidates': [
            {
                'id': c.seq_id,
                'sequence': c.sequence,
                'summary': collect_summary(c),
                'vhh_eval': c.vhh_eval,
                'numbering': c.numbering,
                'sapiens': c.sapiens,
                'abnativ': c.abnativ,
                'tnp': c.tnp,
                'structure': c.structure,
                'layer_reasons': c.layer_reasons,
            }
            for c in candidates.values()
        ],
    }
    (out_dir / 'screen_details.json').write_text(json.dumps(details, indent=2, sort_keys=True), encoding='utf-8')

    counts: Dict[str, int] = {}
    for c in candidates.values():
        counts[final_verdict(c)] = counts.get(final_verdict(c), 0) + 1
    lines = [
        '# VHH Screening Report', '',
        f'- Input candidates: {len(candidates)}',
        '- Verdict counts: ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())),
        '- Summary TSV: `screen_summary.tsv`',
        '- Details JSON: `screen_details.json`', '',
        '## Layer Rules', '',
        '- L1 is a hard gate: AbNumber/ANARCI IMGT+Kabat heavy-chain numbering, FR/CDR boundaries, conserved IMGT Cys H23/H104, FR4 motif, CDR length sanity.',
        '- L2 is VHH-like gate: Kabat FR2 hallmarks, hydrophilic H44/H45 substitutions, reduced VH/VL-interface hydrophobicity, AbNatiV VHH score when available.',
        '- L3 is developability: TNP flags, pI/charge, N-glyc motif, Cys pairing, deamidation/isomerization/clipping motifs, hydrophobic runs, polyreactivity proxy.',
        '- L4 is optional structure stability: model coverage and cross-tool FR C-alpha RMSD; CDR graft and target epitope fit need scaffold/antigen context.', '',
        '## Top Rows', '',
    ]
    for row in rows[:20]:
        lines.append(f"- `{row['id']}`: {row['final_verdict']} | L1={row['L1_numbering_integrity']} L2={row['L2_vhh_features']} L3={row['L3_developability']} L4={row['L4_structure_stability']}")
    (out_dir / 'screen_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> int:
    ap = argparse.ArgumentParser(description='Run four-layer VHH/nanobody screening on node1')
    ap.add_argument('fasta', help='Input VHH FASTA')
    ap.add_argument('-o', '--out-dir', default='vhh_screen_out', help='Output directory')
    ap.add_argument('--prefix', default=None, help='Output prefix for intermediate files')
    ap.add_argument('--skip-abnativ', action='store_true', help='Do not run AbNatiV VHH scoring')
    ap.add_argument('--skip-sapiens', action='store_true', help='Do not run Sapiens human-likeness scoring')
    ap.add_argument('--skip-tnp', action='store_true', help='Do not run TNP developability scoring')
    ap.add_argument('--tnp-ncores', type=int, default=1)
    ap.add_argument(
        '--tnp-workers',
        type=int,
        default=1,
        help='Number of independent candidate-level TNP workers; completed JSON results are reused.',
    )
    ap.add_argument(
        '--tnp-gpus',
        default='',
        help='Comma-separated physical GPU IDs assigned round-robin to TNP workers.',
    )
    ap.add_argument('--abnativ-ncpu', type=int, default=1)
    ap.add_argument('--structure-tools', default='', help='Comma-separated optional tools: igfold,nanonet,nanobodybuilder2')
    ap.add_argument('--max-structures', type=int, default=0, help='Max candidates to structure-model; 0 means all eligible if structure tools requested')
    ap.add_argument('--gpu', default='0')
    ap.add_argument('--nbb-threads', type=int, default=4)
    ap.add_argument('--igfold-models', type=int, default=1)
    args = ap.parse_args()

    fasta = Path(args.fasta).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix or fasta.stem
    candidates = read_candidates(fasta)

    vhh_tsv = out_dir / f'{prefix}.vhh_eval.tsv'
    vhh_json = out_dir / f'{prefix}.numbering.json'
    ok = run_cmd([str(BIN / 'vhh-eval'), str(fasta), '-o', str(vhh_tsv), '--json', str(vhh_json)], out_dir / 'logs' / 'vhh_eval.log')
    if not ok:
        raise SystemExit(f'vhh-eval failed; see {out_dir / "logs" / "vhh_eval.log"}')
    vhh_rows = read_tsv(vhh_tsv)
    numbering_rows = {r['id']: r['numbering'] for r in json.loads(vhh_json.read_text())}
    for sid, c in candidates.items():
        c.vhh_eval = vhh_rows.get(sid, {})
        c.numbering = numbering_rows.get(sid, {})
        layer1_numbering_integrity(c)

    layer1_pass = [c for c in candidates.values() if c.layer_status.get('L1') != 'FAIL']
    layer1_fasta = out_dir / f'{prefix}.layer1_pass.fasta'
    write_fasta(layer1_pass, layer1_fasta)

    if layer1_pass and not args.skip_abnativ:
        ab_dir = out_dir / 'layer2_abnativ'
        ab_prefix = f'{prefix}_abnativ'
        ok = run_cmd([str(BIN / 'abnativ'), 'score', '-nat', 'VHH', '-mean', '-i', str(layer1_fasta), '-odir', str(ab_dir), '-oid', ab_prefix, '-align', '-isVHH', '-ncpu', str(args.abnativ_ncpu)], out_dir / 'logs' / 'abnativ.log')
        ab_csv = ab_dir / f'{ab_prefix}_abnativ_seq_scores.csv'
        ab_rows = read_csv_by_id(ab_csv)
        for c in layer1_pass:
            c.abnativ = ab_rows.get(c.seq_id, {})
            if not ok and not c.abnativ:
                c.abnativ = {'error': f'AbNatiV failed; see {out_dir / "logs" / "abnativ.log"}'}
    if layer1_pass and not args.skip_sapiens:
        sap_csv = out_dir / f'{prefix}.sapiens.csv'
        ok = run_cmd([str(BIN / 'sapiens-score'), str(layer1_fasta), '-o', str(sap_csv), '--chain', 'H'], out_dir / 'logs' / 'sapiens.log')
        sap_rows = read_csv_by_id(sap_csv)
        for c in layer1_pass:
            c.sapiens = sap_rows.get(c.seq_id, {})
            if not ok and not c.sapiens:
                c.sapiens = {'error': f'Sapiens failed; see {out_dir / "logs" / "sapiens.log"}'}

    for c in candidates.values():
        if c.layer_status.get('L1') == 'FAIL':
            c.layer_status['L2'] = 'SKIPPED'
            c.layer_status['L3'] = 'SKIPPED'
            c.layer_status['L4'] = 'SKIPPED'
            add_reason(c, 'L2', 'INFO', 'skipped_after_L1_fail')
            add_reason(c, 'L3', 'INFO', 'skipped_after_L1_fail')
            add_reason(c, 'L4', 'INFO', 'skipped_after_L1_fail')
        else:
            layer2_vhh_features(c)

    layer12_pass = [c for c in candidates.values() if c.layer_status.get('L1') != 'FAIL' and c.layer_status.get('L2') != 'FAIL']
    if layer12_pass and not args.skip_tnp:
        workers = max(1, args.tnp_workers)
        tnp_gpus = [gpu.strip() for gpu in args.tnp_gpus.split(',') if gpu.strip()]
        if workers == 1:
            for index, c in enumerate(layer12_pass):
                gpu = tnp_gpus[index % len(tnp_gpus)] if tnp_gpus else None
                run_tnp(c, out_dir, args.tnp_ncores, gpu)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(
                        run_tnp,
                        c,
                        out_dir,
                        args.tnp_ncores,
                        tnp_gpus[index % len(tnp_gpus)] if tnp_gpus else None,
                    )
                    for index, c in enumerate(layer12_pass)
                ]
                for future in concurrent.futures.as_completed(futures):
                    future.result()

    for c in candidates.values():
        if c.layer_status.get('L3') == 'SKIPPED':
            continue
        if c.layer_status.get('L2') == 'FAIL':
            c.layer_status['L3'] = 'SKIPPED'
            c.layer_status['L4'] = 'SKIPPED'
            add_reason(c, 'L3', 'INFO', 'skipped_after_L2_fail')
            add_reason(c, 'L4', 'INFO', 'skipped_after_L2_fail')
        else:
            layer3_developability(c)

    requested_tools = [t.strip().lower() for t in args.structure_tools.split(',') if t.strip()]
    eligible_struct = [c for c in candidates.values() if c.layer_status.get('L1') != 'FAIL' and c.layer_status.get('L2') != 'FAIL' and c.layer_status.get('L3') != 'FAIL']
    if requested_tools:
        limit = args.max_structures or len(eligible_struct)
        for c in eligible_struct[:limit]:
            run_structure_tools(c, out_dir, requested_tools, args.gpu, args.nbb_threads, args.igfold_models)
            layer4_structure(c, requested_tools)
        for c in eligible_struct[limit:]:
            c.layer_status['L4'] = 'SKIPPED'
            add_reason(c, 'L4', 'INFO', f'structure_skipped_by_max_structures={args.max_structures}')
    for c in candidates.values():
        if 'L4' not in c.layer_status:
            if c.layer_status.get('L3') == 'FAIL':
                c.layer_status['L4'] = 'SKIPPED'
                add_reason(c, 'L4', 'INFO', 'skipped_after_L3_fail')
            else:
                layer4_structure(c, requested_tools)

    write_summary(candidates, out_dir)
    print(f'wrote {out_dir / "screen_summary.tsv"}')
    print(f'wrote {out_dir / "screen_details.json"}')
    print(f'wrote {out_dir / "screen_report.md"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

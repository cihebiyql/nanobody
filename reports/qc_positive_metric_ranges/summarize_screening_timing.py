#!/usr/bin/env python3
"""Summarize observed runtime for the current PVRIG VHH screening workflow."""
from __future__ import annotations

import csv
import re
import statistics
from datetime import date
from pathlib import Path

ROOT = Path('/mnt/d/work/抗体')
OUT_DIR = ROOT / 'reports' / 'qc_positive_metric_ranges'
QC_DIR = OUT_DIR / 'node1_pvrig_11_positive_qc'
MUT_ROOT = ROOT / 'docking' / 'calibration' / 'mutant_validation_panel' / 'workdirs'


def read_stage_timings() -> dict[str, float]:
    path = QC_DIR / 'stage_timings.tsv'
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return {row['stage']: float(row['elapsed_seconds']) for row in csv.DictReader(handle, delimiter='\t')}


def parse_wall(stderr_path: Path) -> float | None:
    if not stderr_path.exists():
        return None
    text = stderr_path.read_text(encoding='utf-8', errors='replace')
    matches = re.findall(r'WALL_SECONDS=([0-9.]+)', text)
    return float(matches[-1]) if matches else None


def parse_haddock_duration(text: str) -> float | None:
    for line in reversed(text.splitlines()):
        if 'This HADDOCK3 run took:' not in line:
            continue
        after = line.split('took:', 1)[1]
        minutes = 0
        seconds = 0
        m = re.search(r'(\d+)\s+minutes?', after)
        if m:
            minutes = int(m.group(1))
        s = re.search(r'(\d+)\s+seconds?', after)
        if s:
            seconds = int(s.group(1))
        return float(minutes * 60 + seconds)
    return None


def haddock_stats() -> tuple[list[float], list[tuple[str, float]]]:
    vals: list[tuple[str, float]] = []
    for path in MUT_ROOT.rglob('reports/stage_logs/haddock3.log'):
        duration = parse_haddock_duration(path.read_text(encoding='utf-8', errors='replace'))
        if duration is not None:
            vals.append((str(path), duration))
    return [v for _, v in vals], vals


def structure_estimate_from_file_mtimes() -> list[float]:
    # Structure stage was sequential in this runner. Adjacent normalized-PDB mtimes
    # approximate per-row cadence, excluding long pauses/out-of-order reruns.
    records: list[tuple[float, str]] = []
    for wd in MUT_ROOT.glob('mut_*'):
        name = wd.name
        pdb = wd / 'haddock3' / 'data' / f'{name}_vhh_chainA.pdb'
        if pdb.exists():
            records.append((pdb.stat().st_mtime, name))
    records.sort()
    deltas: list[float] = []
    for (prev_t, _), (cur_t, _) in zip(records, records[1:]):
        delta = cur_t - prev_t
        if 5 <= delta <= 180:
            deltas.append(delta)
    return deltas


def fmt_seconds(value: float | None) -> str:
    if value is None:
        return ''
    if value < 60:
        return f'{value:.1f}s'
    return f'{value / 60:.2f}min'


def stat_line(vals: list[float]) -> dict[str, str]:
    if not vals:
        return {'n': '0', 'min_s': '', 'median_s': '', 'mean_s': '', 'max_s': ''}
    return {
        'n': str(len(vals)),
        'min_s': f'{min(vals):.1f}',
        'median_s': f'{statistics.median(vals):.1f}',
        'mean_s': f'{statistics.mean(vals):.1f}',
        'max_s': f'{max(vals):.1f}',
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stage = read_stage_timings()
    bench_base = '/data/qlyu/software/vhh_eval_tools/runs/pvrig_11_positive_qc_20260708/timing_bench_vhh_screen'
    local_bench = OUT_DIR / 'timing_bench_vhh_screen'
    # If the remote bench has not been copied locally, the caller can still rely
    # on explicit values written below from the current run.
    bench_values = {
        'l1_basic': parse_wall(local_bench / 'l1_basic.stderr'),
        'abnativ_only': parse_wall(local_bench / 'abnativ_only.stderr'),
        'sapiens_only': parse_wall(local_bench / 'sapiens_only.stderr'),
        'tnp_only': parse_wall(local_bench / 'tnp_only.stderr'),
        'full': parse_wall(local_bench / 'full.stderr'),
    }
    observed_fallback = {
        'l1_basic': 2.66,
        'abnativ_only': 35.30,
        'sapiens_only': 23.92,
        'tnp_only': 114.31,
        'full': 187.57,
    }
    bench = {k: bench_values[k] if bench_values[k] is not None else observed_fallback[k] for k in observed_fallback}
    l1 = bench['l1_basic']
    incr_abnativ = bench['abnativ_only'] - l1
    incr_sapiens = bench['sapiens_only'] - l1
    incr_tnp = bench['tnp_only'] - l1
    full_overhead = bench['full'] - (l1 + incr_abnativ + incr_sapiens + incr_tnp)
    haddock_values, haddock_rows = haddock_stats()
    structure_deltas = structure_estimate_from_file_mtimes()
    postprocess_one = 20.46

    rows = [
        {'stage_or_metric': 'parse/write input', 'basis': 'stage_timings.tsv, 11 sequences', 'n': '11', 'observed_total_s': f"{stage.get('parse_fasta', 0)+stage.get('write_normalized_fasta', 0)+stage.get('write_official_xlsx', 0):.3f}", 'per_sequence_s': '<0.01', 'confidence': 'high', 'notes': 'FASTA parsing and small file writes are negligible.'},
        {'stage_or_metric': 'official ab-data-validator / positive CDR identity', 'basis': 'stage_timings.tsv, 11 sequences', 'n': '11', 'observed_total_s': f"{stage.get('official_validator', 0):.3f}", 'per_sequence_s': f"{stage.get('official_validator', 0)/11:.2f}", 'confidence': 'high', 'notes': 'Includes official validator setup and 48 built-in positive references.'},
        {'stage_or_metric': 'vhh-screen L1 + basic physicochemical/liability scan', 'basis': 'skip-abnativ/skip-sapiens/skip-tnp benchmark, 11 sequences', 'n': '11', 'observed_total_s': f"{l1:.2f}", 'per_sequence_s': f"{l1/11:.2f}", 'confidence': 'high', 'notes': 'Numbering, CDR extraction, length, pI/charge/GRAVY, simple liabilities.'},
        {'stage_or_metric': 'AbNatiV VHH scoring incremental', 'basis': 'abnativ_only - l1_basic benchmark', 'n': '11', 'observed_total_s': f"{incr_abnativ:.2f}", 'per_sequence_s': f"{incr_abnativ/11:.2f}", 'confidence': 'medium-high', 'notes': 'Wrapper/model overhead included; 9/11 produced scores in this positive set.'},
        {'stage_or_metric': 'Sapiens human-likeness incremental', 'basis': 'sapiens_only - l1_basic benchmark', 'n': '11', 'observed_total_s': f"{incr_sapiens:.2f}", 'per_sequence_s': f"{incr_sapiens/11:.2f}", 'confidence': 'medium-high', 'notes': 'Human-likeness and suggested mutation scoring.'},
        {'stage_or_metric': 'TNP developability incremental through vhh-screen', 'basis': 'tnp_only - l1_basic benchmark', 'n': '11', 'observed_total_s': f"{incr_tnp:.2f}", 'per_sequence_s': f"{incr_tnp/11:.2f}", 'confidence': 'medium-high', 'notes': 'TNP wrapper/model overhead; direct standalone batch was faster in one observed run.'},
        {'stage_or_metric': 'vhh-screen full', 'basis': 'full benchmark, 11 sequences', 'n': '11', 'observed_total_s': f"{bench['full']:.2f}", 'per_sequence_s': f"{bench['full']/11:.2f}", 'confidence': 'high', 'notes': f"Full run includes ~{full_overhead:.1f}s residual wrapper/interaction overhead in this split benchmark."},
        {'stage_or_metric': 'local positive CDR novelty', 'basis': 'stage_timings.tsv, 11 sequences vs local positive CDRs', 'n': '11', 'observed_total_s': f"{stage.get('positive_cdr_novelty', 0):.3f}", 'per_sequence_s': f"{stage.get('positive_cdr_novelty', 0)/11:.2f}", 'confidence': 'high', 'notes': 'Local CDR novelty/leakage check.'},
        {'stage_or_metric': 'team diversity clustering', 'basis': 'stage_timings.tsv, 11 sequences', 'n': '11', 'observed_total_s': f"{stage.get('team_diversity', 0):.3f}", 'per_sequence_s': f"{stage.get('team_diversity', 0)/11:.2f}", 'confidence': 'high', 'notes': 'Pairwise team identity and cluster scoring.'},
        {'stage_or_metric': 'portfolio merge/ranking/report writes', 'basis': 'stage_timings.tsv, 11 sequences', 'n': '11', 'observed_total_s': f"{sum(v for k, v in stage.items() if k in {'merge_vhh_eval','load_official_positive_cdrs','load_local_positive_cdrs','load_docking_summary','build_portfolio','write_cdr_novelty','write_team_diversity','write_portfolio_ranked','select_portfolio','write_submission_fasta','write_reserve_fasta','write_submission_xlsx','write_report','write_details'}):.3f}", 'per_sequence_s': '<0.01', 'confidence': 'high', 'notes': 'Negligible for this batch size.'},
        {'stage_or_metric': 'NanoBodyBuilder2 monomer structure prediction', 'basis': 'mutant-panel sequential normalized-PDB mtime cadence, 34 usable deltas', 'n': str(len(structure_deltas)), 'observed_total_s': '', 'per_sequence_s': f"median {statistics.median(structure_deltas):.1f}; mean {statistics.mean(structure_deltas):.1f}; range {min(structure_deltas):.1f}-{max(structure_deltas):.1f}", 'confidence': 'medium', 'notes': 'No unified timer in logs; cadence includes ssh/copy/normalization. Long pauses excluded.'},
        {'stage_or_metric': 'HADDOCK3 docking', 'basis': 'HADDOCK3 final log duration, mutant panel', 'n': str(len(haddock_values)), 'observed_total_s': '', 'per_sequence_s': f"median {statistics.median(haddock_values):.1f}; mean {statistics.mean(haddock_values):.1f}; range {min(haddock_values):.1f}-{max(haddock_values):.1f}", 'confidence': 'high', 'notes': 'Current cfg around 40 rigidbody jobs, 10 flexref/emref, 8 cores.'},
        {'stage_or_metric': '8X6B + 9E6Y scoring/classification/postprocess', 'basis': 'timed rerun on /tmp copy for one completed workdir', 'n': '1', 'observed_total_s': f"{postprocess_one:.2f}", 'per_sequence_s': f"{postprocess_one:.2f}", 'confidence': 'medium', 'notes': 'Local CPU postprocess of 10 models; varies with number of top models.'},
    ]

    csv_path = OUT_DIR / 'pvrig_screening_runtime_estimates.csv'
    with csv_path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    md = OUT_DIR / 'PVRIG_SCREENING_RUNTIME_ESTIMATE.md'
    lines = []
    lines.append('# PVRIG VHH screening runtime estimate')
    lines.append('')
    lines.append(f'Updated: {date.today().isoformat()}')
    lines.append('')
    lines.append('## Bottom line')
    lines.append('')
    lines.append('- Sequence-only QC for 11 VHHs is about 3-4 minutes end-to-end on node1 with the current full settings.')
    lines.append('- The slow sequence-QC item is TNP through `vhh-screen`; L1/basic checks are seconds, AbNatiV and Sapiens are tens of seconds per 11 sequences.')
    lines.append('- Structure+docking dominates if blocker geometry is required: current single-candidate path is roughly 4-6 minutes per sequence, mostly HADDOCK3.')
    lines.append('- For batch mode, structure prediction is kept sequential by the runner, while docking/postprocess can be parallelized with `--jobs`; wall time depends heavily on queue/GPU/CPU contention.')
    lines.append('')
    lines.append('## Observed timing table')
    lines.append('')
    lines.append('| Stage / metric | Basis | n | Total | Per sequence / distribution | Confidence | Notes |')
    lines.append('| --- | --- | ---: | ---: | --- | --- | --- |')
    for row in rows:
        total = fmt_seconds(float(row['observed_total_s'])) if row['observed_total_s'] else ''
        per = row['per_sequence_s']
        if re.fullmatch(r'[0-9.]+', per):
            per = fmt_seconds(float(per))
        lines.append(f"| {row['stage_or_metric']} | {row['basis']} | {row['n']} | {total} | {per} | {row['confidence']} | {row['notes']} |")
    lines.append('')
    lines.append('## Practical estimates')
    lines.append('')
    lines.append('- Fast prefilter without TNP/structure: about 1 minute for 11 sequences, dominated by official validator and local novelty checks.')
    lines.append('- Full sequence QC with AbNatiV + Sapiens + TNP: about 3.1 minutes for 11 sequences in the split benchmark; prior integrated competition QC measured `vhh_screen=176.168s` plus validator/novelty/diversity for ~225s total.')
    lines.append('- Full blocker workflow for one sequence after QC: NanoBodyBuilder2 structure ~0.4-1.0 min typical cadence, HADDOCK3 ~2.4-4.1 min observed, postprocess ~0.3 min; plan ~4-6 min per sequence including ssh/copy overhead.')
    lines.append('- Full blocker workflow for 36 sequences with `--jobs 4` docking is not simply 36x single time; docking CPU parallelism and node load are the limiting factors.')
    lines.append('')
    lines.append('## Evidence files')
    lines.append('')
    lines.append('- `reports/qc_positive_metric_ranges/node1_pvrig_11_positive_qc/stage_timings.tsv`')
    lines.append('- remote benchmark directory: `/data/qlyu/software/vhh_eval_tools/runs/pvrig_11_positive_qc_20260708/timing_bench_vhh_screen`')
    lines.append('- `docking/calibration/mutant_validation_panel/workdirs/*/reports/stage_logs/haddock3.log`')
    lines.append('- temp postprocess timing rerun: `/tmp/pvrig_postprocess_timing.out` and `/tmp/pvrig_postprocess_timing.err` during this run')
    md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(csv_path)
    print(md)


if __name__ == '__main__':
    main()

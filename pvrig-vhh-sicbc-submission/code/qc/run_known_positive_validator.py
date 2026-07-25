#!/usr/bin/env python3
"""Generate official validator input and update known-positive CDR evidence.

Requires the local environment created from the official validator instructions:
  .conda-envs/ab-data-validator/bin/ANARCI
  .conda-envs/ab-data-validator/bin/muscle
and the cloned validator source at tools/ab-data-validator.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_SRC = ROOT / 'tools' / 'ab-data-validator' / 'src'
ENV_BIN = ROOT / '.conda-envs' / 'ab-data-validator' / 'bin'
PYTHON = ENV_BIN / 'python'
ANARCI = ENV_BIN / 'ANARCI'
MUSCLE = ENV_BIN / 'muscle'


def col_name(n: int) -> str:
    s = ''
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def xml_escape(value: str) -> str:
    return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def write_xlsx(rows: list[list[str]], output: Path) -> None:
    xml_rows = []
    for row_idx, row in enumerate(rows, 1):
        cells = []
        for col_idx, value in enumerate(row, 1):
            if not value:
                continue
            ref = f'{col_name(col_idx)}{row_idx}'
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{xml_escape(value)}</t></is></c>')
        xml_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')

    parts = {
        '[Content_Types].xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        '_rels/.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(xml_rows) + '</sheetData></worksheet>',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', ZIP_DEFLATED) as zf:
        for name, content in parts.items():
            zf.writestr(name, content)


def load_metadata() -> dict[str, dict[str, str]]:
    with (ROOT / 'positives' / 'positive_antibody_metadata.csv').open() as handle:
        return {row['record_id']: row for row in csv.DictReader(handle)}


def build_validator_input(output: Path) -> None:
    meta = load_metadata()
    rows = [
        ['idx', 'name', 'vh', 'vl', 'c5', 'c6', 'parent_vh', 'parent_vl'],
        ['', 'HR-151_VHH', meta['hr151_vhh']['heavy_variable_sequence'], '', '', '', '', ''],
        ['', 'Tab5_full_IgG', meta['tab5_vh']['heavy_variable_sequence'], meta['tab5_vl']['light_variable_sequence'], '', '', '', ''],
    ]
    write_xlsx(rows, output)


def run_validator(input_xlsx: Path, output_csv: Path) -> None:
    env = os.environ.copy()
    env['PATH'] = f'{ENV_BIN}:{env.get("PATH", "")}'
    env['PYTHONPATH'] = str(VALIDATOR_SRC)
    stdout = ROOT / 'reports' / 'validator' / 'known_positive_validator.stdout'
    stderr = ROOT / 'reports' / 'validator' / 'known_positive_validator.stderr'
    cmd = [
        str(PYTHON), '-m', 'ab_data_validator.cli', 'validate',
        '--input', str(input_xlsx.relative_to(ROOT)),
        '--output', str(output_csv.relative_to(ROOT)),
        '--anarci-bin', 'ANARCI',
        '--muscle-bin', 'muscle',
        '--workers', '1',
    ]
    result = subprocess.run(cmd, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout.write_text(result.stdout)
    stderr.write_text(result.stderr)
    if result.returncode != 0:
        raise SystemExit(f'validator failed with exit code {result.returncode}; see {stderr}')


def update_cdr_tables() -> None:
    sys.path.insert(0, str(VALIDATOR_SRC))
    from ab_data_validator.anarci_runner import run_anarci
    from ab_data_validator.cdr import extract_imgt_cdrs

    env_path = os.environ.get('PATH', '')
    os.environ['PATH'] = f'{ENV_BIN}:{env_path}'
    meta_rows = list(csv.DictReader((ROOT / 'positives' / 'positive_antibody_metadata.csv').open()))
    cdr_rows = []
    for row in meta_rows:
        if row['record_id'] == 'tab5_vl':
            chain, prefix, seq, keys = 'VL', 'L', row['light_variable_sequence'], ('CDRL1', 'CDRL2', 'CDRL3')
        elif row['format'] == 'VHH':
            chain, prefix, seq, keys = 'VHH', 'H', row['heavy_variable_sequence'], ('CDRH1', 'CDRH2', 'CDRH3')
        else:
            chain, prefix, seq, keys = 'VH', 'H', row['heavy_variable_sequence'], ('CDRH1', 'CDRH2', 'CDRH3')
        residues = run_anarci(seq, sequence_id=f'{row["record_id"]}_{chain}', anarci_bin='ANARCI')
        cdrs = extract_imgt_cdrs(residues, chain_prefix=prefix)
        c1, c2, c3 = [cdrs[key] for key in keys]
        cdr_rows.append({
            'record_id': row['record_id'],
            'name': row['name'],
            'chain': chain,
            'numbering_scheme': 'IMGT',
            'numbering_status': 'anarci_success',
            'cdr1': c1,
            'cdr2': c2,
            'cdr3': c3,
            'cdr1_len': len(c1),
            'cdr2_len': len(c2),
            'cdr3_len': len(c3),
            'source_id': row['source_id'],
            'sequence_status': row['sequence_status'],
            'notes': 'CDRs extracted with official ab-data-validator ANARCI wrapper using IMGT ranges 27-38, 56-65, 105-117.',
        })
        row['numbering_status'] = 'anarci_success'
        row['cdr_source'] = 'ab_data_validator_anarci_imgt'

    meta_fields = list(meta_rows[0].keys())
    with (ROOT / 'positives' / 'positive_antibody_metadata.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=meta_fields)
        writer.writeheader()
        writer.writerows(meta_rows)

    cdr_fields = ['record_id', 'name', 'chain', 'numbering_scheme', 'numbering_status', 'cdr1', 'cdr2', 'cdr3', 'cdr1_len', 'cdr2_len', 'cdr3_len', 'source_id', 'sequence_status', 'notes']
    with (ROOT / 'positives' / 'known_positive_CDR_table.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=cdr_fields)
        writer.writeheader()
        writer.writerows(cdr_rows)


def update_similarity_table(failure_csv: Path) -> None:
    with failure_csv.open() as handle:
        failures = list(csv.DictReader(handle))
    fields = ['query_id', 'reference_id', 'chain', 'cdr', 'numbering_scheme', 'alignment_tool', 'identity_pct', 'hamming_distance', 'threshold_pct', 'status', 'notes']
    with (ROOT / 'positives' / 'positive_CDR_similarity_exclusion_table.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in failures:
            identity = float(row['identity'])
            threshold = float(row['threshold'])
            writer.writerow({
                'query_id': row['name'],
                'reference_id': row['positive_name'],
                'chain': row['chain'],
                'cdr': row['cdr'],
                'numbering_scheme': 'IMGT',
                'alignment_tool': 'MUSCLE5 via ab-data-validator',
                'identity_pct': f'{identity * 100:.1f}',
                'hamming_distance': 'not_reported_by_validator',
                'threshold_pct': f'{threshold * 100:.1f}',
                'status': 'excluded_high_cdr_identity',
                'notes': row['details'],
            })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-validator', action='store_true', help='only regenerate input and CDR table; do not rerun validator')
    args = parser.parse_args()
    for required in [PYTHON, ANARCI, MUSCLE, VALIDATOR_SRC]:
        if not required.exists():
            raise SystemExit(f'missing required validator dependency: {required}')
    input_xlsx = ROOT / 'reports' / 'validator' / 'known_positive_submit.xlsx'
    failure_csv = ROOT / 'reports' / 'validator' / 'known_positive_failed_reasons.csv'
    build_validator_input(input_xlsx)
    if not args.skip_validator:
        run_validator(input_xlsx, failure_csv)
    update_cdr_tables()
    if failure_csv.exists():
        update_similarity_table(failure_csv)
    print('known-positive validator artifacts updated')


if __name__ == '__main__':
    main()

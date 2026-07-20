#!/usr/bin/env python3
import sys
from pathlib import Path
root=Path(sys.argv[1])

def clean(src,dst):
    out=[]; serial=1
    for line in src.read_text(errors='ignore').splitlines():
        if not line.startswith(('ATOM  ','HETATM')):continue
        atom=line[12:16].strip(); alt=(line[16:17] or ' ');res=line[17:20].strip();chain=(line[21:22].strip() or 'A')
        try:
            resseq=int(line[22:26]);icode=(line[26:27] or ' ');x=float(line[30:38]);y=float(line[38:46]);z=float(line[46:54]);occ=float(line[54:60] or 1);bf=float(line[60:66] or 0)
        except Exception as e:raise ValueError(f'{src}: {line!r}: {e}')
        letters=''.join(c for c in atom if c.isalpha()); element=(letters[0] if letters else 'C').upper()
        name_field=f'{atom:>4s}'
        out.append(f"ATOM  {serial:5d} {name_field}{alt:1s}{res:>3s} {chain:1s}{resseq:4d}{icode:1s}   {x:8.3f}{y:8.3f}{z:8.3f}{occ:6.2f}{bf:6.2f}          {element:>2s}  ")
        serial+=1
    out.append('END')
    dst.write_text('\n'.join(out)+'\n')
    return serial-1
for pair in sorted((root/'fixed_pose_ddg').iterdir()):
    if not pair.is_dir():continue
    for i in range(5):
        clean(pair/f'WT_wt_1_{i}.pdb',pair/f'graphinity_wt_rep{i}.pdb')
        clean(pair/f'wt_1_{i}.pdb',pair/f'graphinity_mut_rep{i}.pdb')
print('sanitized',len(list((root/'fixed_pose_ddg').glob('*/graphinity_*_rep*.pdb'))))

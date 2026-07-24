#!/usr/bin/env python3
"""Independent OpenMM/CHARMM36 CUDA minimization sentinel for HR-151."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import openmm
from openmm import LangevinMiddleIntegrator, Platform, unit
from openmm.app import (
    PME,
    ForceField,
    HBonds,
    Modeller,
    PDBFile,
    Simulation,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_heavy_atom_pdb_with_oxt(source: Path, destination: Path) -> None:
    """Remove legacy hydrogens and add missing C-terminal OXT atoms."""
    chains: dict[str, list[tuple[tuple[str, str, str], list[str]]]] = {}
    residue_maps: dict[str, dict[tuple[str, str, str], list[str]]] = {}
    chain_order: list[str] = []
    for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("ATOM  "):
            continue
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        if not element:
            element = "".join(ch for ch in line[12:16] if ch.isalpha())[:1].upper()
        if element in {"H", "D"}:
            continue
        chain = line[21]
        key = (line[22:26], line[26:27], line[17:20])
        if chain not in residue_maps:
            chain_order.append(chain)
            chains[chain] = []
            residue_maps[chain] = {}
        if key not in residue_maps[chain]:
            residue_maps[chain][key] = []
            chains[chain].append((key, residue_maps[chain][key]))
        residue_maps[chain][key].append(line)

    output: list[str] = []
    serial = 1
    for chain in chain_order:
        residues = chains[chain]
        for residue_index, (key, lines) in enumerate(residues):
            for line in lines:
                output.append(f"{line[:6]}{serial:5d}{line[11:]}")
                serial += 1
            is_terminal = residue_index == len(residues) - 1
            atom_names = {line[12:16].strip() for line in lines}
            if is_terminal and "OXT" not in atom_names:
                coords = {
                    line[12:16].strip(): tuple(float(line[i : i + 8]) for i in (30, 38, 46))
                    for line in lines
                    if line[12:16].strip() in {"C", "O", "CA"}
                }
                if set(coords) != {"C", "O", "CA"}:
                    raise RuntimeError(f"cannot construct OXT for chain {chain}: {sorted(coords)}")
                c, oxygen, ca = coords["C"], coords["O"], coords["CA"]

                def unit_vector(point: tuple[float, float, float]) -> tuple[float, float, float]:
                    vector = tuple(point[i] - c[i] for i in range(3))
                    norm = math.sqrt(sum(value * value for value in vector))
                    return tuple(value / norm for value in vector)

                u_o, u_ca = unit_vector(oxygen), unit_vector(ca)
                direction = tuple(-(u_o[i] + u_ca[i]) for i in range(3))
                norm = math.sqrt(sum(value * value for value in direction))
                direction = tuple(value / norm for value in direction)
                x, y, z = tuple(c[i] + 1.25 * direction[i] for i in range(3))
                resseq, icode, resname = key
                output.append(
                    f"ATOM  {serial:5d}  OXT {resname:>3s} {chain}{int(resseq):4d}{icode}"
                    f"   {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           O"
                )
                serial += 1
        output.append(f"TER   {serial:5d}")
        serial += 1
    output.append("END")
    destination.write_text("\n".join(output) + "\n", encoding="utf-8")


root = Path(
    os.environ.get(
        "PVRIG_CALIBRATION_ROOT",
        "/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724",
    )
)
job_id = "CONTROL_CTRL_PATENT_001_case02_pos_01_PVRIG-151_HR151_8x6b_s917_f8fab9ee3ba5"
input_pdb = root / "inputs/pdb" / f"{job_id}.pdb"
output_dir = root / "md/openmm_hr151_cuda_smoke"
output_dir.mkdir(parents=True, exist_ok=True)
complete = output_dir / "COMPLETE.json"
if complete.is_file():
    print(complete.read_text(encoding="utf-8"))
    raise SystemExit(0)
if not input_pdb.is_file():
    raise SystemExit(f"missing frozen input: {input_pdb}")

started = time.time()
sanitized_pdb = output_dir / "sanitized_heavy_atoms_with_oxt.pdb"
prepare_heavy_atom_pdb_with_oxt(input_pdb, sanitized_pdb)
pdb = PDBFile(str(sanitized_pdb))
forcefield = ForceField("charmm36.xml", "charmm36/water.xml")
modeller = Modeller(pdb.topology, pdb.positions)
modeller.addHydrogens(forcefield, pH=7.4)
modeller.addSolvent(
    forcefield,
    model="tip3p",
    padding=1.0 * unit.nanometer,
    ionicStrength=0.15 * unit.molar,
)
system = forcefield.createSystem(
    modeller.topology,
    nonbondedMethod=PME,
    nonbondedCutoff=1.2 * unit.nanometer,
    constraints=HBonds,
)
integrator = LangevinMiddleIntegrator(
    300 * unit.kelvin,
    1 / unit.picosecond,
    0.002 * unit.picoseconds,
)
platform_name = os.environ.get("OPENMM_PLATFORM", "CUDA")
platform = Platform.getPlatformByName(platform_name)
properties = {"DeviceIndex": os.environ.get("OPENMM_GPU_DEVICE", "0"), "Precision": "mixed"}
simulation = Simulation(modeller.topology, system, integrator, platform, properties)
simulation.context.setPositions(modeller.positions)
initial = simulation.context.getState(getEnergy=True)
simulation.minimizeEnergy(tolerance=10 * unit.kilojoule_per_mole / unit.nanometer, maxIterations=2000)
final = simulation.context.getState(getEnergy=True, getPositions=True)
with (output_dir / "minimized.pdb").open("w", encoding="utf-8") as handle:
    PDBFile.writeFile(modeller.topology, final.getPositions(), handle, keepIds=True)

receipt = {
    "state": "COMPLETE",
    "finished_at": datetime.now(timezone.utc).isoformat(),
    "job_id": job_id,
    "input_pdb": str(input_pdb),
    "input_sha256": sha256(input_pdb),
    "sanitized_input_sha256": sha256(sanitized_pdb),
    "openmm_version": openmm.__version__,
    "platform": platform.getName(),
    "platform_properties": properties,
    "force_fields": ["charmm36.xml", "charmm36/water.xml"],
    "water_model": "tip3p",
    "ionic_strength_molar": 0.15,
    "atom_count": modeller.topology.getNumAtoms(),
    "residue_count": modeller.topology.getNumResidues(),
    "initial_potential_kj_mol": initial.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole),
    "final_potential_kj_mol": final.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole),
    "elapsed_seconds": round(time.time() - started, 3),
    "output_pdb_sha256": sha256(output_dir / "minimized.pdb"),
}
complete.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps(receipt, indent=2))

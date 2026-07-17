#!/usr/bin/env python3
"""NanoBodyBuilder2 CLI with a narrow OpenMM Threads compatibility repair.

ImmuneBuilder 1.2.0 passes ``{'Threads', str(n_threads)}`` (a set) to one
strained-sidechain OpenMM Simulation path. Current OpenMM requires a mapping.
This wrapper converts only that exact malformed value to ``{'Threads': N}``
in memory and leaves the installed environment unchanged.
"""
from __future__ import annotations

from openmm import app


_original_init = app.Simulation.__init__


def _compatible_init(
    self,
    topology,
    system,
    integrator,
    platform=None,
    platformProperties=None,
    state=None,
):
    if isinstance(platformProperties, set) and "Threads" in platformProperties:
        values = [value for value in platformProperties if value != "Threads"]
        if len(values) != 1:
            raise TypeError(f"ambiguous OpenMM Threads property set: {platformProperties!r}")
        platformProperties = {"Threads": str(values[0])}
    return _original_init(
        self,
        topology,
        system,
        integrator,
        platform,
        platformProperties,
        state,
    )


app.Simulation.__init__ = _compatible_init

from ImmuneBuilder.NanoBodyBuilder2 import command_line_interface  # noqa: E402


if __name__ == "__main__":
    command_line_interface()

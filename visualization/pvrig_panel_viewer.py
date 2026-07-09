"""Panel wrapper for the PVRIG-PVRL2 py3Dmol HTML viewer.
Run with:
  panel serve visualization/pvrig_panel_viewer.py --show --port 5007
"""
from pathlib import Path

import panel as pn

pn.extension(sizing_mode='stretch_width')
ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / 'visualization' / 'pvrig_pvrl2_mechanism_view.html').read_text()
notes = (ROOT / 'reports' / 'pvrig_pvrl2_binding_mechanism_visual_notes.md').read_text()

pn.template.FastListTemplate(
    title='PVRIG-PVRL2 Mechanism Viewer',
    main=[
        pn.pane.Markdown('''## PVRIG-PVRL2 interface viewer\n\nUse PyMOL for the full curated scene; this Panel page is a quick browser fallback. R95 is magenta, I97 hot pink, S67 slate.'''),
        pn.pane.HTML(html, height=760, sizing_mode='stretch_both'),
        pn.pane.Markdown(notes),
    ],
).servable()

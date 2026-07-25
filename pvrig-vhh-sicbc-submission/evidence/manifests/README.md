# Integrity manifests

`SHA256SUMS` covers every repository file except itself and Git internals.
`top10_pose_sha256s.txt` is a focused PDB checksum list.  Regenerate the main
manifest with `python3 scripts/write_sha256s.py` after an intentional change.

#!/usr/bin/env bash
set -euo pipefail
umask 027

ROOT=/data1/qlyu/projects/pvrig_top7500_c2_gap_recovery_v1_20260723
PARENT=c2_new6220_split4220_2000_dualreceptor_2seed_handoffs_v2
ARCHIVE_DIR="$ROOT/archives"
ARCHIVE="$ARCHIVE_DIR/pvrig_c2_new6220_dualreceptor_2seed_handoffs_v2_20260723.tar.gz"
PARTIAL="$ARCHIVE.partial"

mkdir -p "$ARCHIVE_DIR"

if [[ -s "$ARCHIVE" && -s "$ARCHIVE.sha256" ]] &&
   (cd "$ARCHIVE_DIR" && sha256sum -c "$(basename "$ARCHIVE").sha256" >/dev/null); then
    printf 'READY %s\n' "$ARCHIVE"
    exit 0
fi

rm -f "$PARTIAL"
if command -v pigz >/dev/null 2>&1; then
    tar -C "$ROOT" -cf - "$PARENT" | pigz -1 -p 8 > "$PARTIAL"
else
    tar -C "$ROOT" -czf "$PARTIAL" "$PARENT"
fi
mv "$PARTIAL" "$ARCHIVE"
(
    cd "$ARCHIVE_DIR"
    sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
    stat -c '%s' "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").bytes"
)
printf 'READY %s\n' "$ARCHIVE"

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_submission_integrity() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_submission.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout

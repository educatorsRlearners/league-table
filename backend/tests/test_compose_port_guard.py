import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check-compose-ports.py"

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker CLI not available"
)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def test_fixed_overrides_pass() -> None:
    result = run()
    assert result.returncode == 0, result.stderr


def test_appending_override_fails(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text(
        'services:\n  db:\n    ports:\n      - "15433:5432"\n'
        "  backend:\n    ports:\n      - \"18000:8000\"\n"
    )
    result = run(str(bad))
    assert result.returncode != 0
    assert "5433" in result.stderr
    assert "8000" in result.stderr

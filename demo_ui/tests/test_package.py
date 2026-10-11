"""The built distribution imports the demo under its real package name."""

import subprocess
import sys
import os
from pathlib import Path
from zipfile import ZipFile


def test_wheel_contains_demo_package_and_demo_crypto_dependency(tmp_path):
    root = Path(__file__).resolve().parents[2]
    wheels = tmp_path / "wheels"
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-index", "--no-deps",
         "--no-build-isolation", "--wheel-dir", str(wheels), "."],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    wheel = next(wheels.glob("*.whl"))
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert "demo_ui/__init__.py" in names
        assert "demo_ui/signed_gateway.py" in names
        assert "dcta/__init__.py" in names
        assert "dcta/mixed/session.py" in names
        assert not any("demo_requests.jsonl" in name for name in names)
        assert not any("/tests/" in name or name.startswith("tests/") for name in names)
        metadata = archive.read(next(n for n in names if n.endswith(".dist-info/METADATA"))).decode()
        assert "cryptography" in metadata
    installed = tmp_path / "installed"
    install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
         "--target", str(installed), str(wheel)],
        capture_output=True,
        text=True,
    )
    assert install.returncode == 0, install.stderr
    imported = subprocess.run(
        [sys.executable, "-c", "from demo_ui.signed_gateway import SignedExecutionGateway; print(SignedExecutionGateway.schema_version)"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(installed)},
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr
    assert imported.stdout.strip() == "signed-execution-gateway-v1"

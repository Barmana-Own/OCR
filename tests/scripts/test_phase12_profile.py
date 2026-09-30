import json
import subprocess
import sys
from pathlib import Path

from PIL import Image


def test_profile_script_reports_dpi_costs(tmp_path: Path) -> None:
    source = tmp_path / "profile.png"
    output = tmp_path / "results.json"
    Image.new("RGB", (24, 24), "white").save(source, format="PNG")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/profile_pipeline.py",
            str(source),
            "--dpi",
            "300",
            "450",
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["dpis"] == [300, 450]
    assert len(payload["measurements"]) == 2
    assert all(item["artifact_bytes"] > 0 for item in payload["measurements"])

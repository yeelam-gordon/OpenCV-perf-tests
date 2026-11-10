"""Confirm retained build outputs with captured smoke results, outside timing."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
results = Path(sys.argv[1])
study = json.loads((results / "study.json").read_text(encoding="utf-8-sig"))
executable = (
    root / ".work/smoke_MSVC2026_MSBuild/Release/opencv_smoke.exe"
)
records = []


def captured_text(value):
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")


for run in study["runs"]:
    directory = results / run["directory"]
    receipt = directory / "smoke-captured.json"
    if receipt.exists():
        raise FileExistsError(receipt)
    dll = directory / "runtime-binaries/opencv_world4100.dll"
    validation = json.loads((directory / "output-validation.json").read_text())
    digest = hashlib.sha256(dll.read_bytes()).hexdigest()
    if digest != validation["image"]["sha256"] or validation["image"]["machine"] != "0xaa64":
        raise ValueError(f"Retained output identity mismatch: {run['label']}")
    destination = dll.parent / executable.name
    shutil.copy2(executable, destination)
    record = {
        "label": run["label"], "exit_code": None,
        "stdout": "", "stderr": "", "dll_sha256": digest,
        "smoke_executable_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "scope": "Untimed common current-harness image/matrix check, not full toolchain/runtime qualification",
    }
    try:
        output = subprocess.run(
            [str(destination)], cwd=dll.parent, text=True, capture_output=True,
            check=False, timeout=60,
        )
        record.update(exit_code=output.returncode, stdout=output.stdout, stderr=output.stderr)
        record["status"] = (
            "passed" if output.returncode == 0
            and "image and matrix smoke checks passed" in output.stdout else "failed"
        )
    except subprocess.TimeoutExpired as error:
        record.update(status="timed_out", stdout=captured_text(error.stdout),
                      stderr=captured_text(error.stderr), error=str(error))
    except OSError as error:
        record.update(status="launch_failed", error=str(error))
    receipt.write_text(json.dumps(record, indent=2))
    records.append(record)
    (results / "output-smoke-captured.json").write_text(json.dumps(records, indent=2))
    if record["status"] != "passed":
        raise RuntimeError(
            f"Retained-output smoke {record['status']}: {run['label']}; "
            f"exit={record['exit_code']}; captured diagnostics preserved"
        )
print(f"Confirmed {len(records)} retained native outputs with captured smoke evidence")

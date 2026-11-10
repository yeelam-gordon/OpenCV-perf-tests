"""Capture untimed compiler-command and native output evidence after each build."""

import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_msbuild_tail import command_manifest
from analyze_runtime_screen import image_sections

build, run = map(Path, sys.argv[1:])
commands = command_manifest(build)
(run / "commands.json").write_text(
    json.dumps(commands, sort_keys=True, indent=2), encoding="utf-8"
)
dll = build / "bin" / "Release" / "opencv_world4100.dll"
image = image_sections(dll)
if image["machine"] != "0xaa64":
    raise ValueError("Expected native Arm64 output")
destination = run / "runtime-binaries"
destination.mkdir()
copy = destination / dll.name
shutil.copy2(dll, copy)
if hashlib.sha256(copy.read_bytes()).hexdigest() != image["sha256"]:
    raise ValueError("Retained DLL copy changed")
(run / "output-validation.json").write_text(
    json.dumps({"command_records": len(commands), "image": image}, indent=2),
    encoding="utf-8",
)

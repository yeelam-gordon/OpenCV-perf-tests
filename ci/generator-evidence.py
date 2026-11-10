"""Retain uninstrumented-run inputs and outputs after the build timer stops."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "scripts"))
from analyze_msbuild_tail import command_manifest
from analyze_runtime_screen import image_sections

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("build", type=Path)
parser.add_argument("run", type=Path)
parser.add_argument("dll", type=Path)
parser.add_argument("--generator", choices=("MSBuild", "Ninja"), required=True)
args = parser.parse_args()
if args.generator == "MSBuild":
    commands = command_manifest(args.build)
else:
    cache = (args.build / "CMakeCache.txt").read_text(encoding="utf-8-sig")
    match = re.search(r"^CMAKE_MAKE_PROGRAM:[^=]+=(.+)$", cache, re.M)
    if not match:
        raise ValueError("Missing selected Ninja path")
    result = subprocess.run(
        [match[1], "-C", str(args.build), "-t", "compdb"],
        text=True, capture_output=True, check=True,
    )
    commands = json.loads(result.stdout)
(args.run / "commands.json").write_text(
    json.dumps(commands, indent=2, sort_keys=True), encoding="utf-8"
)
snapshot = args.run / "runtime-binaries"
snapshot.mkdir()
copy = snapshot / args.dll.name
shutil.copy2(args.dll, copy)
image = image_sections(copy)
if image["machine"] != "0xaa64":
    raise ValueError("Output is not native Arm64")
if image["sha256"] != hashlib.sha256(args.dll.read_bytes()).hexdigest():
    raise ValueError("Retained DLL copy changed")
headers = {}
for name in ("cvconfig.h", "opencv2/opencv_modules.hpp"):
    source = args.build / name
    destination = args.run / Path(name).name
    shutil.copy2(source, destination)
    headers[name] = hashlib.sha256(source.read_bytes()).hexdigest()
(args.run / "output-validation.json").write_text(
    json.dumps({"image": image, "feature_headers": headers}, indent=2), encoding="utf-8"
)

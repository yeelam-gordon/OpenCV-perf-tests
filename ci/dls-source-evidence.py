"""Post-timer source/workload/object receipts; never upload the captured binaries."""

import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import shlex
import shutil
import subprocess

HEADERS = ("cvconfig.h", "opencv2/opencv_modules.hpp", "cv_cpu_config.h")
SOURCE = "modules/calib3d/src/dls.cpp"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def identity(file, source, build):
    value = str(file).replace("\\", "/").strip('"').lower()
    for root, prefix in ((build, "generated/"), (source, "")):
        start = str(root).replace("\\", "/").lower().rstrip("/") + "/"
        if value.startswith(start):
            return prefix + value[len(start):]
    raise ValueError(f"Compile input outside configured source/build: {file}")


def principal(command, msvc=True):
    macros = re.findall(r'(?:^|\s)(?:/|-)D\s*("[^"]+"|[^\s"]+)', command)
    macros = sorted(m.strip('"') for m in macros if not m.strip('"').startswith("CMAKE_INTDIR="))
    eh = sorted(set(re.findall(r"(?i)(?:/|-)(EH[a-z]+)\b", command)))
    fp = sorted(set(re.findall(r"(?i)(?:/|-)(fp:[a-z]+)\b", command)))
    crt = sorted(set(re.findall(r"(?:/|-)(MDd?|MTd?)\b", command))) if msvc else []
    return {"macros": macros, "eh": eh, "fp": fp, "crt": crt}


def compilation_entries(commands, generator):
    entries = []
    if generator == "MSBuild":
        for key, command in commands.items():
            marker = key.split("|^", 1)
            if len(marker) != 2:
                raise ValueError("Malformed MSBuild command identity")
            for file in marker[1].split("|"):
                entries.append({"file": file, "command": command, "tlog": marker[0]})
    else:
        for entry in commands:
            if generator == "Ninja" and Path(entry.get("output", "")).suffix.lower() not in (".obj", ".o"):
                continue
            # CMake's compile database includes Objective-C/C++ and assembly too.
            entries.append(entry)
    return entries


def unit_manifest(entries, source, build, generator):
    records = []
    for entry in entries:
        file = entry["file"]
        if not Path(file).is_absolute():
            file = Path(entry["directory"]) / file
        records.append((identity(file, source, build), entry["command"]))
    if not records:
        raise ValueError("No compiler units captured")
    world = [(file, principal(command, generator != "Make")) for file, command in records
             if file.startswith(("modules/", "generated/modules/"))]
    if not any(file == SOURCE for file, _ in world):
        raise ValueError("DLS source compile command missing")
    return records, world


def units(commands, source, build, generator):
    return unit_manifest(compilation_entries(commands, generator), source, build, generator)


def compiled_output(entry, generator):
    if generator == "Make":
        tokens = shlex.split(entry["command"])
        if "-o" not in tokens:
            raise ValueError("Missing Make compiler output")
        name = tokens[tokens.index("-o") + 1]
    else:
        name = entry["output"]
    return Path(entry["directory"]) / name


def compiled_outputs(entries, generator):
    outputs = []
    for entry in entries:
        output = compiled_output(entry, generator)
        if not output.is_file():
            raise ValueError(f"Compile-database unit was not actually built: {entry['file']}")
        outputs.append(output)
    if len(set(outputs)) != len(entries):
        raise ValueError("Duplicate compile-database object outputs")
    return outputs


def dls_object(entries, source, build, generator):
    bindings = []
    for entry in entries:
        file = Path(entry["file"])
        if not file.is_absolute():
            file = Path(entry["directory"]) / file
        if identity(file, source, build) == SOURCE:
            bindings.append(entry)
    if len(bindings) != 1:
        raise ValueError(f"Expected exactly one DLS source binding; found {len(bindings)}")
    entry = bindings[0]
    if generator == "MSBuild":
        tlog = PureWindowsPath(entry["tlog"])
        expected = PureWindowsPath("modules/world/opencv_world.dir/Release")
        if tlog != expected / "opencv_world.tlog/CL.command.1.tlog":
            raise ValueError("DLS source binding is not the MSBuild world Release target")
        options = re.findall(r'(?:^|\s)/Fo(?:"([^"]+)"|(\S+))', entry["command"], re.I)
        if len(options) != 1:
            raise ValueError("Expected exactly one MSBuild DLS /Fo output binding")
        name = options[0][0] or options[0][1]
        output = PureWindowsPath(name)
        if not output.is_absolute():
            output = PureWindowsPath(str(build)) / "modules/world" / output
        directory = PureWindowsPath(str(build)) / expected
        if name.endswith(("\\", "/")):
            output /= PureWindowsPath(SOURCE).stem + ".obj"
        if output != directory / "dls.obj":
            raise ValueError("MSBuild DLS /Fo does not match its world Release source binding")
        path = build / "modules/world/opencv_world.dir/Release/dls.obj"
    else:
        path = compiled_output(entry, generator).resolve()
        try:
            relative = path.relative_to(build.resolve())
        except ValueError:
            raise ValueError("DLS object output is outside the configured build") from None
        prefix = ("modules", "world", "cmakefiles", "opencv_world.dir")
        basename = "dls.cpp.obj" if generator == "Ninja" else "dls.cpp.o"
        if tuple(part.lower() for part in relative.parts[:4]) != prefix or path.name.lower() != basename:
            raise ValueError("DLS source binding is not the configured world object target")
    if not path.is_file():
        raise ValueError(f"Source-bound DLS object is missing: {path}")
    return path


def capture(source, build, run, generator, entries=None):
    if entries is None:
        commands = load(run / "commands.json")
        entries = compilation_entries(commands, generator)
    records, world = unit_manifest(entries, source, build, generator)
    object_file = dls_object(entries, source, build, generator)
    target = run / "runtime-binaries" / object_file.name
    target.parent.mkdir(exist_ok=True)
    shutil.copyfile(object_file, target)
    if sha(target) != sha(object_file):
        raise ValueError("DLS object copy mismatch")
    headers = {}
    for name in HEADERS:
        file = build / name
        headers[name] = sha(file)
        shutil.copyfile(file, run / file.name)
    def git(*args):
        return subprocess.run(["git", "-C", str(source), *args], check=True,
                              text=True, capture_output=True).stdout.strip()
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Dirty pinned source after build")
    record = {
        "unit_count": len(records),
        "openexr_units": sum("3rdparty/openexr/" in file for file, _ in records),
        "units": sorted(file for file, _ in records),
        "world_principal": sorted(world, key=lambda row: (row[0], json.dumps(row[1], sort_keys=True))),
        "headers_sha256": headers, "source_commit": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "source_blob": git("rev-parse", f"HEAD:{SOURCE}"),
        "source_raw_sha256": sha(source / SOURCE), "dls_object_sha256": sha(target),
        "dls_object_bytes": target.stat().st_size,
        "dls_object_binding": {"generator": generator, "source": SOURCE,
                               "object_build_relative": str(object_file.resolve().relative_to(build.resolve()))},
        "proof_scope": "Object copied and hashed after timer locally. Text-only cloud upload is a receipt, not retained-binary proof.",
    }
    if generator in ("Make", "Ninja"):
        outputs = compiled_outputs(entries, generator)
        record["actual_object_count"] = len(outputs)
        if len(outputs) != len(records):
            raise ValueError("Compile-database object/source count mismatch")
    (run / "source-workload.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


def compare(results, platform="windows"):
    study = load(results / "study.json")
    reference = None
    audited = []
    for run in study["runs"]:
        record = load(results / run["directory"] / "source-workload.json")
        if reference is None:
            reference = record
        for key in ("units", "headers_sha256", "world_principal"):
            if record[key] != reference[key]:
                raise ValueError(f"{key} mismatch: {run['label']}")
        if platform == "windows" and (record["unit_count"] != 1015 or record["openexr_units"] != 107):
            raise ValueError(f"Windows workload drift: {run['label']}; expected 1015 units / 107 bundled OpenEXR")
        expected = load(Path(__file__).with_name("dls-source-variant.json"))
        prefix = "variant" if run["configuration"] == "table" else "base"
        if record["source_tree"] != expected[prefix + "_tree"] or record["source_blob"] != expected[prefix + "_blob"]:
            raise ValueError(f"Source variant mismatch: {run['label']}")
        for file, flags in record["world_principal"]:
            if platform == "windows" and (not any(value.lower() == "eha" for value in flags["eh"]) or flags["crt"] != ["MD"]):
                raise ValueError(f"Expected world /EHa and /MD: {file}")
        audited.append({"label": run["label"], "units": record["unit_count"],
                        "openexr_units": record["openexr_units"]})
    (results / "workload-parity.json").write_text(json.dumps({
        "status": "passed-so-far", "runs": audited,
        "comparison": "Exact source multiset, three feature/CPU headers and per-world-source EH/FP/CRT/macros (except configuration-location CMAKE_INTDIR). Source CPP differs only as declared by canonical variant tree.",
        "cross_platform": "Do not require macOS counts/dependencies to equal Windows; no core/count normalization.",
    }, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    part = sub.add_parser("capture")
    for name in ("source", "build", "run"):
        part.add_argument("--" + name, type=Path, required=True)
    part.add_argument("--generator", choices=("MSBuild", "Ninja", "Make"), required=True)
    part = sub.add_parser("compare")
    part.add_argument("--results", type=Path, required=True)
    part.add_argument("--platform", choices=("windows", "macos"), default="windows")
    args = parser.parse_args()
    if args.action == "capture":
        capture(args.source, args.build, args.run, args.generator)
    else:
        compare(args.results, args.platform)


if __name__ == "__main__":
    main()

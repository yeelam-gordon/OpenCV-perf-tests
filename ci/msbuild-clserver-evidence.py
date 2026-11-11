"""Fail-closed unchanged-source MSBuild/CL-server and Make reference receipts."""

import argparse
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import statistics
import subprocess
import sys


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


source_evidence = load_module("dls-source-evidence")
BASE = "71d3237a093b60a27601c20e9ee6c3e52154e8b1"
TREE = "1f7a0c7fcc20571cab11da4c86ae1e796979df5b"
BLOB = "f0b9d850e9879aa21dc87f899e605acad7801bc7"
SERVER = ["/p:MultiProcCL=true", "/p:MultiProcMaxCount=4",
          "/p:EnforceProcessCountAcrossBuilds=true", "/nr:false", "/p:EnableClServerMode=true"]
PROPERTIES = ("MultiProcCL", "MultiProcMaxCount", "EnforceProcessCountAcrossBuilds", "EnableClServerMode")
CONTEXT = ("PreprocessorDefinitions", "ExceptionHandling", "FloatingPointModel", "RuntimeLibrary", "PrecompiledHeader",
           "AdditionalOptions", "AdditionalIncludeDirectories", "Optimization", "ForcedIncludeFiles")
BINARIES = ("bin/Release/opencv_world4100.dll", "lib/Release/opencv_world4100.lib",
            "bin/Release/opencv_version.exe")


def write(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def git(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def source_guard(source):
    for args, expected in ((("rev-parse", "HEAD"), BASE), (("rev-parse", "HEAD^{tree}"), TREE),
                           (("rev-parse", "HEAD:" + source_evidence.SOURCE), BLOB),
                           (("status", "--porcelain", "--untracked-files=no"), "")):
        if git(source, *args) != expected:
            raise ValueError("Exact clean BASE/source/tree/blob required")


def temp_guard(temp, owner):
    temp, owner = temp.resolve(), owner.resolve()
    if re.search(r"\s", str(temp)) or not temp.is_relative_to(owner) or temp == owner:
        raise ValueError("TEMP must be a whitespace-free child of the host-owned runner root")


def object_path(name, source, project, build):
    if not name or "$(" in name or "%(" in name:
        raise ValueError("Unevaluated or missing native object binding")
    path = PureWindowsPath(name)
    if not path.is_absolute():
        path = PureWindowsPath(str(project.parent)) / path
    if name.endswith(("\\", "/")):
        path /= PureWindowsPath(str(source)).stem + ".obj"
    actual = Path(str(path)).resolve()
    if not actual.is_relative_to(build.resolve()):
        raise ValueError("Object binding outside configured build")
    return actual


def query(msbuild, project, settings, extra=()):
    arguments = [str(msbuild), str(project), "-nologo", "-verbosity:quiet",
                 "-p:Configuration=Release", "-p:Platform=ARM64", *settings,
                 "-getProperty:" + ",".join(PROPERTIES + tuple(extra)), "-getItem:ClCompile"]
    result = subprocess.run(arguments, check=True, capture_output=True, text=True, encoding="utf-8-sig")
    return json.loads(result.stdout)


def plan(source, build, path, candidate_build=None):
    source_guard(source)
    temp = Path(os.environ["TEMP"])
    temp_guard(temp, Path(os.environ["RUNNER_TEMP"]))
    if temp.resolve() != Path(os.environ["TMP"]).resolve():
        raise ValueError("Both cases require identical process-owned TEMP/TMP")
    setup = source_evidence.load(build / "benchmark-setup.json")
    if setup["generator"] != "MSBuild" or setup["compiler_id"] != "MSVC" or setup["architecture"] != "arm64":
        raise ValueError("Native MSVC/MSBuild Arm64 required")
    config = source_evidence.load(Path(__file__).resolve().parents[1] / "benchmark.json")
    if config["opencv_commit"] != BASE or len(config["cmake_flags"]) != 23:
        raise ValueError("Unchanged BASE/23-definition workload required")
    pch_helper = load_module("msbuild-pch-evidence") if candidate_build else None
    if candidate_build and candidate_build.resolve() == build.resolve():
        raise ValueError("Original and combined profiles must be isolated")
    cases = {}
    modes = (("original", [], build), ("combined", SERVER, candidate_build)) if candidate_build else (
        ("original", [], build), ("server", SERVER, build))
    for mode, settings, selected in modes:
        selected_setup = source_evidence.load(selected / "benchmark-setup.json")
        for field in ("generator", "compiler_id", "architecture", "config_sha256", "compiler_sha256", "cmake_sha256"):
            if selected_setup.get(field) != setup.get(field):
                raise ValueError("Configured profile tool/definition drift")
        if selected_setup.get("windows_sdk") != setup.get("windows_sdk") or selected_setup.get("build_engine") != setup.get("build_engine"):
            raise ValueError("Configured profile SDK/MSBuild drift")
        projects = sorted(project for project in selected.rglob("*.vcxproj")
                          if project.relative_to(selected).parts[0] != "CMakeFiles"
                          and project.stem not in ("ALL_BUILD", "INSTALL", "ZERO_CHECK"))
        units, profiles = [], {}
        for project in projects:
            data = query(setup["build_engine"]["path"], project, settings, ("IntDir",)) if candidate_build else query(
                setup["build_engine"]["path"], project, settings)
            properties = data["Properties"]
            if mode != "original":
                expected = dict(zip(PROPERTIES, ("true", "4", "true", "true")))
                if {key: properties[key].lower() for key in PROPERTIES} != expected:
                    raise ValueError("Native evaluated shared/server profile mismatch")
            elif any(properties[key].lower() not in ("", "false") for key in
                     ("MultiProcCL", "EnforceProcessCountAcrossBuilds", "EnableClServerMode")):
                raise ValueError("Original native scheduling defaults contaminated")
            profiles[project.relative_to(selected).as_posix()] = properties
            for item in data["Items"]["ClCompile"]:
                if item.get("ExcludedFromBuild", "").lower() == "true":
                    continue
                file = Path(item["FullPath"])
                if mode != "combined" and (item.get("PrecompiledHeader", "").lower() not in ("", "notusing") or
                                           "cmake_pch" in item.get("ForcedIncludeFiles", "").lower()):
                    raise ValueError("PCH is outside this MSBuild server experiment")
                output = object_path(item.get("ObjectFileName"), file, project, selected)
                unit = {
                    "file": str(file), "identity": source_evidence.identity(file, source, selected),
                    "output": str(output), "project": str(project),
                    "context": {key: item.get(key, "") for key in CONTEXT},
                    "source_sha256": source_evidence.sha(file) if file.is_file() else None,
                }
                if candidate_build:
                    unit["pch"] = {key: item.get(key, "") for key in pch_helper.PCH_FIELDS}
                units.append(unit)
        units.sort(key=lambda unit: (unit["identity"], unit["output"]))
        pch = None
        if mode == "combined":
            world_base = pch_helper.common_world_base(cases["original"]["units"], source, build)
            units, pch = pch_helper.partition(units, source, selected, world_base)
        if len(units) != 1015 or sum("3rdparty/openexr/" in unit["identity"] for unit in units) != 107:
            raise ValueError("Expected 1015 original compiler units including 107 OpenEXR")
        if len({unit["output"] for unit in units}) != len(units):
            raise ValueError("Duplicate native object bindings")
        cases[mode] = {"units": units, "profiles": profiles, "build": str(selected)}
        if candidate_build:
            cases[mode]["features"] = {name: source_evidence.sha(selected / name) for name in source_evidence.HEADERS}
            cases[mode]["pch"] = pch
    if candidate_build:
        pch_helper.paired_units(cases["original"]["units"], cases["combined"]["units"], source, build, candidate_build)
        if cases["original"]["features"] != cases["combined"]["features"]:
            raise ValueError("Combined changed source/output/context/features beyond roots/PCH bookkeeping")
    elif cases["original"]["units"] != cases["server"]["units"]:
        raise ValueError("Candidate changed source/object/compiler context beyond scheduler properties")
    common = Path(setup["visual_studio"]["path"]) / "MSBuild/Microsoft/VC/v180/Microsoft.CppCommon.targets"
    write(path, {
        "source_commit": BASE, "source_tree": TREE, "cases": cases,
        "stock_server_targets": str(common), "stock_server_targets_sha256": source_evidence.sha(common),
        "features": {name: source_evidence.sha(build / name) for name in source_evidence.HEADERS},
        "config_sha256": source_evidence.sha(Path(__file__).resolve().parents[1] / "benchmark.json"),
        "compiler_temp": str(temp),
        "combined": bool(candidate_build),
        "resource_profile": "Shared budget4 plus CL-server request; different residency, not a four-resident/busy/global cap.",
    })


def clean(source, build, run, path, generator, configuration="original"):
    source_guard(source)
    if generator == "Make":
        entries = source_evidence.compilation_entries(source_evidence.load(build / "compile_commands.json"), "Make")
        if len(entries) != 908:
            raise ValueError("Expected 908 complete Make language units")
        outputs = [source_evidence.compiled_output(entry, "Make") for entry in entries]
    else:
        data = source_evidence.load(path)
        if os.environ.get("TEMP") != data["compiler_temp"] or os.environ.get("TMP") != data["compiler_temp"]:
            raise ValueError("Process-owned matched TEMP/TMP changed")
        case = data["cases"][configuration]
        if data.get("combined") and Path(case["build"]).resolve() != build.resolve():
            raise ValueError("Configured profile/build contamination")
        outputs = [Path(unit["output"]) for unit in case["units"]]
        outputs += [build / name for name in BINARIES]
        if len(outputs) != 1018:
            raise ValueError("Expected all 1015 required native objects and three outputs")
        if case.get("pch"):
            load_module("msbuild-pch-evidence").wrapper_input(case["pch"])
            outputs += [Path(name) for name in case["pch"]["artifacts"]]
        for name, digest in case.get("features", data["features"]).items():
            if source_evidence.sha(build / name) != digest:
                raise ValueError("Feature header drift before timer")
    if any(output.exists() for output in outputs):
        raise ValueError("Required native object/binary still present before timer")
    write(run / "native-clean.json", {"status": "passed", "required_absent": len(outputs),
                                      "checked_at": datetime.now().astimezone().isoformat()})


def native_outputs(entries, build):
    records = []
    for entry in entries:
        options = re.findall(r'(?:^|\s)/Fo(?:"([^"]+)"|(\S+))', entry["command"], re.I)
        if len(options) != 1:
            raise ValueError("Missing or ambiguous source-bound /Fo")
        name = options[0][0] or options[0][1]
        project = build / str(PureWindowsPath(entry["tlog"]).parents[3]) / "binding.vcxproj"
        records.append((entry, object_path(name, entry["file"], project, build)))
    if len({str(output) for _, output in records}) != len(records):
        raise ValueError("Duplicate compiled native objects")
    return records


def clock_outputs(outputs, owned):
    start, end = (datetime.fromisoformat(owned[key]).timestamp() for key in ("started_at", "finished_at"))
    if end < start:
        raise ValueError("Invalid owned build clock")
    for output in outputs:
        if not output.is_file() or not start <= output.stat().st_mtime <= end:
            raise ValueError("Required compiler/link output not created inside owned clock")


def capture(source, build, run, path, generator, configuration="original"):
    source_guard(source)
    if generator == "Make":
        source_evidence.capture(source, build, run, "Make")
        entries = source_evidence.compilation_entries(source_evidence.load(run / "commands.json"), "Make")
        records = [(entry, source_evidence.compiled_output(entry, "Make")) for entry in entries]
        if len(records) != 908:
            raise ValueError("Expected all 908 Make language units")
    else:
        data = source_evidence.load(path)
        case = data["cases"][configuration]
        pch = case.get("pch")
        owned = source_evidence.load(run / "owned-build.json")
        if owned["exit_code"] or not owned["descendants_drained_after_clock"]:
            raise ValueError("Owned build/lifecycle failed")
        binary = build / BINARIES[0]
        subprocess.run([sys.executable, str(Path(__file__).with_name("generator-evidence.py")),
                        str(build), str(run), str(binary), "--generator", "MSBuild"], check=True)
        entries = source_evidence.compilation_entries(source_evidence.load(run / "commands.json"), "MSBuild")
        records = native_outputs(entries, build)
        required_units = case["units"] + ([pch["producer"]] if pch else [])
        expected = sorted((unit["identity"], str(Path(unit["output"]).resolve()).lower()) for unit in required_units)
        actual = sorted((source_evidence.identity(Path(entry["file"]), source, build), str(output).lower())
                        for entry, output in records)
        if len(records) != 1015 + int(bool(pch)) or actual != expected:
            raise ValueError("Timed compile units/source-bound native object plan mismatch")
        clock_outputs([output for _, output in records] + [build / name for name in BINARIES] +
                      ([Path(name) for name in pch["artifacts"]] if pch else []), owned)
        pch_receipt = {}
        pch_inputs = {}
        if pch:
            helper = load_module("msbuild-pch-evidence")
            wrapper = helper.wrapper_input(pch)
            helper.diagnostics((run / "build.log").read_text(encoding="utf-8-sig", errors="replace"))
            observations = source_evidence.load(run.parent / "study.json")["runs"]
            original = next((item for item in observations if item["configuration"] == "original"), None)
            if original is None:
                raise ValueError("Original WORLD base receipt must precede combined capture")
            original_entries = source_evidence.compilation_entries(
                source_evidence.load(run.parent / original["directory"] / "commands.json"), "MSBuild")
            entries = helper.commands(entries, source, build, pch, source_evidence.principal, original_entries)
            records = [(entry, output) for entry, output in records if not helper.producer(entry["file"])]
            for name in pch["artifacts"]:
                file = Path(name)
                target = run / "runtime-binaries" / file.name
                shutil.copyfile(file, target)
                if source_evidence.sha(file) != source_evidence.sha(target):
                    raise ValueError("PCH/producer retained copy differs")
                pch_receipt[file.name] = {"sha256": source_evidence.sha(target), "bytes": target.stat().st_size}
            shutil.copyfile(wrapper, run / "pch-wrapper.txt")
            pch_inputs = {"wrapper": str(wrapper.resolve().relative_to(build.resolve())),
                          "sha256": source_evidence.sha(wrapper),
                          "scope": "Frozen configure-time input; no clean-deletion or in-clock timestamp requirement."}
        elif any(re.search(r'(?i)(?:^|[\s"])/Y[cu]', entry["command"]) for entry in entries):
            raise ValueError("PCH compiler options are outside this experiment")
        source_evidence.capture(source, build, run, "MSBuild", entries=entries)
        for name in BINARIES[1:]:
            retained = run / "runtime-binaries" / Path(name).name
            shutil.copyfile(build / name, retained)
            if source_evidence.sha(retained) != source_evidence.sha(build / name):
                raise ValueError("Retained native binary copy differs")
        write(run / "native-output.json", {
            "status": "passed", "source_objects": len(records),
            "producer_objects": int(bool(pch)), "pch_outputs": pch_receipt, "pch_inputs": pch_inputs,
            "binaries": {name: source_evidence.sha(build / name) for name in BINARIES},
            "retained_sha256": {Path(name).name: source_evidence.sha(run / "runtime-binaries" / Path(name).name)
                                for name in BINARIES},
            "boundary": "Captured after clock/owned-descendant drain and BEFORE direct install; no offclock OpenCV build.",
            "proof_scope": "Actual runner-local copies; uploaded text hashes are not retained-binary proof.",
        })
        if data.get("combined"):
            helper = load_module("msbuild-pch-evidence")
            write(run / "compiled-flags.json", sorted([
                {"source": source_evidence.identity(Path(entry["file"]), source, build),
                 "project": str(PureWindowsPath(entry["tlog"]).parent).replace("\\", "/").lower(),
                 "flags": helper.flags(entry, source, build)} for entry in entries
            ], key=lambda row: (row["source"], row["project"], str(row["flags"]))))
    if source_evidence.load(run / "native-clean.json")["status"] != "passed":
        raise ValueError("Missing preclock native clean receipt")
    inputs = []
    for entry, output in records:
        file = Path(entry["file"])
        if not file.is_absolute():
            file = Path(entry["directory"]) / file
        if not output.is_file():
            raise ValueError("Required actual source object missing")
        inputs.append({"source": source_evidence.identity(file, source, build),
                       "source_sha256": source_evidence.sha(file),
                       "object_sha256": source_evidence.sha(output),
                       "suffix": file.suffix.lower()})
    write(run / "compiled-inputs.json", sorted(inputs, key=lambda row: row["source"]))


def compare(results, generator):
    study = source_evidence.load(results / "study.json")
    reference = None
    scores = {}
    for observation in study["runs"]:
        run = results / observation["directory"]
        if study.get("combined_pch"):
            if observation["configuration"] not in ("original", "combined") or not (run / "compiled-flags.json").is_file():
                raise ValueError("Missing combined-cohort flag evidence or wrong profile")
            output = source_evidence.load(run / "native-output.json")
            expected_producers = int(observation["configuration"] == "combined")
            if (output["source_objects"] != 1015 or output["producer_objects"] != expected_producers or
                    len(output["pch_outputs"]) != 2 * expected_producers):
                raise ValueError("Missing combined-cohort producer/native-output proof")
            if expected_producers and not output.get("pch_inputs", {}).get("sha256"):
                raise ValueError("Missing frozen PCH wrapper input proof")
        record = source_evidence.load(run / "source-workload.json")
        if (record["source_commit"], record["source_tree"], record["source_blob"]) != (BASE, TREE, BLOB):
            raise ValueError("BASE source drift")
        if record["unit_count"] != (1015 if generator == "MSBuild" else 908):
            raise ValueError("Compiler unit count drift")
        inputs = source_evidence.load(run / "compiled-inputs.json")
        binding = [(item["source"], item["source_sha256"]) for item in inputs]
        principal = {name: record[name] for name in ("units", "headers_sha256", "world_principal")}
        if generator == "MSBuild":
            for name, context in record["world_principal"]:
                if [value.lower() for value in context["eh"]] != ["eha"] or context["crt"] != ["MD"]:
                    raise ValueError("Required world EH/CRT context changed: " + name)
        flags = source_evidence.load(run / "compiled-flags.json") if (run / "compiled-flags.json").exists() else None
        current = binding, principal, flags
        if reference is not None and current != reference:
            raise ValueError("Source/header/principal compile context drift")
        reference = current
        if not observation["warmup"]:
            scores.setdefault(observation["configuration"], []).append(observation["build_seconds"])
    write(results / "workload-parity.json", {
        "status": "passed-so-far", "source_commit": BASE, "source_tree": TREE,
        "runs": len(study["runs"]), "generator": generator,
        "scope": "Within-platform only; 1015 Windows and 908 Mac are different workload boundaries.",
        "language_counts": {suffix: sum(item["suffix"] == suffix for item in inputs)
                            for suffix in sorted({item["suffix"] for item in inputs})} if reference else {},
        "scores": {name: {"seconds": values, "median": statistics.median(values),
                          "min": min(values), "max": max(values)} for name, values in scores.items()},
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "clean", "capture", "compare"))
    for name in ("source", "build", "run", "plan", "results", "candidate-build"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--generator", choices=("MSBuild", "Make"), default="MSBuild")
    parser.add_argument("--configuration", choices=("original", "server", "combined"), default="original")
    args = parser.parse_args()
    if args.action == "plan":
        plan(args.source, args.build, args.plan, args.candidate_build)
    elif args.action == "clean":
        clean(args.source, args.build, args.run, args.plan, args.generator, args.configuration)
    elif args.action == "capture":
        capture(args.source, args.build, args.run, args.plan, args.generator, args.configuration)
    else:
        compare(args.results, args.generator)


if __name__ == "__main__":
    main()

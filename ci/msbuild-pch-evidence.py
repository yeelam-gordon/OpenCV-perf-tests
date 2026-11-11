"""World-only native VS PCH specialization; no source or SDK mutation."""

import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET

HEADERS = ("vector", "algorithm", "string", "memory", "utility", "limits")
PCH_FIELDS = ("PrecompiledHeader", "PrecompiledHeaderFile", "PrecompiledHeaderOutputFile",
              "ForcedIncludeFiles", "MultiProcessorCompilation", "EnableClServerMode")
WORLD_TLOG = "modules/world/opencv_world.dir/release/opencv_world.tlog/cl.command.1.tlog"


def producer(file):
    return Path(file).name.lower() == "cmake_pch.cxx"


def path(value, project):
    result = Path(value)
    return (result if result.is_absolute() else Path(project).parent / result).resolve()


def standard_header(file):
    includes = re.findall(r"^\s*#\s*include\s+(.+?)\s*$", file.read_text(), re.M)
    if includes != ["<" + name + ">" for name in HEADERS]:
        raise ValueError("PCH wrapper must contain exactly six standard headers")


def wrapper_input(profile):
    wrapper = Path(profile["wrapper"])
    if hashlib.sha256(wrapper.read_bytes()).hexdigest() != profile["wrapper_sha256"]:
        raise ValueError("Frozen PCH wrapper input changed")
    standard_header(wrapper)
    return wrapper


def normal(value, source, build):
    text = value
    for root, label in ((build, "<BUILD>"), (source, "<SOURCE>")):
        for spelling in {str(root), str(root).replace("\\", "/")}:
            text = re.sub(re.escape(spelling), lambda _: label, text, flags=re.I)
    return text


def unit_key(unit, source, build):
    context = {key: normal(value, source, build) for key, value in unit["context"].items()
               if key != "PrecompiledHeader"}
    if unit.get("pch", {}).get("PrecompiledHeader", "").lower() in ("use", "create"):
        context["ForcedIncludeFiles"] = ""
    return {"identity": unit["identity"], "output": normal(unit["output"], source, build),
            "project": normal(unit["project"], source, build), "context": context,
            "source_sha256": unit["source_sha256"]}


def common_world_base(original, source, build):
    project = build / "modules/world/opencv_world.vcxproj"
    semantic = set(original[0]["context"]) - {"PrecompiledHeader"}
    plain = set()
    for item in ET.parse(project).getroot().iter():
        if item.tag.rsplit("}", 1)[-1] != "ClCompile" or "Include" not in item.attrib:
            continue
        if any(child.tag.rsplit("}", 1)[-1] in semantic for child in item):
            continue
        include = item.attrib["Include"]
        if "$(" not in include and "%(" not in include:
            plain.add(path(include, project))
    candidates = [unit for unit in original if Path(unit["project"]).resolve() == project.resolve()
                  and Path(unit["file"]).resolve() in plain
                  and Path(unit["file"]).suffix.lower() in (".cpp", ".cxx", ".cc")]
    if not candidates:
        raise ValueError("No original WORLD CXX item without per-source semantic overrides")
    context = unit_key(candidates[0], source, build)["context"]
    if any(unit_key(unit, source, build)["context"] != context for unit in candidates):
        raise ValueError("Original native WORLD base contexts disagree")
    return {"identity": candidates[0]["identity"], "file_key": normal(candidates[0]["file"], source, build).replace("\\", "/").lower(),
            "tlog": WORLD_TLOG, "build": str(build), "context": context,
            "basis": "Native original WORLD CXX item without per-source semantic metadata overrides"}


def paired_units(original, combined, source, original_build, combined_build):
    left = [unit_key(unit, source, original_build) for unit in original]
    right = [unit_key(unit, source, combined_build) for unit in combined]
    if left != right:
        raise ValueError("Per-source/target context or output drift beyond roots/PCH bookkeeping")


def partition(units, source, build, world_base, expected_consumers=513):
    created = [unit for unit in units if producer(unit["file"])]
    consumers = [unit for unit in units if unit["pch"]["PrecompiledHeader"].lower() == "use"]
    if len(created) != 1 or len(consumers) != expected_consumers:
        raise ValueError(f"Expected one world PCH producer and {expected_consumers} CXX consumers")
    first = created[0]
    project = build / "modules/world/opencv_world.vcxproj"
    directory = (project.parent / "opencv_world.dir/Release").resolve()
    artifacts = [directory / name for name in ("cmake_pch.pch", "cmake_pch.obj")]
    wrapper = Path(first["file"]).parent / "Release/cmake_pch.hxx"
    for unit in units:
        mode = unit["pch"]["PrecompiledHeader"].lower()
        if unit not in created + consumers:
            if mode not in ("", "notusing") or "cmake_pch" in unit["pch"]["ForcedIncludeFiles"].lower():
                raise ValueError("PCH leaked to another C/static/dispatched/object source")
            continue
        if Path(unit["project"]).resolve() != project.resolve() or Path(unit["file"]).suffix.lower() not in (".cpp", ".cxx", ".cc"):
            raise ValueError("PCH is restricted to world CXX")
        expected = "create" if unit in created else "use"
        if mode != expected or Path(unit["output"]).parent != directory:
            raise ValueError("Wrong producer/consumer native IntDir")
        for field, value in (("PrecompiledHeaderFile", wrapper),
                             ("PrecompiledHeaderOutputFile", artifacts[0])):
            if path(unit["pch"][field], project) != value:
                raise ValueError("PCH output or canonical wrapper binding differs")
        forced = [value for value in unit["pch"]["ForcedIncludeFiles"].split(";") if value]
        if len(forced) != 1 or path(forced[0], project) != wrapper:
            raise ValueError("Unexpected forced include context")
        if unit["pch"]["MultiProcessorCompilation"].lower() != "true":
            raise ValueError("CL-server PCH requires native MP selection")
        if unit["pch"].get("EnableClServerMode", "").lower() not in ("", "true"):
            raise ValueError("Source metadata disables native CL-server selection")
    if unit_key(first, source, build)["context"] != world_base["context"]:
        raise ValueError("Producer CPP context differs from original native WORLD base")
    if Path(first["output"]) != artifacts[1]:
        raise ValueError("Unexpected native producer object binding")
    standard_header(wrapper)
    return [unit for unit in units if unit not in created], {
        "producer": first, "artifacts": [str(file) for file in artifacts],
        "wrapper": str(wrapper), "wrapper_sha256": hashlib.sha256(wrapper.read_bytes()).hexdigest(),
        "world_base": world_base,
        "headers": HEADERS, "consumers": len(consumers),
        "mp_scope": "Native evaluated MP=true and CL-server=true; MSBuild excludes /MP from CL command tracking. No resident/busy/global cap proof.",
    }


def tokens(command):
    return re.findall(r'(?:[^\s"]|"[^"]*")+', command)


def option(command, name):
    values = [token.replace('"', "")[len(name):] for token in tokens(command)
              if token.replace('"', "").startswith(name)]
    if len(values) != 1:
        raise ValueError("Missing or ambiguous native PCH option " + name)
    return values[0]


def command_key(entry, source, build):
    return (normal(entry["file"], source, build).replace("\\", "/").lower(),
            entry["tlog"].replace("\\", "/").lower())


def commands(entries, source, build, profile, principal, original):
    created = [entry for entry in entries if producer(entry["file"])]
    consumers = [entry for entry in entries if any(
        token.replace('"', "").startswith("/Yu") for token in tokens(entry["command"]))]
    if len(created) != 1 or len(consumers) != 513:
        raise ValueError("Actual timed producer/consumer count differs")
    pch, obj = map(Path, profile["artifacts"])
    wrapper = wrapper_input(profile)
    original_build = Path(profile["world_base"]["build"])
    baseline = {}
    for entry in original:
        key = command_key(entry, source, original_build)
        if key in baseline:
            raise ValueError("Ambiguous original source/target command binding")
        baseline[key] = entry
    base_key = profile["world_base"]["file_key"], profile["world_base"]["tlog"]
    if base_key not in baseline:
        raise ValueError("Missing original native WORLD base command")
    expected_context = principal(normal(baseline[base_key]["command"], source, original_build))
    if principal(normal(created[0]["command"], source, build)) != expected_context:
        raise ValueError("Actual producer CPP context differs from original WORLD base")
    for entry in created + consumers:
        project = build / "modules/world/opencv_world.vcxproj"
        if str(entry["tlog"]).replace("\\", "/").lower() != WORLD_TLOG:
            raise ValueError("Actual PCH command escaped world Release target")
        for flag, target in (("/Yc" if entry in created else "/Yu", wrapper), ("/Fp", pch), ("/FI", wrapper)):
            if path(option(entry["command"], flag), project) != target:
                raise ValueError("Actual Yc/Yu/Fp/FI path binding differs")
        if entry in consumers:
            key = command_key(entry, source, build)
            if key not in baseline or flags(entry, source, build) != flags(baseline[key], source, original_build):
                raise ValueError("Actual per-source/target consumer flag or macro drift")
        if "/Y-" in [token.replace('"', "") for token in tokens(entry["command"])]:
            raise ValueError("Actual compiler command disables PCH")
    for entry in entries:
        if entry not in created + consumers and any(
            token.replace('"', "").startswith(("/Yc", "/Yu")) or
            (token.replace('"', "").startswith("/FI") and "cmake_pch" in token.lower())
            for token in tokens(entry["command"])):
            raise ValueError("Actual PCH leaked outside world consumers")
    standard_header(wrapper)
    return [entry for entry in entries if entry not in created]


def flags(entry, source, build):
    result = []
    for token in tokens(entry["command"]):
        bare = token.replace('"', "")
        if bare.startswith(("/Yc", "/Yu", "/Fp")):
            continue
        if bare.startswith("/FI") and "cmake_pch.hxx" in bare.lower():
            continue
        # Source identities and actual native output bindings are checked separately.
        if not bare.startswith(("/", "-")) and "=" not in bare and Path(bare).suffix.lower() in (".cpp", ".cxx", ".cc", ".c"):
            continue
        result.append(normal(token, source, build))
    return result


def diagnostics(text):
    if re.search(r"(?i)\bC(?:4650|4651|4652|4653|4627|2855|2857|2858|4599)\b"
                 r"|precompiled header[^\n]*(?:ignor|not used|incompat)"
                 r"|(?:ignor|not used|incompat)[^\n]*precompiled header", text):
        raise ValueError("Ignored or incompatible PCH diagnostic")

"""Persist balanced Mac observations and fail closed on source/configuration drift."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

BASE = "71d3237a093b60a27601c20e9ee6c3e52154e8b1"
ORDER = ["warmup_baseline", "warmup_table", "baseline_1", "table_1", "table_2", "baseline_2"]
STABLE_MAKE_PATTERNS = (
    "**/Makefile", "**/Makefile2", "**/build.make", "**/flags.make", "**/link.txt",
    "**/Makefile.cmake", "**/DependInfo.cmake", "**/cmake_clean*.cmake",
    "**/cmake_install.cmake", "CMakeFiles/*/CMake*Compiler.cmake",
    "CMakeFiles/*/CMakeSystem.cmake",
)
CONFIGURED_TOOL = re.compile(
    r"^CMAKE_(?:COMMAND|MAKE_PROGRAM|C_COMPILER|CXX_COMPILER|ASM_COMPILER|"
    r"OBJC_COMPILER|OBJCXX_COMPILER|AR|RANLIB|LINKER):[^=]+=(.+)$", re.M
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen(root, expected=None):
    files = []
    for variant in ("base", "table"):
        build = root / (variant + "-build")
        for pattern in STABLE_MAKE_PATTERNS:
            files.extend(build.glob(pattern))
        cache = build / "CMakeCache.txt"
        files += [cache, build / "compile_commands.json", build / "cvconfig.h",
                  build / "opencv2/opencv_modules.hpp", build / "cv_cpu_config.h"]
        if cache.is_file():
            files.extend(Path(name) for name in CONFIGURED_TOOL.findall(cache.read_text(encoding="utf-8-sig"))
                         if name and not name.endswith("-NOTFOUND"))
    harness = Path(__file__).resolve().parents[1]
    for owner in (harness, root / "table-harness"):
        files += [owner / "benchmark.json"]
        for directory in ("scripts", "tests", "toolchains"):
            files.extend(file for file in (owner / directory).rglob("*")
                         if file.is_file() and "__pycache__" not in file.parts)
    files.extend(file for file in (harness / "ci").rglob("*")
                 if file.is_file() and "__pycache__" not in file.parts)
    # Keep prior paths in the snapshot so removals remain diagnosable.
    files.extend(Path(name) for name in (expected or {}))
    return {str(file): sha(file) if file.is_file() else None for file in sorted(set(files))}


def assert_frozen(expected, current, evidence, action):
    changed = {
        name: {"expected_sha256": digest, "actual_sha256": current[name]}
        for name, digest in expected.items()
        if current.get(name) is not None and current[name] != digest
    }
    added = {
        name: {"actual_sha256": digest} for name, digest in current.items()
        if name not in expected and digest is not None
    }
    missing = {
        name: {"expected_sha256": expected.get(name)} for name in expected.keys() | current.keys()
        if current.get(name) is None
    }
    if changed or added or missing:
        receipt = evidence / "frozen-input-drift.json"
        receipt.write_text(json.dumps({
            "action": action, "changed": changed, "added": added, "missing": missing,
            "scope": "Stable recipes/configuration/headers/tools/harness; dependency/progress outputs are not frozen.",
        }, indent=2, sort_keys=True), encoding="utf-8")
        raise ValueError(
            f"Frozen Mac workload inputs changed: {len(changed)} changed, "
            f"{len(added)} added, {len(missing)} missing; see {receipt.name}"
        )


def main():
    action, root, evidence, jobs = sys.argv[1:]
    root, evidence, jobs = Path(root), Path(evidence), int(jobs)
    path = evidence / "study.json"
    if action == "initialize":
        if path.exists():
            raise FileExistsError(path)
        study = {
            "status": "running", "profile": "matched-23-definitions", "jobs": jobs,
            "generator": "Unix Makefiles", "order": ORDER, "runs": [],
            "warmups": 2, "warmups_excluded": True, "frozen_sha256": frozen(root),
            "boundary": "Release make invocation only; provisioning/configure/clean/version/capture/smoke excluded.",
            "limitations": "Same-job source comparison, two scored observations each; hosted hardware uncontrolled. No cross-platform dependency/count equivalence, per-core normalization, parity prediction, numerical or runtime qualification. Text hash receipts are not retained-binary proof.",
        }
    else:
        study = json.loads(path.read_text())
    if action.startswith("failed:"):
        study.update(status="failed", shell_exit_code=int(action.split(":", 1)[1]))
        path.write_text(json.dumps(study, indent=2), encoding="utf-8")
        return
    try:
        provenance = json.loads((evidence / "source-variant.json").read_text())
        for variant, commit in (("base", BASE), ("table", provenance["local_snapshot_commit"])):
            for args, expected in ((("rev-parse", "HEAD"), commit),
                                   (("status", "--porcelain", "--untracked-files=no"), "")):
                value = subprocess.run(["git", "-C", str(root / variant), *args],
                                       check=True, text=True, capture_output=True).stdout.strip()
                if value != expected:
                    raise ValueError(f"Source pin/clean guard failed: {variant}")
        assert_frozen(study["frozen_sha256"], frozen(root, study["frozen_sha256"]), evidence, action)
        if action.startswith("record:"):
            label = action.split(":", 1)[1]
            if label != ORDER[len(study["runs"])]:
                raise ValueError("Unexpected observation order")
            directory = evidence / label
            timing = dict(line.split() for line in (directory / "time.log").read_text().splitlines())
            build = root / (("table" if "table" in label else "base") + "-build")
            libraries = [file for file in (build / "lib").glob("*.dylib") if not file.is_symlink()]
            if not libraries:
                raise ValueError("No built dynamic library to hash")
            (directory / "output-validation.json").write_text(json.dumps({
                "libraries_sha256": {file.name: sha(file) for file in libraries},
                "opencv_version_sha256": sha(build / "bin/opencv_version"),
                "smoke": (directory / "smoke.log").read_text(),
                "proof_scope": "Post-timer runner-local hash receipts, not retained-binary proof.",
            }, indent=2))
            study["runs"].append({
                "label": label, "directory": label, "configuration": "table" if "table" in label else "base",
                "warmup": label.startswith("warmup_"), "build_seconds": float(timing["real"]),
            })
        if action == "finish":
            if [run["label"] for run in study["runs"]] != ORDER:
                raise ValueError("Missing observations")
            study["status"] = "succeeded-awaiting-local-evidence-audit"
    except Exception as error:
        study.update(status="failed", error=str(error))
        raise
    finally:
        path.write_text(json.dumps(study, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

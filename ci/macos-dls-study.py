"""Persist balanced Mac observations and fail closed on source/configuration drift."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

BASE = "71d3237a093b60a27601c20e9ee6c3e52154e8b1"
ORDER = ["warmup_baseline", "warmup_table", "baseline_1", "table_1", "table_2", "baseline_2"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen(root):
    files = []
    for variant in ("base", "table"):
        build = root / (variant + "-build")
        files.extend(build.glob("**/Makefile"))
        files.extend(build.glob("**/*.make"))
        files.extend(build.glob("**/flags.make"))
        files += [build / "CMakeCache.txt", build / "compile_commands.json"]
    harness = Path(__file__).resolve().parents[1]
    for owner in (harness, root / "table-harness"):
        files += [owner / "benchmark.json"]
        for directory in ("scripts", "tests", "toolchains"):
            files.extend(file for file in (owner / directory).rglob("*")
                         if file.is_file() and "__pycache__" not in file.parts)
    files.extend(file for file in (harness / "ci").rglob("*")
                 if file.is_file() and "__pycache__" not in file.parts)
    return {str(file): sha(file) for file in files}


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
        if frozen(root) != study["frozen_sha256"]:
            raise ValueError("Frozen Mac workload inputs changed")
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

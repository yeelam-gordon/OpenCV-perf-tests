"""Verify a public-base, one-path variant and create a runner-local clean pin."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

BASE = "71d3237a093b60a27601c20e9ee6c3e52154e8b1"
SOURCE = "modules/calib3d/src/dls.cpp"
BOT = "github-actions[bot]"
EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
MESSAGE = (
    "Local DLS source-table experiment (not for publication)\n\n"
    "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>\n"
)


def git(root, *args, **kwargs):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True,
        text=True, **kwargs,
    ).stdout.strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data["base_commit"] != BASE or data["path"] != SOURCE:
        raise ValueError("Only the public 4.10.0 base and DLS source path are allowed")
    if data["patch"] != "patches/dls-source-table.patch":
        raise ValueError("Unexpected patch path")
    for key in ("base_commit", "base_tree", "base_blob", "variant_blob", "variant_tree"):
        if len(data[key]) != 40 or any(c not in "0123456789abcdef" for c in data[key]):
            raise ValueError(f"Invalid Git identity: {key}")
    patch = path.parent / data["patch"]
    if sha(patch) != data["patch_sha256"]:
        raise ValueError("Patch SHA256 mismatch")
    return data, patch


def copy_harness(harness, destination, snapshot):
    config_path = harness / "benchmark.json"
    original = config_path.read_bytes()
    config = json.loads(original)
    if config["opencv_commit"] != BASE or config["opencv_tag"] != "4.10.0" or len(config["cmake_flags"]) != 23:
        raise ValueError("Unexpected control workload pin/tag/23 definitions")
    files = git(harness, "ls-files", "-z", "--", "scripts", "tests", "toolchains", "benchmark.json").split("\0")
    destination.mkdir(parents=True, exist_ok=False)
    copied = {}
    for name in files:
        if not name:
            continue
        source = harness / name
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied[name] = sha(target)
    target_config = destination / "benchmark.json"
    # Keep every byte except the one pin, including the control's newline convention.
    changed = original.replace(BASE.encode(), snapshot.encode())
    target_config.write_bytes(changed)
    expected = dict(config, opencv_commit=snapshot)
    if json.loads(changed) != expected or config_path.read_bytes() != original:
        raise ValueError("Candidate configuration isolation failed")
    for name, digest in copied.items():
        if name != "benchmark.json" and sha(destination / name) != digest:
            raise ValueError(f"Harness copy mismatch: {name}")
    return {
        "control_config_sha256": hashlib.sha256(original).hexdigest(),
        "candidate_config_sha256": sha(target_config),
        "copied_control_sha256": copied,
        "changed_config_fields": ["opencv_commit"],
    }


def prepare(base, candidate, harness, candidate_harness, manifest_path, receipt):
    data, patch = manifest(manifest_path)
    if any(p.exists() for p in (candidate, candidate_harness, receipt)):
        raise FileExistsError("Candidate, harness and receipt must all be fresh")
    if git(base, "rev-parse", "HEAD") != BASE:
        raise ValueError("Base HEAD mismatch")
    if git(base, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Dirty public base")
    if git(base, "rev-parse", "HEAD^{tree}") != data["base_tree"]:
        raise ValueError("Base tree mismatch")
    if git(base, "rev-parse", f"HEAD:{SOURCE}") != data["base_blob"]:
        raise ValueError("Base blob mismatch")
    git(base, "worktree", "add", "--detach", str(candidate), BASE)
    git(candidate, "apply", "--check", "--index", str(patch.resolve()))
    git(candidate, "apply", "--index", str(patch.resolve()))
    if git(candidate, "diff", "--cached", "--name-only", "--no-renames").splitlines() != [SOURCE]:
        raise ValueError("Variant must change exactly one allowed file")
    tree = git(candidate, "write-tree")
    if tree != data["variant_tree"] or git(candidate, "rev-parse", f":{SOURCE}") != data["variant_blob"]:
        raise ValueError("Variant index tree/blob mismatch")
    env = dict(os.environ, GIT_AUTHOR_NAME=BOT, GIT_AUTHOR_EMAIL=EMAIL,
               GIT_COMMITTER_NAME=BOT, GIT_COMMITTER_EMAIL=EMAIL)
    snapshot = git(candidate, "-c", "commit.gpgsign=false", "commit-tree", tree, "-p", BASE,
                   input=MESSAGE, env=env)
    git(candidate, "reset", "--hard", snapshot)
    if git(candidate, "status", "--porcelain") or git(candidate, "rev-parse", "HEAD^{tree}") != tree:
        raise ValueError("Candidate is not a clean, pinned snapshot")
    isolation = copy_harness(harness, candidate_harness, snapshot)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({
        **data, "local_snapshot_commit": snapshot, "harness": isolation,
        "source_raw_sha256": sha(candidate / SOURCE),
        "identity": "Git blobs/trees are canonical across CRLF/LF; raw source SHA is runner-local only.",
        "publication": "Local commit only; public upstream base plus verified patch; no source fork.",
    }, indent=2), encoding="utf-8")
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "candidate", "harness", "candidate-harness", "receipt"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("dls-source-variant.json"))
    args = parser.parse_args()
    print(prepare(args.base.resolve(), args.candidate.resolve(), args.harness.resolve(),
                  args.candidate_harness.resolve(), args.manifest.resolve(), args.receipt.resolve()))


if __name__ == "__main__":
    main()

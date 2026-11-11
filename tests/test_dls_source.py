"""Bounded no-build/no-network patch, identity and harness-isolation guard tests."""

import importlib.util
import json
from pathlib import Path
import shutil
import stat
import subprocess
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dls_prepare", ROOT / "ci/prepare-dls-source.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def remove_fixture(path):
    def writable(function, name, error):
        Path(name).chmod(stat.S_IWRITE)
        function(name)
    shutil.rmtree(path, onerror=writable)


class SourceGuardTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".work" / ("dls-guard-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.addCleanup(remove_fixture, self.root)
        self.base = self.root / "base"
        self.base.mkdir()
        prepare.git(self.base, "init", "-b", "fixture")
        prepare.git(self.base, "config", "user.name", prepare.BOT)
        prepare.git(self.base, "config", "user.email", prepare.EMAIL)
        source = self.base / prepare.SOURCE
        source.parent.mkdir(parents=True)
        source.write_text("original\n")
        prepare.git(self.base, "add", ".")
        prepare.git(self.base, "-c", "commit.gpgsign=false", "commit", "-m", "Public synthetic fixture")
        self.commit = prepare.git(self.base, "rev-parse", "HEAD")
        self.base_patch = patch.object(prepare, "BASE", self.commit)
        self.base_patch.start()
        self.addCleanup(self.base_patch.stop)
        self.data = {
            "base_commit": self.commit, "path": prepare.SOURCE,
            "base_tree": prepare.git(self.base, "rev-parse", "HEAD^{tree}"),
            "base_blob": prepare.git(self.base, "rev-parse", f"HEAD:{prepare.SOURCE}"),
            "patch": "patches/dls-source-table.patch",
        }
        source.write_text("table\n")
        prepare.git(self.base, "add", ".")
        self.data["variant_tree"] = prepare.git(self.base, "write-tree")
        self.data["variant_blob"] = prepare.git(self.base, "rev-parse", f":{prepare.SOURCE}")
        self.patch_path = self.root / self.data["patch"]
        self.patch_path.parent.mkdir()
        subprocess.run(["git", "-C", str(self.base), "diff", "--cached", "--binary", "--full-index",
                        "--output=" + str(self.patch_path)], check=True)
        prepare.git(self.base, "reset", "--hard", self.commit)
        self.data["patch_sha256"] = prepare.sha(self.patch_path)
        self.manifest = self.root / "variant.json"
        self.save()
        self.harness = self.root / "harness"
        self.harness.mkdir()
        prepare.git(self.harness, "init", "-b", "fixture")
        config = {"opencv_commit": self.commit, "opencv_tag": "4.10.0",
                  "cmake_flags": [f"-DFIXTURE_{index}=ON" for index in range(23)]}
        (self.harness / "benchmark.json").write_text(json.dumps(config))
        for directory in ("scripts", "tests", "toolchains"):
            (self.harness / directory).mkdir()
            (self.harness / directory / "fixture.txt").write_text("unchanged\n")
        prepare.git(self.harness, "add", ".")

    def save(self):
        self.manifest.write_text(json.dumps(self.data))

    def run_prepare(self):
        return prepare.prepare(self.base, self.root / "candidate", self.harness,
                               self.root / "candidate-harness", self.manifest, self.root / "receipt.json")

    def test_clean_pin_and_exact_harness_config_isolation(self):
        original = (self.harness / "benchmark.json").read_bytes()
        commit = self.run_prepare()
        candidate = self.root / "candidate"
        self.assertEqual(prepare.git(candidate, "status", "--porcelain"), "")
        self.assertEqual(prepare.git(candidate, "rev-parse", "HEAD^{tree}"), self.data["variant_tree"])
        self.assertEqual(prepare.git(candidate, "show", "-s", "--format=%an|%ae"), prepare.BOT + "|" + prepare.EMAIL)
        self.assertIn("Co-authored-by: Copilot", prepare.git(candidate, "show", "-s", "--format=%B"))
        changed = (self.root / "candidate-harness/benchmark.json").read_bytes()
        self.assertEqual(changed, original.replace(self.commit.encode(), commit.encode()))
        self.assertEqual((self.harness / "benchmark.json").read_bytes(), original)
        for directory in ("scripts", "tests", "toolchains"):
            self.assertEqual((self.root / "candidate-harness" / directory / "fixture.txt").read_bytes(),
                             (self.harness / directory / "fixture.txt").read_bytes())

    def test_bad_patch_digest(self):
        self.patch_path.write_bytes(self.patch_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "Patch SHA256"):
            self.run_prepare()

    def test_path_guard(self):
        self.data["path"] = "modules/core/src/other.cpp"
        self.save()
        with self.assertRaisesRegex(ValueError, "Only the public"):
            self.run_prepare()

    def test_patch_path_guard(self):
        self.data["patch"] = "../outside.patch"
        self.save()
        with self.assertRaisesRegex(ValueError, "Unexpected patch path"):
            self.run_prepare()

    def test_base_sha_guard(self):
        self.data["base_commit"] = "0" * 40
        self.save()
        with self.assertRaisesRegex(ValueError, "Only the public"):
            self.run_prepare()

    def test_tree_guard(self):
        self.data["variant_tree"] = "0" * 40
        self.save()
        with self.assertRaisesRegex(ValueError, "index tree/blob"):
            self.run_prepare()

    def test_one_file_guard_even_with_matching_patch_digest(self):
        (self.base / "extra.txt").write_text("unapproved\n")
        prepare.git(self.base, "add", "extra.txt")
        extra = subprocess.run(["git", "-C", str(self.base), "diff", "--cached", "--binary", "--full-index"],
                               check=True, capture_output=True).stdout
        self.patch_path.write_bytes(self.patch_path.read_bytes() + extra)
        self.data["patch_sha256"] = prepare.sha(self.patch_path)
        self.save()
        prepare.git(self.base, "reset", "--hard", self.commit)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.run_prepare()

    def test_dirty_control_guard(self):
        (self.base / prepare.SOURCE).write_text("unapproved\n")
        with self.assertRaisesRegex(ValueError, "Dirty public base"):
            self.run_prepare()

    def test_control_config_wrong_pin_is_not_rewritten(self):
        path = self.harness / "benchmark.json"
        before = path.read_text().replace(self.commit, "0" * 40)
        path.write_text(before)
        with self.assertRaisesRegex(ValueError, "control workload"):
            self.run_prepare()
        self.assertEqual(path.read_text(), before)


if __name__ == "__main__":
    unittest.main()

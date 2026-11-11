import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("macos_dls_study", ROOT / "ci/macos-dls-study.py")
mac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mac)


class MacFreezeTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / ".work" / ("macos-freeze-" + uuid.uuid4().hex)
        self.root = self.directory / "study"
        self.evidence = self.directory / "evidence"
        self.harness = self.directory / "harness"
        self.evidence.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.directory)
        self.snapshot = "1" * 40
        self.write(self.evidence / "source-variant.json", json.dumps({"local_snapshot_commit": self.snapshot}))
        self.tool = self.directory / "tools/compiler"
        self.write(self.tool, "fixture tool, never executed")
        for owner in (self.harness, self.root / "table-harness"):
            for name in ("benchmark.json", "scripts/run.ps1", "tests/check.py",
                         "toolchains/profile.json", "ci/check.py"):
                self.write(owner / name, "stable harness fixture")
        for variant in ("base", "table"):
            build = self.root / (variant + "-build")
            for name in (
                "Makefile", "CMakeFiles/Makefile2", "CMakeFiles/Makefile.cmake",
                "modules/videoio/Makefile", "modules/videoio/CMakeFiles/videoio.dir/build.make",
                "modules/videoio/CMakeFiles/videoio.dir/flags.make",
                "modules/videoio/CMakeFiles/videoio.dir/link.txt",
                "modules/videoio/CMakeFiles/videoio.dir/DependInfo.cmake",
                "modules/videoio/CMakeFiles/videoio.dir/cmake_clean.cmake",
                "cmake_install.cmake", "compile_commands.json", "cvconfig.h",
                "opencv2/opencv_modules.hpp", "cv_cpu_config.h",
                "CMakeFiles/4.4.4/CMakeCXXCompiler.cmake",
            ):
                self.write(build / name, "stable configured fixture")
            self.write(build / "CMakeCache.txt", f"CMAKE_CXX_COMPILER:FILEPATH={self.tool}\n")
            for name in ("compiler_depend.make", "depend.make", "progress.make"):
                self.write(build / "modules/videoio/CMakeFiles/videoio.dir" / name, "# initial state\n")
        self.file_patch = patch.object(mac, "__file__", str(self.harness / "ci/macos-dls-study.py"))
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def run_action(self, action):
        def git_result(args, **kwargs):
            value = ""
            if args[3] == "rev-parse":
                value = mac.BASE if Path(args[2]).name == "base" else self.snapshot
            return subprocess.CompletedProcess(args, 0, stdout=value)

        with patch.object(sys, "argv", ["macos-dls-study.py", action, str(self.root), str(self.evidence), "4"]), \
                patch.object(mac.subprocess, "run", side_effect=git_result):
            mac.main()

    def populate_dependencies(self):
        for variant in ("base", "table"):
            build = self.root / (variant + "-build")
            for name in ("compiler_depend.make", "depend.make", "progress.make"):
                self.write(build / "modules/videoio/CMakeFiles/videoio.dir" / name,
                           "# populated by first compilation\nsource.mm.o: source.mm header.hpp\n")
                self.write(build / "new-target/CMakeFiles/new.dir" / name, "# new dependency/progress cache\n")
            self.write(build / "modules/videoio/CMakeFiles/videoio.dir/compiler_depend.internal", "new cache")
            self.write(build / "CMakeFiles/progress.marks", "1\n")

    def test_first_warmup_dependency_mutations_and_additions_are_accepted(self):
        self.run_action("initialize")
        original = json.loads((self.evidence / "study.json").read_text())["frozen_sha256"]
        self.populate_dependencies()
        build = self.root / "base-build"
        self.write(build / "lib/libopencv_world.dylib", "fixture library, never loaded")
        self.write(build / "bin/opencv_version", "fixture executable, never executed")
        run = self.evidence / "warmup_baseline"
        self.write(run / "time.log", "real 12.5\nuser 40\nsys 2\n")
        self.write(run / "smoke.log", "image and matrix smoke checks passed\n")
        self.run_action("record:warmup_baseline")
        study = json.loads((self.evidence / "study.json").read_text())
        self.assertEqual(study["frozen_sha256"], original)
        self.assertEqual(len(study["runs"]), 1)
        self.assertTrue(study["runs"][0]["warmup"])
        self.assertEqual(study["runs"][0]["build_seconds"], 12.5)
        self.assertFalse((self.evidence / "frozen-input-drift.json").exists())

    def test_stable_flags_recipes_cache_headers_and_tools_still_fail(self):
        files = [
            self.root / "base-build/modules/videoio/CMakeFiles/videoio.dir/flags.make",
            self.root / "base-build/modules/videoio/CMakeFiles/videoio.dir/build.make",
            self.root / "base-build/Makefile",
            self.root / "base-build/CMakeFiles/Makefile2",
            self.root / "base-build/modules/videoio/CMakeFiles/videoio.dir/link.txt",
            self.root / "base-build/CMakeCache.txt",
            self.root / "base-build/compile_commands.json",
            self.root / "base-build/cvconfig.h",
            self.root / "base-build/opencv2/opencv_modules.hpp",
            self.root / "base-build/cv_cpu_config.h",
            self.root / "base-build/CMakeFiles/4.4.4/CMakeCXXCompiler.cmake",
            self.harness / "scripts/run.ps1", self.tool,
        ]
        for path in files:
            with self.subTest(path=path.relative_to(self.directory)):
                expected = mac.frozen(self.root)
                original = path.read_bytes()
                path.write_bytes(original + b"\nchanged stable input\n")
                try:
                    with self.assertRaisesRegex(ValueError, "1 changed, 0 added, 0 missing"):
                        mac.assert_frozen(expected, mac.frozen(self.root, expected), self.evidence, "guard")
                    drift = json.loads((self.evidence / "frozen-input-drift.json").read_text())
                    self.assertEqual(drift["changed"][str(path)], {
                        "expected_sha256": expected[str(path)], "actual_sha256": mac.sha(path),
                    })
                finally:
                    path.write_bytes(original)

    def test_added_recipe_and_missing_cpu_header_have_precise_diagnostics(self):
        self.run_action("initialize")
        removed = self.root / "table-build/cv_cpu_config.h"
        old_hash = mac.sha(removed)
        removed.unlink()
        added = self.root / "table-build/new-target/build.make"
        self.write(added, "new stable recipe")
        with self.assertRaisesRegex(ValueError, "0 changed, 1 added, 1 missing"):
            self.run_action("guard")
        drift = json.loads((self.evidence / "frozen-input-drift.json").read_text())
        self.assertEqual(drift["changed"], {})
        self.assertEqual(drift["added"], {str(added): {"actual_sha256": mac.sha(added)}})
        self.assertEqual(drift["missing"], {str(removed): {"expected_sha256": old_hash}})
        study = json.loads((self.evidence / "study.json").read_text())
        self.assertEqual(study["status"], "failed")
        self.assertIn("frozen-input-drift.json", study["error"])

    def test_missing_required_header_at_initialization_fails_closed(self):
        (self.root / "base-build/cv_cpu_config.h").unlink()
        with self.assertRaisesRegex(ValueError, "1 missing"):
            self.run_action("initialize")
        self.assertEqual(json.loads((self.evidence / "study.json").read_text())["status"], "failed")


if __name__ == "__main__":
    unittest.main()

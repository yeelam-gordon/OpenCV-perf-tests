import contextlib
import hashlib
import io
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class GeneratorSmokeEvidenceTests(unittest.TestCase):
    def exercise(self, result=None, failure=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        script = root / "ci/confirm-generator-outputs.py"
        script.parent.mkdir()
        shutil.copy2(Path(__file__).resolve().parents[1] / "ci" / script.name, script)
        exe = root / ".work/smoke_MSVC2026_MSBuild/Release/opencv_smoke.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"fixture executable, never executed")
        study = root / "evidence"
        run = study / "run"
        dll = run / "runtime-binaries/opencv_world4100.dll"
        dll.parent.mkdir(parents=True)
        dll.write_bytes(b"fixture DLL")
        (study / "study.json").write_text(json.dumps({"runs": [{"label": "case", "directory": "run"}]}))
        (run / "output-validation.json").write_text(json.dumps({
            "image": {"machine": "0xaa64", "sha256": hashlib.sha256(dll.read_bytes()).hexdigest()}
        }))
        with patch.object(sys, "argv", [str(script), str(study)]), \
                patch("subprocess.run", return_value=result, side_effect=failure), \
                contextlib.redirect_stdout(io.StringIO()):
            if failure is None and result.returncode == 0 and "checks passed" in result.stdout:
                runpy.run_path(str(script), run_name="__main__")
            else:
                with self.assertRaises(RuntimeError):
                    runpy.run_path(str(script), run_name="__main__")
        receipt = json.loads((run / "smoke-captured.json").read_text())
        self.assertEqual(json.loads((study / "output-smoke-captured.json").read_text()), [receipt])
        return receipt

    def test_nonzero_exit_preserves_both_streams(self):
        receipt = self.exercise(subprocess.CompletedProcess([], 7, "failed assertion", "DLL detail"))
        self.assertEqual(receipt["exit_code"], 7)
        self.assertEqual((receipt["stdout"], receipt["stderr"]), ("failed assertion", "DLL detail"))
        self.assertEqual(receipt["status"], "failed")

    def test_timeout_preserves_partial_byte_streams(self):
        receipt = self.exercise(failure=subprocess.TimeoutExpired(
            ["fixture"], 60, output=b"partial stdout", stderr=b"timeout detail"
        ))
        self.assertEqual(receipt["status"], "timed_out")
        self.assertEqual((receipt["stdout"], receipt["stderr"]), ("partial stdout", "timeout detail"))

    def test_missing_marker_is_recorded_before_failure(self):
        receipt = self.exercise(subprocess.CompletedProcess([], 0, "unexpected output", ""))
        self.assertEqual(receipt["exit_code"], 0)
        self.assertEqual(receipt["stdout"], "unexpected output")
        self.assertEqual(receipt["status"], "failed")

    def test_launch_failure_is_recorded(self):
        receipt = self.exercise(failure=OSError("cannot launch fixture"))
        self.assertEqual(receipt["status"], "launch_failed")
        self.assertIn("cannot launch fixture", receipt["error"])

    def test_success_retains_verified_identity(self):
        receipt = self.exercise(subprocess.CompletedProcess(
            [], 0, "image and matrix smoke checks passed", ""
        ))
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["dll_sha256"], hashlib.sha256(b"fixture DLL").hexdigest())


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dls_evidence", ROOT / "ci/dls-source-evidence.py")
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


class WorkloadEvidenceTests(unittest.TestCase):
    def test_grouped_msbuild_sources_and_ninja_have_same_units_and_flags(self):
        source, build = ROOT / ".work/source", ROOT / ".work/source/build"
        files = [source / evidence.SOURCE, source / "modules/core/src/matrix.cpp"]
        command = '/D "NDEBUG" /D_MBCS /D "CMAKE_INTDIR=\\"Release\\"" /EHa /fp:precise /MD'
        msbuild = {"world.tlog|^" + "|".join(str(file).upper() for file in files): command}
        ninja = [{"file": str(file), "output": str(file) + ".obj",
                  "command": "-DNDEBUG -D_MBCS /EHa /fp:precise /MD"} for file in files]
        left, left_world = evidence.units(msbuild, source, build, "MSBuild")
        right, right_world = evidence.units(ninja, source, build, "Ninja")
        self.assertEqual(sorted(file for file, _ in left), sorted(file for file, _ in right))
        self.assertEqual(left_world, right_world)

    def test_generated_sources_are_build_relative_not_candidate_directory_names(self):
        source, build = ROOT / ".work/table", ROOT / ".work/table/build"
        self.assertEqual(evidence.identity(build / "modules/core/math.neon.cpp", source, build),
                         "generated/modules/core/math.neon.cpp")

    def test_outside_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside configured"):
            evidence.identity(ROOT / "outside.cpp", ROOT / "source", ROOT / "build")

    def test_dls_command_required(self):
        source, build = ROOT / ".work/source", ROOT / ".work/build"
        with self.assertRaisesRegex(ValueError, "DLS source"):
            evidence.units([{"file": str(source / "modules/core/src/matrix.cpp"), "output": "matrix.cpp.obj",
                             "command": "cl /MD"}],
                           source, build, "Ninja")

    def test_ninja_custom_cpp_generator_is_not_a_compiler_unit(self):
        source, build = ROOT / ".work/source", ROOT / ".work/build"
        records, _ = evidence.units([
            {"file": str(source / evidence.SOURCE), "output": "dls.cpp.obj", "command": "cl /MD"},
            {"file": "modules/js/generated.cpp", "output": "gen_js", "command": ""},
        ], source, build, "Ninja")
        self.assertEqual(len(records), 1)

    def test_lowercase_diagnostics_option_is_not_a_preprocessor_definition(self):
        self.assertEqual(evidence.principal("/diagnostics:column /D_WIN32")["macros"], ["_WIN32"])

    def test_clang_dependency_flag_is_not_msvc_crt(self):
        self.assertEqual(evidence.principal("clang++ -DNDEBUG -MD", msvc=False)["crt"], [])

    def capture_language(self, suffix, missing=False):
        root = ROOT / ".work" / ("dls-language-" + uuid.uuid4().hex)
        source, build, run = root / "source", root / "build", root / "run"
        for directory in (source, build, run):
            directory.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root)
        for header in evidence.HEADERS:
            path = build / header
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture header\n")
        language_source = "modules/videoio/src/capture" + suffix
        commands = []
        for name in (evidence.SOURCE, language_source):
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture source, never compiled\n")
            output = path.name + ".o"
            if not (missing and name == language_source):
                (build / output).write_bytes(b"fixture object, never executed")
            commands.append({
                "file": str(path), "directory": str(build),
                "command": f'clang -DFEATURE_TEST=1 -MD -c "{path}" -o {output}',
            })
        (run / "commands.json").write_text(json.dumps(commands))

        def git_result(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout="" if args[3] == "status" else "0" * 40)

        with patch.object(evidence.subprocess, "run", side_effect=git_result):
            evidence.capture(source, build, run, "Make")
        return evidence.load(run / "source-workload.json"), language_source.lower()

    def test_make_objective_c_and_cpp_sources_match_actual_object_accounting(self):
        for suffix in (".m", ".mm"):
            with self.subTest(suffix=suffix):
                record, source = self.capture_language(suffix)
                self.assertEqual((record["unit_count"], record["actual_object_count"]), (2, 2))
                self.assertEqual(record["units"], sorted([evidence.SOURCE, source]))
                self.assertEqual(dict(record["world_principal"])[source]["macros"], ["FEATURE_TEST=1"])

    def test_make_assembly_sources_match_actual_object_accounting(self):
        for suffix in (".S", ".s", ".asm"):
            with self.subTest(suffix=suffix):
                record, source = self.capture_language(suffix)
                self.assertEqual((record["unit_count"], record["actual_object_count"]), (2, 2))
                self.assertEqual(record["units"], sorted([evidence.SOURCE, source]))
                self.assertIn(source, dict(record["world_principal"]))

    def test_required_objective_cpp_and_assembly_objects_cannot_be_omitted(self):
        for suffix in (".mm", ".S"):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, "not actually built"):
                self.capture_language(suffix, missing=True)


if __name__ == "__main__":
    unittest.main()

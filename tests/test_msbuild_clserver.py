"""No OpenCV build, install, source commit, or network guard tests."""

import importlib.util
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("clserver", ROOT / "ci/msbuild-clserver-evidence.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


class ClServerGuards(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".work" / ("clserver-test-" + uuid.uuid4().hex)
        self.source, self.build, self.run = [self.root / name for name in ("source", "build", "run")]
        for directory in (self.source, self.build, self.run):
            directory.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)

    def test_exact_base_tree_blob_and_clean_required(self):
        expected = [study.BASE, study.TREE, study.BLOB, ""]
        with patch.object(study, "git", side_effect=expected):
            study.source_guard(self.source)
        for index in range(4):
            wrong = list(expected)
            wrong[index] = "changed"
            with patch.object(study, "git", side_effect=wrong), self.assertRaises(ValueError):
                study.source_guard(self.source)

    def test_spacefree_temp_must_remain_under_owned_runner_root(self):
        owner = Path(r"C:\runner-temp") if os.name == "nt" else Path("/runner-temp")
        study.temp_guard(owner / "compiler-run", owner)
        for temp in (owner / "compiler run", owner, owner.parent / "outside"):
            with self.subTest(temp=temp), self.assertRaises(ValueError):
                study.temp_guard(temp, owner)

    @unittest.skipUnless(os.name == "nt", "Windows native object paths")
    def test_native_Fo_binding_has_no_directory_search_fallback(self):
        entry = {
            "file": str(self.source / study.source_evidence.SOURCE),
            "tlog": "modules/world/opencv_world.dir/Release/opencv_world.tlog/CL.command.1.tlog",
            "command": '/Fo"opencv_world.dir\\Release\\\\" /MD /EHa',
        }
        output = study.native_outputs([entry], self.build)[0][1]
        self.assertEqual(output, (self.build / "modules/world/opencv_world.dir/Release/dls.obj").resolve())
        for command in ("/MD", '/Fo"one.obj" /Fo"two.obj"', '/Fo"C:\\outside.obj"'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                study.native_outputs([dict(entry, command=command)], self.build)

    def test_native_clean_rejects_residue_and_missing_units(self):
        plan = self.run / "plan.json"
        units = [{"output": str(self.build / f"unit{i}.obj")} for i in range(1015)]
        temp = str(self.root / "process-temp")
        environment = {"TEMP": temp, "TMP": temp}
        data = {"cases": {"original": {"units": units}}, "features": {}, "compiler_temp": temp}
        study.write(plan, data)
        with patch.object(study, "source_guard"), patch.dict(os.environ, environment):
            study.clean(self.source, self.build, self.run, plan, "MSBuild")
        for file in (self.build / "unit0.obj", self.build / study.BINARIES[0]):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"synthetic stale native output")
            with patch.object(study, "source_guard"), patch.dict(os.environ, environment), \
                    self.assertRaisesRegex(ValueError, "still present"):
                study.clean(self.source, self.build, self.run, plan, "MSBuild")
            file.unlink()
        data["cases"]["original"]["units"].pop()
        study.write(plan, data)
        with patch.object(study, "source_guard"), patch.dict(os.environ, environment), \
                self.assertRaisesRegex(ValueError, "1015"):
            study.clean(self.source, self.build, self.run, plan, "MSBuild")

    def test_missing_and_offclock_compiler_outputs_rejected(self):
        output = self.build / "unit.obj"
        output.write_bytes(b"synthetic object, not native code")
        now = time.time()
        owned = {key: datetime.fromtimestamp(value, timezone.utc).isoformat()
                 for key, value in (("started_at", now - 2), ("finished_at", now + 2))}
        study.clock_outputs([output], owned)
        os.utime(output, (now - 100, now - 100))
        with self.assertRaisesRegex(ValueError, "inside owned clock"):
            study.clock_outputs([output], owned)
        output.unlink()
        with self.assertRaisesRegex(ValueError, "inside owned clock"):
            study.clock_outputs([output], owned)

    def test_make_includes_objcxx_and_assembly_and_rejects_leftover(self):
        entries = [{"directory": str(self.build), "file": "unit.cpp", "command": f"clang -c unit.cpp -o u{i}.o"}
                   for i in range(908)]
        entries[0] = dict(entries[0], file="capture.mm")
        entries[1] = dict(entries[1], file="kernel.S")
        study.write(self.build / "compile_commands.json", entries)
        with patch.object(study, "source_guard"):
            study.clean(self.source, self.build, self.run, None, "Make")
        (self.build / "u1.o").write_bytes(b"synthetic assembly object")
        with patch.object(study, "source_guard"), self.assertRaisesRegex(ValueError, "still present"):
            study.clean(self.source, self.build, self.run, None, "Make")

    def test_source_features_flags_and_counts_cannot_change(self):
        record = {"source_commit": study.BASE, "source_tree": study.TREE, "source_blob": study.BLOB,
                  "unit_count": 1015, "units": ["fixture"], "headers_sha256": {"cpu": "same"},
                  "world_principal": [["fixture", {"eh": ["EHa"], "fp": ["fp:precise"], "crt": ["MD"],
                                                      "macros": ["_WINDLL"]}]]}
        runs = [{"label": name, "directory": name, "configuration": name, "warmup": False, "build_seconds": 1}
                for name in ("original", "server")]
        study.write(self.run / "study.json", {"runs": runs})
        for name in ("original", "server"):
            directory = self.run / name
            directory.mkdir()
            study.write(directory / "source-workload.json", record)
            study.write(directory / "compiled-inputs.json", [{"source": "fixture", "source_sha256": "same", "suffix": ".mm"}])
        study.compare(self.run, "MSBuild")
        for key, value in (("unit_count", 1014), ("source_tree", "patched"), ("headers_sha256", {}),
                           ("world_principal", [])):
            study.write(self.run / "server/source-workload.json", dict(record, **{key: value}))
            with self.subTest(key=key), self.assertRaises(ValueError):
                study.compare(self.run, "MSBuild")

    @unittest.skipUnless(os.name == "nt", "Windows native MSBuild evaluation")
    def test_real_native_query_evaluates_only_requested_profile_without_targets(self):
        msbuild = os.environ.get("STUDY_TEST_MSBUILD")
        if not msbuild:
            self.skipTest("Native MSBuild not supplied; no installation attempted")
        project = self.build / "fixture.vcxproj"
        project.write_text('''<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
<PropertyGroup><IntDir>fixture.dir\\Release\\</IntDir></PropertyGroup>
<ItemDefinitionGroup><ClCompile><ObjectFileName>$(IntDir)</ObjectFileName></ClCompile></ItemDefinitionGroup>
<ItemGroup><ClCompile Include="fixture.cpp"/></ItemGroup>
<Target Name="Build"><Error Text="A build target must never execute in this fixture"/></Target>
</Project>''')
        original = study.query(msbuild, project, [])
        server = study.query(msbuild, project, study.SERVER)
        self.assertEqual(original["Properties"]["EnableClServerMode"], "")
        self.assertEqual(server["Properties"]["EnableClServerMode"], "true")
        self.assertEqual(server["Properties"]["MultiProcMaxCount"], "4")
        self.assertEqual(original["Items"], server["Items"])
        self.assertEqual(original["Items"]["ClCompile"][0]["ObjectFileName"], "fixture.dir\\Release\\")

    @unittest.skipUnless(os.name == "nt", "Windows native plan paths")
    def test_preclock_plan_rejects_profile_count_and_compiler_context_drift(self):
        project = self.build / "modules/world/opencv_world.vcxproj"
        project.parent.mkdir(parents=True)
        project.write_text("<Project/>")
        stock = self.root / "vs/MSBuild/Microsoft/VC/v180/Microsoft.CppCommon.targets"
        stock.parent.mkdir(parents=True)
        stock.write_text("synthetic target-hash fixture, never imported")
        setup = {"generator": "MSBuild", "compiler_id": "MSVC", "architecture": "arm64",
                 "build_engine": {"path": "fixture-msbuild"}, "visual_studio": {"path": str(self.root / "vs")}}
        study.write(self.build / "benchmark-setup.json", setup)
        for header in study.source_evidence.HEADERS:
            path = self.build / header
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("unchanged feature fixture")
        items = []
        for index in range(1015):
            name = study.source_evidence.SOURCE if index == 0 else (
                f"3rdparty/openexr/u{index}.cpp" if index >= 908 else f"modules/core/src/u{index}.cpp")
            items.append({"FullPath": str(self.source / name), "ObjectFileName": f"obj\\u{index}.obj"})
        defect = None

        def query(msbuild, configured_project, settings):
            candidate = bool(settings)
            units = [dict(item) for item in items]
            profile = dict(zip(study.PROPERTIES, ("true", "4", "true", "true") if candidate else ("", "", "", "")))
            if candidate and defect == "count":
                units.pop()
            if candidate and defect == "context":
                units[0]["AdditionalOptions"] = "/O1"
            if candidate and defect == "profile":
                profile["EnableClServerMode"] = "false"
            return {"Properties": profile, "Items": {"ClCompile": units}}

        environment = {"RUNNER_TEMP": r"C:\runner-temp", "TEMP": r"C:\runner-temp\owned",
                       "TMP": r"C:\runner-temp\owned"}
        with patch.object(study, "source_guard"), patch.object(study, "query", side_effect=query), \
                patch.dict(os.environ, environment):
            plan = self.run / "plan.json"
            study.plan(self.source, self.build, plan)
            self.assertEqual(len(study.source_evidence.load(plan)["cases"]["original"]["units"]), 1015)
            for defect, message in (("count", "1015"), ("context", "compiler context"), ("profile", "profile mismatch")):
                with self.subTest(defect=defect), self.assertRaisesRegex(ValueError, message):
                    study.plan(self.source, self.build, plan)


if __name__ == "__main__":
    unittest.main()

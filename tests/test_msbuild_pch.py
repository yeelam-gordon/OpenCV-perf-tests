"""No OpenCV build/install/network: combined profile and native-clean guards."""

import importlib.util
import copy
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


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "ci" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


main = module("msbuild-clserver-evidence")
pch = module("msbuild-pch-evidence")


class CombinedGuards(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".work" / ("combined-test-" + uuid.uuid4().hex)
        self.source, self.build, self.run = [self.root / name for name in ("source", "build", "run")]
        for directory in (self.source, self.build, self.run):
            directory.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)

    def base(self):
        return {"identity": str(self.source / "modules/core/src/unit0.cpp"),
                "file_key": pch.normal(str(self.source / "modules/core/src/unit0.cpp"), self.source, self.build).replace("\\", "/").lower(),
                "tlog": pch.WORLD_TLOG, "build": str(self.build),
                "context": {"PreprocessorDefinitions": "_WINDLL;NDEBUG", "ExceptionHandling": "Async",
                            "RuntimeLibrary": "MultiThreadedDLL", "FloatingPointModel": "Precise", "ForcedIncludeFiles": ""}}

    def partition(self, units):
        return pch.partition(units, self.source, self.build, self.base())

    def units(self):
        project = self.build / "modules/world/opencv_world.vcxproj"
        directory = project.parent / "opencv_world.dir/Release"
        source = project.parent / "CMakeFiles/opencv_world.dir/cmake_pch.cxx"
        template = source.parent / "Release/cmake_pch.hxx"
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text("\n".join("#include <" + name + ">" for name in pch.HEADERS))
        units = []
        for index in range(514):
            created = index == 513
            file = source if created else self.source / f"modules/core/src/unit{index}.cpp"
            units.append({
                "file": str(file), "identity": str(file), "project": str(project),
                "output": str(directory / ("cmake_pch.obj" if created else f"unit{index}.obj")),
                "source_sha256": "fixture",
                "context": {"PrecompiledHeader": "Create" if created else "Use",
                            "PreprocessorDefinitions": "_WINDLL;NDEBUG", "ExceptionHandling": "Async",
                            "RuntimeLibrary": "MultiThreadedDLL", "FloatingPointModel": "Precise"},
                "pch": {"PrecompiledHeader": "Create" if created else "Use",
                        "PrecompiledHeaderFile": str(template),
                        "PrecompiledHeaderOutputFile": str(directory / "cmake_pch.pch"),
                        "ForcedIncludeFiles": str(template), "MultiProcessorCompilation": "true"},
            })
        return units

    def test_exact_producer_consumers_context_and_native_paths(self):
        units = self.units()
        sources, profile = self.partition(units)
        self.assertEqual((len(sources), profile["consumers"]), (513, 513))
        for changed, message in ((units[:-1], "one world"), (units[1:], "513 CXX")):
            with self.assertRaisesRegex(ValueError, message):
                self.partition(changed)
        units[-1]["context"]["RuntimeLibrary"] = "MultiThreaded"
        with self.assertRaisesRegex(ValueError, "CPP context"):
            self.partition(units)

    def test_legitimate_source_macros_bound_to_original_and_producer_base(self):
        combined = self.units()
        extras = (";HAVE_MALLOC_H=1;HAVE_WIN32_ALIGNED_MALLOC=1",
                  ';PARALLEL_ENABLE_PLUGINS;DEBUG_POSTFIX="d"',
                  ';DEBUG_POSTFIX="d"', ';DEBUG_POSTFIX="d"')
        for unit, extra in zip(combined, extras):
            unit["context"]["PreprocessorDefinitions"] += extra
        original = copy.deepcopy(combined[:-1])
        for unit in original:
            unit["context"]["PrecompiledHeader"] = "NotUsing"
            unit["context"]["ForcedIncludeFiles"] = ""
            unit["pch"]["PrecompiledHeader"] = "NotUsing"
            unit["pch"]["ForcedIncludeFiles"] = ""
        sources, _ = self.partition(combined)
        pch.paired_units(original, sources, self.source, self.build, self.build)
        combined[0]["context"]["PreprocessorDefinitions"] += ";UNEXPECTED_CONSUMER=1"
        with self.assertRaisesRegex(ValueError, "Per-source/target context"):
            pch.paired_units(original, combined[:-1], self.source, self.build, self.build)
        combined[-1]["context"]["PreprocessorDefinitions"] += ";UNEXPECTED_PRODUCER=1"
        with self.assertRaisesRegex(ValueError, "original native WORLD base"):
            self.partition(combined)

    def test_nested_parallel_collision_outputs_keep_exact_source_target_binding(self):
        combined = self.units()
        directory = Path(combined[-1]["output"]).parent
        for unit, name in zip(combined, ("parallel.cpp", "parallel/parallel.cpp")):
            unit["file"] = str(self.source / "modules/core/src" / name)
            unit["identity"] = "modules/core/src/" + name
            unit["output"] = str(directory / "__/core/src" / (name + ".obj"))
        original = copy.deepcopy(combined[:-1])
        for unit in original:
            unit["context"]["PrecompiledHeader"] = "NotUsing"
            unit["context"]["ForcedIncludeFiles"] = ""
            unit["pch"]["PrecompiledHeader"] = "NotUsing"
        sources, _ = self.partition(combined)
        pch.paired_units(original, sources, self.source, self.build, self.build)
        for output in (directory.parent / "outside.obj", self.build / "wrong-root/u.obj",
                       directory / ".." / "escape.obj"):
            bad = copy.deepcopy(combined)
            bad[0]["output"] = str(output)
            with self.assertRaisesRegex(ValueError, "escapes canonical"):
                self.partition(bad)
        bad = copy.deepcopy(combined)
        bad[0]["output"] = str(directory / "__/core/src/wrong-binding.obj")
        sources, _ = self.partition(bad)
        with self.assertRaisesRegex(ValueError, "Per-source/target context or output drift"):
            pch.paired_units(original, sources, self.source, self.build, self.build)
        bad = copy.deepcopy(combined)
        bad[-1]["output"] = str(directory / "nested/cmake_pch.obj")
        with self.assertRaisesRegex(ValueError, "native IntDir"):
            self.partition(bad)
        bad = copy.deepcopy(combined)
        bad[0]["project"] = str(self.build / "modules/core/wrong.vcxproj")
        with self.assertRaisesRegex(ValueError, "world CXX"):
            self.partition(bad)

    def test_no_pch_leak_to_static_object_C_or_wrong_forced_include(self):
        units = self.units()
        units[0]["project"] = str(self.build / "modules/core/dispatched.vcxproj")
        with self.assertRaisesRegex(ValueError, "world CXX"):
            self.partition(units)
        units = self.units()
        units[0]["pch"]["ForcedIncludeFiles"] += ";opencv2/core.hpp"
        with self.assertRaisesRegex(ValueError, "forced include"):
            self.partition(units)
        units = self.units()
        units[0]["file"] = str(self.source / "unit.c")
        with self.assertRaisesRegex(ValueError, "world CXX"):
            self.partition(units)
        units = self.units()
        units[0]["pch"]["MultiProcessorCompilation"] = "false"
        with self.assertRaisesRegex(ValueError, "MP selection"):
            self.partition(units)
        units = self.units()
        units[0]["pch"]["EnableClServerMode"] = "false"
        with self.assertRaisesRegex(ValueError, "CL-server selection"):
            self.partition(units)

    def test_standard_only_frozen_wrapper_and_recipe_binding(self):
        units = self.units()
        _, profile = self.partition(units)
        wrapper = pch.wrapper_input(profile)
        original = wrapper.read_bytes()
        wrapper.write_bytes(original + b"\n// changed configure input\n")
        with self.assertRaisesRegex(ValueError, "wrapper input changed"):
            pch.wrapper_input(profile)
        wrapper.write_bytes(original)
        units[0]["pch"]["PrecompiledHeaderFile"] = str(self.build / "wrong-wrapper.hxx")
        with self.assertRaisesRegex(ValueError, "canonical wrapper binding"):
            self.partition(units)
        units[0]["pch"]["PrecompiledHeaderFile"] = str(wrapper)
        wrapper.write_text(wrapper.read_text() + '\n#include "opencv2/core.hpp"\n')
        with self.assertRaisesRegex(ValueError, "six standard"):
            self.partition(units)

    def test_native_clean_and_profile_contamination(self):
        units, profile = self.partition(self.units())
        standard = [dict(units[0], output=str(self.build / f"u{i}.obj")) for i in range(1015)]
        temp = str(self.root / "compiler-temp")
        plan = {"combined": True, "compiler_temp": temp, "features": {},
                "cases": {"combined": {"build": str(self.build), "units": standard, "pch": profile}}}
        file = self.run / "plan.json"
        main.write(file, plan)
        with patch.object(main, "source_guard"), patch.dict(os.environ, {"TEMP": temp, "TMP": temp}):
            main.clean(self.source, self.build, self.run, file, "MSBuild", "combined")
            for name in profile["artifacts"]:
                artifact = Path(name)
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_bytes(b"synthetic stale PCH/producer/header")
                with self.assertRaisesRegex(ValueError, "still present"):
                    main.clean(self.source, self.build, self.run, file, "MSBuild", "combined")
                artifact.unlink()
            with self.assertRaisesRegex(ValueError, "contamination"):
                main.clean(self.source, self.build / "wrong-profile", self.run, file, "MSBuild", "combined")

    def test_flags_normalize_only_roots_and_pch_not_optimization(self):
        baseline = self.build / "original"
        combined = self.build / "combined"
        old = {"file": str(self.source / "unit.cpp"),
               "command": f'cl /MP /O2 /EHa /MD /fp:precise /I"{baseline}/include" "{self.source / "unit.cpp"}"'}
        new = dict(old, command=old["command"].replace(str(baseline), str(combined)) +
                   ' "/Yucmake_pch.hxx" "/Fpcmake_pch.pch" "/FIcmake_pch.hxx"')
        self.assertEqual(pch.flags(old, self.source, baseline), pch.flags(new, self.source, combined))
        new["command"] = new["command"].replace("/O2", "/O1")
        self.assertNotEqual(pch.flags(old, self.source, baseline), pch.flags(new, self.source, combined))
        escaped = dict(old, command=old["command"] + r' /D NAME="a\b" /D FILE_NAME="unit.cpp"')
        changed = dict(escaped, command=escaped["command"].replace(r'a\b', 'a/b'))
        self.assertNotEqual(pch.flags(escaped, self.source, baseline), pch.flags(changed, self.source, baseline))
        self.assertIn('FILE_NAME="unit.cpp"', pch.flags(escaped, self.source, baseline))

    def test_diagnostics_and_real_option_casing(self):
        self.assertEqual(pch.option('cl /fp:precise "/Fpdir with spaces/cmake_pch.pch"', "/Fp"),
                         "dir with spaces/cmake_pch.pch")
        for message in ("warning C4652", "ignoring precompiled header", "precompiled header not used"):
            with self.assertRaisesRegex(ValueError, "diagnostic"):
                pch.diagnostics(message)

    def test_actual_yc_yu_fi_fp_mp_and_context_must_match(self):
        units, profile = self.partition(self.units())
        wrapper = pch.wrapper_input(profile)
        entries = []
        for unit in units + [profile["producer"]]:
            flag = "/Yc" if pch.producer(unit["file"]) else "/Yu"
            entries.append({"file": unit["file"],
                            "tlog": "modules/world/opencv_world.dir/Release/opencv_world.tlog/CL.command.1.tlog",
                            "command": f'cl /MP /MD /EHa /fp:precise /DNDEBUG {flag}"{wrapper}" '
                                       f'/Fp"{profile["artifacts"][0]}" /FI"{wrapper}"'})
        baseline = [dict(entry, command="cl /MP /MD /EHa /fp:precise /DNDEBUG") for entry in entries[:-1]]
        for index, extra in ((1, " /DHAVE_MALLOC_H=1 /DHAVE_WIN32_ALIGNED_MALLOC=1"),
                             (2, ' /DPARALLEL_ENABLE_PLUGINS /DDEBUG_POSTFIX="d"')):
            entries[index]["command"] += extra
            baseline[index]["command"] += extra
        self.assertEqual(len(pch.commands(entries, self.source, self.build, profile, main.source_evidence.principal, baseline)), 513)
        original = entries[0]["command"]
        entries[0]["command"] = original.replace("/MP ", "")
        baseline[0]["command"] = baseline[0]["command"].replace("/MP ", "")
        pch.commands(entries, self.source, self.build, profile, main.source_evidence.principal, baseline)
        baseline[0]["command"] = "cl /MP /MD /EHa /fp:precise /DNDEBUG"
        for changed in (original.replace("/Yu", "/Yc"),
                        original.replace("/MD ", "/MT "), original + " /Y-",
                        original.replace("/FI", "/FIwrong")):
            entries[0]["command"] = changed
            with self.assertRaises(ValueError):
                pch.commands(entries, self.source, self.build, profile, main.source_evidence.principal, baseline)
        entries[0]["command"] = original
        entries[1]["command"] += " /DCONSUMER_DRIFT=1"
        with self.assertRaisesRegex(ValueError, "per-source/target consumer"):
            pch.commands(entries, self.source, self.build, profile, main.source_evidence.principal, baseline)
        entries[1]["command"] = entries[1]["command"].replace(" /DCONSUMER_DRIFT=1", "")
        entries[-1]["command"] += " /DPRODUCER_BASE_DRIFT=1"
        with self.assertRaisesRegex(ValueError, "producer CPP context"):
            pch.commands(entries, self.source, self.build, profile, main.source_evidence.principal, baseline)

    def test_outputs_in_clock_but_old_wrapper_is_valid_frozen_input(self):
        _, profile = self.partition(self.units())
        outputs = [Path(name) for name in profile["artifacts"]]
        now = time.time()
        owned = {key: datetime.fromtimestamp(value, timezone.utc).isoformat()
                 for key, value in (("started_at", now - 2), ("finished_at", now + 2))}
        wrapper = Path(profile["wrapper"])
        os.utime(wrapper, (now - 100, now - 100))
        self.assertEqual(pch.wrapper_input(profile), wrapper)
        for file in outputs:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"synthetic owned output")
        main.clock_outputs(outputs, owned)
        self.assertLess(wrapper.stat().st_mtime, datetime.fromisoformat(owned["started_at"]).timestamp())
        for file in outputs:
            os.utime(file, (now - 100, now - 100))
            with self.assertRaisesRegex(ValueError, "inside owned clock"):
                main.clock_outputs(outputs, owned)
            os.utime(file, (now, now))
        outputs[1].unlink()
        with self.assertRaisesRegex(ValueError, "inside owned clock"):
            main.clock_outputs(outputs, owned)

    def test_original_profile_still_rejects_pch_before_timing(self):
        setup = {"generator": "MSBuild", "compiler_id": "MSVC", "architecture": "arm64",
                 "build_engine": {"path": "fixture"}, "visual_studio": {"path": "fixture"}}
        main.write(self.build / "benchmark-setup.json", setup)
        project = self.build / "world.vcxproj"
        project.write_text("<Project/>")
        data = {"Properties": dict.fromkeys(main.PROPERTIES, ""), "Items": {"ClCompile": [
            {"FullPath": str(self.source / "unit.cpp"), "PrecompiledHeader": "Use"}]}}
        owner = str(Path(r"C:\runner-temp") if os.name == "nt" else Path("/runner-temp"))
        with patch.object(main, "source_guard"), patch.object(main, "query", return_value=data), \
                patch.dict(os.environ, {"RUNNER_TEMP": owner, "TEMP": str(Path(owner) / "owned"),
                                        "TMP": str(Path(owner) / "owned")}):
            with self.assertRaisesRegex(ValueError, "PCH is outside"):
                main.plan(self.source, self.build, self.run / "plan.json")

    def test_comparison_requires_flags_and_separate_producer_proof(self):
        record = {"source_commit": main.BASE, "source_tree": main.TREE, "source_blob": main.BLOB,
                  "unit_count": 1015, "units": ["fixture"], "headers_sha256": {"cpu": "same"},
                  "world_principal": [["fixture", {"eh": ["EHa"], "crt": ["MD"]}]]}
        runs = [{"label": name, "directory": name, "configuration": name, "warmup": False, "build_seconds": 1}
                for name in ("original", "combined")]
        main.write(self.run / "study.json", {"combined_pch": True, "runs": runs})
        for name in ("original", "combined"):
            directory = self.run / name
            directory.mkdir()
            main.write(directory / "source-workload.json", record)
            main.write(directory / "compiled-inputs.json", [{"source": "fixture", "source_sha256": "same", "suffix": ".cpp"}])
            main.write(directory / "compiled-flags.json", [{"source": "fixture", "flags": ["/MP", "/O2"]}])
            main.write(directory / "native-output.json", {"source_objects": 1015, "producer_objects": int(name == "combined"),
                       "pch_outputs": dict.fromkeys(("pch", "obj"), "receipt") if name == "combined" else {},
                       "pch_inputs": {"sha256": "frozen-wrapper-receipt"} if name == "combined" else {}})
        main.compare(self.run, "MSBuild")
        main.write(self.run / "combined/compiled-flags.json", [{"source": "fixture", "flags": ["/MP", "/O1"]}])
        with self.assertRaisesRegex(ValueError, "context drift"):
            main.compare(self.run, "MSBuild")
        (self.run / "combined/compiled-flags.json").unlink()
        with self.assertRaisesRegex(ValueError, "flag evidence"):
            main.compare(self.run, "MSBuild")
        main.write(self.run / "combined/compiled-flags.json", [{"source": "fixture", "flags": ["/MP", "/O2"]}])
        main.write(self.run / "combined/native-output.json", {"source_objects": 1015, "producer_objects": 0, "pch_outputs": {}})
        with self.assertRaisesRegex(ValueError, "producer/native-output proof"):
            main.compare(self.run, "MSBuild")


class NativeOwnership(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows native VS configuration/clean fixture")
    def test_private_PCH_scope_and_native_clean_without_compilation(self):
        names = ("STUDY_TEST_CMAKE", "STUDY_TEST_MSBUILD", "STUDY_TEST_COMPILER", "STUDY_TEST_VS")
        if not all(os.environ.get(name) for name in names):
            self.skipTest("Explicit native fixture tools unavailable; no install performed")
        cmake, msbuild, compiler, vs = [os.environ[name] for name in names]
        root = ROOT / ".work" / ("native-pch-" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root)
        build = root / "build"
        arguments = [cmake, "-S", str(ROOT / "tests/msbuild_pch"), "-B", str(build),
                     "-G", "Visual Studio 18 2026", "-A", "ARM64", "-T", "host=ARM64",
                     "-DCMAKE_GENERATOR_INSTANCE=" + vs,
                     "-DCMAKE_PROJECT_INCLUDE=" + str(ROOT / "ci/msbuild-stdlib-pch.cmake")]
        for language in ("C", "CXX"):
            arguments += [f"-DCMAKE_{language}_COMPILER:FILEPATH={compiler}",
                          f"-DCMAKE_{language}_COMPILER_ID=MSVC", f"-DCMAKE_{language}_COMPILER_VERSION=19.51",
                          f"-DCMAKE_{language}_COMPILER_ID_RUN=TRUE", f"-DCMAKE_{language}_COMPILER_FORCED=TRUE",
                          f"-DCMAKE_{language}_COMPILER_WORKS=TRUE"]
        result = subprocess.run(arguments, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        def collect(selected, settings):
            units = []
            for project in sorted((selected / "modules/world").glob("*.vcxproj")):
                if project.stem in ("ALL_BUILD", "ZERO_CHECK"):
                    continue
                data = main.query(msbuild, project, settings, ("IntDir",))
                for item in data["Items"]["ClCompile"]:
                    file = Path(item["FullPath"])
                    units.append({
                        "file": str(file), "identity": main.source_evidence.identity(file, ROOT / "tests/msbuild_pch", selected),
                        "project": str(project), "output": str(main.object_path(item["ObjectFileName"], file, project, selected)),
                        "source_sha256": main.source_evidence.sha(file),
                        "context": {key: item.get(key, "") for key in main.CONTEXT},
                        "pch": {key: item.get(key, "") for key in pch.PCH_FIELDS},
                    })
            return units

        combined = collect(build, main.SERVER)
        baseline = root / "original"
        original_arguments = [value.replace(str(build), str(baseline)) for value in arguments
                              if not value.startswith("-DCMAKE_PROJECT_INCLUDE=")]
        result = subprocess.run(original_arguments, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        original = collect(baseline, [])
        world_base = pch.common_world_base(original, ROOT / "tests/msbuild_pch", baseline)
        self.assertTrue(world_base["identity"].endswith("/unit.cpp"))
        units, profile = pch.partition(combined, ROOT / "tests/msbuild_pch", build, world_base, expected_consumers=5)
        self.assertTrue(all(unit["pch"]["PrecompiledHeader"].lower() in ("", "notusing") for unit in original))
        pch.paired_units(original, units, ROOT / "tests/msbuild_pch", baseline, build)
        alloc = next(unit for unit in units if Path(unit["file"]).name == "alloc.cpp")
        self.assertIn("HAVE_MALLOC_H=1", alloc["context"]["PreprocessorDefinitions"])
        self.assertIn("HAVE_WIN32_ALIGNED_MALLOC=1", alloc["context"]["PreprocessorDefinitions"])
        self.assertNotIn("HAVE_MALLOC_H", profile["producer"]["context"]["PreprocessorDefinitions"])
        changed = copy.deepcopy(combined)
        next(unit for unit in changed if Path(unit["file"]).name == "parallel.cpp")["context"]["PreprocessorDefinitions"] += ";DRIFT=1"
        with self.assertRaisesRegex(ValueError, "Per-source/target context"):
            pch.paired_units(original, [unit for unit in changed if not pch.producer(unit["file"])],
                             ROOT / "tests/msbuild_pch", baseline, build)
        changed = copy.deepcopy(combined)
        next(unit for unit in changed if pch.producer(unit["file"]))["context"]["PreprocessorDefinitions"] += ";BASE_DRIFT=1"
        with self.assertRaisesRegex(ValueError, "original native WORLD base"):
            pch.partition(changed, ROOT / "tests/msbuild_pch", build, world_base, expected_consumers=5)
        artifacts = [Path(name) for name in profile["artifacts"]]
        wrapper = pch.wrapper_input(profile)
        frozen_wrapper = wrapper.read_bytes()
        world_project = build / "modules/world/opencv_world.vcxproj"
        required_objects = [Path(unit["output"]) for unit in units if Path(unit["project"]) == world_project]
        for artifact in artifacts + required_objects:
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"synthetic native-clean fixture; never compiled")
        unowned = artifacts[0].parent / "unowned.hxx"
        unowned.write_bytes(b"unowned header")
        result = subprocess.run([msbuild, str(build / "modules/world/opencv_world.vcxproj"), "-nologo",
                                 "-verbosity:quiet", "-p:Configuration=Release", "-p:Platform=ARM64", "-target:Clean"],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(artifact.exists() for artifact in artifacts + required_objects))
        self.assertTrue(wrapper.is_file())
        self.assertEqual(wrapper.read_bytes(), frozen_wrapper)
        self.assertEqual(pch.wrapper_input(profile), wrapper)
        self.assertTrue(unowned.exists())


if __name__ == "__main__":
    unittest.main()

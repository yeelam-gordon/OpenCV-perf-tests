# Native MSBuild combined stdlib-PCH experiment

Local output audit, independent CI review and parent metareview are delivery
gates. No performance forecast, NoReg, Debug,
adoption, memory equivalence or resident/busy/global-four-process cap is claimed.
Do not add percentages or transfer local/historical timings to this cohort.

The published standalone server experiment at `cc585f6` / run 43038363001 is
already qualified: Windows 700.97255 → 633.60765 s within its own cohort; the
Mac-only capacity recovery reference median was 242.50 s. Windows was not
rerun for that recovery. No further standalone-server run is requested here.
Those are not denominators or forecasts for this new direct combined pair.

## Manual bounded launch contract

The local-only next-step candidate is `perf/msbuild-extended-pch-ci-20261125`,
based on public benchmark commit `e8ff35749914f120f5e8793121223d018e26d278`.
It adds only the opt-in fixed header-set selector described below. Preparation
does not authorize push, dispatch or publication. Independent artifact-fidelity
audit, native validation and parent final review remain pending; no local
timing transfers to CI, adoption or universal NoReg claims.

The preceding six-header repair contract was:

Repository `yeelam-gordon/OpenCV-perf-tests`, experiment ref
`perf/msbuild-pch-tracker-parity`, exact repair base
`0d898d2ad6305051427c30a57a655421831579a5`. Reuse registered workflow
**412734614**, `.github/workflows/hosted-arm-storage.yml`, manual dispatch on
the reviewed new ref only. No settings, default-branch or capacity change and
no automatic retry. Exactly Windows `windows-11-arm` / 120 minutes and Mac
`macos-15` / 60 minutes by default. For a Windows-only repair, explicitly set
dispatch input `run_macos=false` and preserve the independently audited successful
Mac artifact instead of consuming another runner. Record both commits and
confirm the Mac execution payload is unchanged before pairing references.

Historical combined ref `perf/msbuild-clserver-pch-ci` at that base produced
run 43087870068; Windows failed metadata planning before warmups or scores.
Its failed tree, artifact and log remain historical evidence, not a repair run.
The nested-path repair reached both excluded Windows warmups in run45297421317,
then rejected path-derived tracking-folder names as project-context drift.
No Windows score ran. This repair binds flags to the source and relative
project/configuration directory, omitting only the terminal tracker container.
Unexpected layouts and duplicate source/project bindings still fail; semantic
flags and native output bindings retain their existing checks.

Windows excludes two warmups (original/combined), then scores
original/combined/combined/original: **six total builds, not three profiles
or nine builds**. Mac retains one excluded warmup and two unchanged-source
Make references. There is no Mac PCH.

## Two isolated native MSVC/MSBuild profiles, one unchanged source

Every case uses BASE 4.10.0 commit
`71d3237a093b60a27601c20e9ee6c3e52154e8b1`, tree
`1f7a0c7fcc20571cab11da4c86ae1e796979df5b`, the same 23 definitions,
observed/pinned native toolchain, SDK/UCRT and feature headers. No source CPP
patch, variant commit, source fork, Ninja dispatch/definition hook, SDK
dependency-filter change or `_WINDLL` override is used. Native VS already
supplies DLL macros.

Original keeps default `/MP` and its original build directory. Combined uses
a separate configured child directory, the published shared4/CL-server
settings, and PRIVATE modern `target_precompile_headers` on shared
`opencv_world` only. Both cases inherit the same fresh, process-owned,
whitespace-free `TEMP`/`TMP`; no global environment or protection changes.
The directory/profile guards reject baseline contamination.

All **1,015 original source units**, including 107 OpenEXR units, remain
required. Combined adds **exactly one** generated CXX producer and exactly
**513 main-world CXX consumers**. The header list is exactly `vector`,
`algorithm`, `string`, `memory`, `utility`, `limits` by default (`six`).
The explicit opt-in `ten` appends only `mutex`, `ostream`, `cmath`, `functional`
in that order. No OpenCV, Windows,
iostream, module or private header is cached. C/static/dispatched/object
targets must not consume this PCH. DNN's source-level macro undef behavior
is untouched.

## Plain PRIVATE API: frozen inputs versus native outputs

The CMake hook uses plain modern PRIVATE `target_precompile_headers`, matching
the qualified local configuration, with legacy world PCH disabled. CMake's
canonical config-specific wrapper under `CMakeFiles/opencv_world.dir/Release`
is a **configure-time input**, like `cvconfig.h`: freeze its exact selected includes,
byte hash and native Yc/Yu/FI bindings. It legitimately remains outside native
`IntDir` across Clean and need not have an in-clock timestamp.

Only the actual PCH binary and producer object are additional native build
outputs in world `IntDir`. Stock native Clean owns these outputs. There is no
wrapper relocation/copy/touch, user-props replacement, per-source VS override,
clean-pattern extension or `ADDITIONAL_CLEAN_FILES` hook. PRIVATE CXX-only API
scope is checked directly, including a physical source shared with a static
or object target.

Native evaluated profile guards require exact Create/Use, FI/FP/header paths
and MP selection. The producer must match the original native WORLD common
context, bound to an original CXX item whose project XML has no per-source
semantic metadata overrides. Consumers keep all source-specific definitions:
their complete contexts must match the same original source and target, not
the producer. This preserves legitimate alloc/parallel/backend definitions
without a macro allowlist or flag homogenization. Actual producer semantics
are bound to that original base command receipt; actual consumer flags remain
bound per source/target. Source IDs, output bindings, tool/SDK/features and
normalized compiler contexts must agree across profiles.
Consumer objects may be nested below canonical world `IntDir` for CMake
basename collisions. Containment never replaces exact original source/target
`ObjectFileName` parity. The producer retains its exact native root object
binding; outside/escaping objects or changed bindings fail.

## Reused clock, lifecycle and evidence

The published owned-job wall timer, post-clock descendant drain, native clean,
MSBuild command collector, canonical world/source `/Fo` DLS resolver, direct
`cmake --install`, native version/common image-matrix and captured-DLL smoke
checks remain shared. Old standalone-server, DLS and generator entrypoint
defaults are preserved through a thin opt-in specialization.

Before each timer, every original native object and final DLL/import-library/
version output must be absent. Combined additionally requires its producer
object and PCH absent after **native** Clean, while the canonical wrapper must
remain byte-identical to its frozen configure-time input. After timing and
before direct install, all 1,015 objects, binaries and the separate producer/PCH
must exist with in-clock write times. Actual Yc/Yu/FI/FP paths and CPP context
are checked; MP selection is evaluated natively because MSBuild deliberately
omits `/MP` from its CL command tlog. That omission is not a disabled-MP signal
or process-cap proof. Disabled, ignored or incompatible PCH is rejected.
Raw actual source flags are compared after root/PCH-bookkeeping normalization;
source arguments and resolved output bindings are audited separately.

Actual producer/PCH, source-bound DLS object, DLL/import-library and version
copies stay runner-local before the next clean. Only the published text
extension allowlist uploads, including failures; no object/PCH/compiler/DLL/
library/executable/token uploads. Cloud hashes are receipts, not retained
binary proof. Mac's unchanged 908-language-unit Make boundary, ObjC++/assembly
and stable-only freeze remain intact; do not normalize it to Windows counts
or remove Windows OpenEXR work.

## Fixed six/ten selection and future validation

Workflow input `pch_header_set` defaults to `six`; `ten` selects the same
original/combined two-profile pair, not a third profile. The ten-header CI
candidate qualifies **total original → combined10**, not an isolated
combined6 → combined10 increment. `run_macos` and the Mac Make payload remain
unchanged. Windows still has two excluded warmups plus C/V/V/C, six builds.

`-PchHeaderSet six|ten` is threaded through preparation, the thin combined
entrypoint, runner and the owned setup cache. CMake accepts only
`OPENCV_MSBUILD_PCH_HEADER_SET=six|ten`. Planner, study and native-output receipts
freeze the selection and known ordered includes. Actual generated and retained
wrappers must match the selected fixed set, even if metadata/hash is changed;
arbitrary header metadata is never proof.

After the parent clears the competing native workload, configure locally using
existing discovered tool paths and a fresh owned source/build directory:

```powershell
.\scripts\setup.ps1 -Root $source -Generator MSBuild -Toolchain MSVC2026 -CMake $cmake
$combined = Join-Path $source 'build_hobl_msvc2026_combined'
.\scripts\setup.ps1 -Root $source -Generator MSBuild -Toolchain MSVC2026 -CMake $cmake `
  -BuildDirectory $combined -InitialCache (Join-Path $PWD 'ci\msbuild-stdlib-pch-cache.cmake') -PchHeaderSet ten
python .\ci\msbuild-clserver-evidence.py plan --source $source `
  --build (Join-Path $source 'build_hobl_msvc2026') --candidate-build $combined `
  --pch-header-set ten --plan $plan
python -m unittest discover -s tests -p 'test_msbuild*.py'
```

The native planner still requires matching process-owned, whitespace-free
`TEMP`/`TMP` beneath `RUNNER_TEMP`, original tool/source/profile checks, and a
fresh `$plan` receipt. Tool pins and the source commit must already satisfy the
owned setup; these commands do not waive discovery or isolation guards.
For an independently authorized hosted execution, preparation is
`.\ci\Prepare-QualifiedGeneratorWorkload.ps1 -MSBuildOnly -CombinedPch -PchHeaderSet ten`
and the existing paired entry is
`.\ci\Run-MSBuildCombinedPchStudy.ps1 -ResultsDir $results -PchHeaderSet ten`.
Neither was run to prepare this candidate.

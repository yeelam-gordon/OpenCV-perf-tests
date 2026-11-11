# Unpublished native MSBuild/CL-server paired candidate

This is preparation only. Local output audit, parent metareview and independent
CI review gate publication/launch. No CI gain, forecast, adoption or NoReg claim
is made. Local n=2 results and historical cohorts do not transfer to this study.
The existing required-path CI reference remains the old 695.5378 s observation.

## Launch contract (not launched)

Owned repository `yeelam-gordon/OpenCV-perf-tests`, proposed ref
`perf/msbuild-clserver-ci`, based on published repair commit
`d5ed039001b476f7dd776463d8aaca4f0eb35f9a`. Reuse registered workflow
**412734614**, `.github/workflows/hosted-arm-storage.yml`, manual dispatch on the
reviewed new ref only. No default-branch/settings/capacity change or automatic
retry. Exactly two hosted jobs: `windows-11-arm` / 120 minutes, `macos-15` /
60 minutes. The separate Ninja/PCH candidate stays on hold and is not modified.

## Windows: both cases are native MSVC + MSBuild

Both use **unchanged** OpenCV 4.10.0 BASE
`71d3237a093b60a27601c20e9ee6c3e52154e8b1`, tree
`1f7a0c7fcc20571cab11da4c86ae1e796979df5b`, the same configured source/build
directory, the original 23 definitions and all 1,015 source compiler units
(including 107 bundled OpenEXR units). No source variant/commit, DLS rewrite,
Ninja, PCH, SDK mutation, LLVM migration or toolset migration is used. Setup
observes the installed native hosted MSVC/MSBuild versions and retains existing
pin/hash/architecture/SDK/UCRT guards.

Original keeps default MSBuild `/MP` behavior. Candidate alone requests four
project jobs and the qualified shared settings `MultiProcCL=true`,
`MultiProcMaxCount=4`, `EnforceProcessCountAcrossBuilds=true`, `/nr:false`, plus
**only** `EnableClServerMode=true`. Server mode is an explicit
**different-residency resource profile**. Budget4 does **not** establish four
resident compilers, four busy compilers, a global process cap or thread parity.
Native evaluated profiles and the installed stock server-target hash are
captured before timing; no PID sampler/profiler runs inside the clock.

Order: excluded warmup original/server, scored original/server/server/original.
A fresh whitespace-free child of the host-owned `RUNNER_TEMP` is the same
process-owned `TEMP` and `TMP` for both cases. Space-containing roots fail closed
(no short-path/root-drive workaround, global environment/protection change or
changed budget). The study restores its inherited process environment afterward.

## Clock, lifecycle and actual-output proof

Native clean, configuration/property queries, managed helper loading, install,
version/capture/smoke and 30-second pauses are outside the build clock. The
existing job-object invoker has an opt-in owned mode: assign the suspended
build invocation and descendants to a kill-on-close job, measure through root
build completion, then drain only that job's residual servers **after** the
clock. Existing invoker behavior remains the default. Aggregate drain checks
outside timing are lifecycle checks, not a residency/busy-process measurement.

Before any timer, native evaluated source-to-object bindings must enumerate all
1,015 units with identical source/CPP contexts across profiles; every required
object, DLL, import library and version executable must be absent after clean.
After the timed build and owned drain, but **before install**, the published
MSBuild command collector and canonical source/world-directory `/Fo` DLS
resolver bind actual compiled sources/objects. Every required compiler/link
output must exist with a write time inside the owned build interval and match
the preflight source/output plan. Missing units or off-clock outputs fail.
Feature headers, source hashes and principal compile contexts must remain equal.

Installation is **direct** `cmake --install`, never an `INSTALL` build target
that might silently compile off-clock. Installed DLL/import-library hashes must
match the already captured timed outputs. Version and common image/matrix
compile/link/execution checks are untimed; common captured-DLL smoke runs over
all six observations. Actual source-bound DLS object, DLL/import-library and
version-executable copies remain runner-local before the next clean.

Only `json`, `log`, `txt`, `csv`, `hpp`, `h`, `cmake` artifacts are allowlisted,
including failed receipts. No compiler/object/DLL/library/executable/archive,
token or private context is uploaded. Cloud hashes are receipts, **not retained
binary proof**. Actual CPU/RAM/tool/architecture/dependency and timing evidence
is retained without core/count normalization.

## Unchanged Mac reference and shared implementation

Mac keeps unchanged BASE and all 23 definitions with native Make: one excluded
warmup and two scored references. It requires the complete 908-language-unit
boundary, including Objective-C++, Objective-C and assembly where present;
actual language counts are recorded. No Mac PCH or native-HOBL world/examples
profile change. Freeze stable recipes/configuration/headers/tools, not mutable
Make dependency/progress caches. Do not equate 908 Mac with 1,015 Windows or
remove Windows OpenEXR work.

`Run-MSBuildClServerStudy.ps1` is a thin specialization of the existing study
core. Existing generator/DLS defaults remain available. Setup is explicitly
MSBuild-only in this workflow; Mac shell/study helpers expose a single-reference
mode while retaining their previous defaults. Focused no-build tests cover
native property evaluation, exact source pin/count/context, stale/off-clock
objects, whitespace ownership, native `/Fo` resolution, Make language/freeze
behavior, owned descendant cleanup/failure and existing captured-output errors.

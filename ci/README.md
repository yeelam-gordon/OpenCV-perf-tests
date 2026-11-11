# Hosted Arm build/storage screen

**Branch note:** the current workflow on `perf/dls-source-ci` is the
[DLS source-table experiment](DLS_SOURCE_EXPERIMENT.md), prepared for parent
audit only. The prior [qualified native generators](QUALIFIED_GENERATORS.md)
and the storage-screen description below are historical on this branch;
neither storage crossover nor a workflow dispatch is authorized by preparation.

Manual-only experimental workflow: `hosted-arm-storage.yml`.
It runs only on GitHub-hosted `windows-11-arm` and `macos-15`, never an inherited
self-hosted lab runner. Four jobs, each bounded to 90 minutes, no automatic retry.
The `lanes` input can restrict a corrective dispatch to two Windows or two macOS
jobs, preserving valid results from the other platform instead of repeating it.

| Job | Workload | Observations |
|---|---|---|
| Windows standard storage | OpenCV 4.10.0, existing 23-definition benchmark, installed native VS 2026/MSVC/MSBuild | Baseline/shared/shared/baseline, two builds per schedule |
| Windows Dev Drive | Same definitions, source, tool requirements and order; source/build/downloads/temp on newly created Dev Drive | Two builds per schedule; explicitly ineligible if the runner has no single safe unused NVMe disk or D: is occupied |
| macOS matched definitions | Same 23 definitions as Windows; native Apple Clang and Make | Two clean builds |
| macOS HOBL-native | Inspected HOBL macOS definitions, including examples enabled and no world-library requirement; native Make | Two clean builds; separate workload, not interchangeable with matched results |

CMake 4.4.4 archives are pinned by official release SHA-256 on both systems.
The first hosted attempt exposed the label's VS 2026 migration: native VS 2022
was unavailable. Discover installed VS 2026, write its observed versions to a
job-local profile, then retain all existing setup/run pin/hash checks. This is
a new CI toolchain series, not an exact historical-toolchain reproduction.
OpenCV must resolve to `71d3237a093b60a27601c20e9ee6c3e52154e8b1`.
macOS uses FFmpeg 6; Windows uses OpenCV's own configured dependencies.
Source/options match where declared; platform features, dependencies, SDKs,
hardware and job core counts do not thereby become identical.

## What this can establish

Baseline and shared-MSBuild timings within each Windows job screen scheduler
effects. Between-job standard/Dev Drive timings screen the practical storage
intervention, not ReFS alone: the physical disk and temporary-file placement
also differ. Both interventions must be measured together before reporting a
combined result against the unchanged standard-storage baseline.

Thirty-second rests precede scored builds. There are no discarded full-build
warmups; retain all observations and ranges. Windows install/version and
per-output image/matrix smoke checks are untimed. Effective compiler command
manifests must match across schedules. macOS follows the native Make timed-build
boundary and validates version/smoke behavior outside it.

Build wall times exclude checkout, downloads, configure, clean, install and
smoke checks. Read GitHub job start/completion times separately for total job
cost, which here includes repeated builds and setup. Do not compare these
job totals to a single-build release job or infer energy from wall time.

## Safe Dev Drive adaptation

Based on the merged
[IronRDP PR 2186](https://github.com/Devolutions/IronRDP/pull/2186), commit
`fb4b93cb0644306e3115f20ba8a3313de44ed700`, and the ongoing
[runner-images issue 14878](https://github.com/actions/runner-images/issues/14878).
The IronRDP result is not an OpenCV result.

Preparation requires a hosted Windows Arm64 job, no D: assignment, and exactly
one online writable RAW non-boot/non-system NVMe disk, at least 50 GiB, with
zero partitions and absent from the partition inventory. It never clears,
resizes, or reformats existing storage. Eighteen mock guard cases run before
provisioning. Operational failures are explicit; ineligible storage is recorded
as ineligible, not reported as a successful treatment.

`Format-Volume -DevDrive -FileSystem ReFS` uses Windows defaults. Trust and
Defender state are queried and retained; no exclusions, disabling, trust
overrides, or filter-policy changes are applied. This is not permission to
format or change the shared investigation host.

Only the measured OpenCV source/build/download/temp paths move; the workflow
checkout, running Actions agent, SDKs and hosted tool cache stay unchanged.
No Cargo/NuGet caches are added to this C++ workload. Artifacts contain public
benchmark logs/receipts, not internal work records or credentials.

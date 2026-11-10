# Qualified native generator CI

This branch's manual workflow compares **original/shared-MSBuild/aligned Ninja
on the same Windows Arm VM**, with a fresh matched-definition macOS Arm reference.
It does not include storage provisioning, compiler migration or source prototypes.

| Job | Bounded protocol |
|---|---|
| Windows `windows-11-arm` |120-minute cap; native observed VS2026/MSVC/SDK, pinned Arm64 CMake4.4.4/Ninja1.13.2; three excluded warmups then original/shared/Ninja/Ninja/shared/original |
| macOS `macos-15` |60-minute cap; native Apple Clang/Make, same23 definitions and pinned CMake4.4.4; one excluded warmup plus two scored builds |

Manual-only, read-only repository permission, no automatic retries or inherited
self-hosted execution. Actual CPU/RAM, architecture, image/tool versions and
commands are retained; equal runner labels do not imply equal physical hosts.
The Windows configurations share one job/VM, not separate scheduler-treatment VMs.

OpenCV4.10.0 commit `71d3237a093b60a27601c20e9ee6c3e52154e8b1`,
the existing23 HOBL Windows definitions and declared phase boundary are retained.
Aligned Ninja uses OpenCV's existing forced-dispatch-object-target option plus
matching platform macros and `/Oy-`; it is not unmodified default Ninja.
Residual generator metadata and platform dependency differences remain explicit.

**Score only the build invocation.** Tool download/provisioning, configuration,
clean, install/version, evidence collection, excluded warmups and smoke checks
are outside it. Tests/perf tests remain OFF in the original scored payload.
Common image/matrix smoke runs against every retained Windows DLL before text
artifacts are uploaded. Actual compile/source/feature parity and raw observations
must be audited before reporting gains; no local percentage is assumed to transfer.

Mac matched definitions are not the separate native-HOBL profile (examples ON,
world OFF), and neither three-vCPU Mac nor four-vCPU Windows hosted hardware is
the physical scenario target. Preserve those distinctions in Windows/Mac ratios.
No antivirus/trust/filter changes, disk formatting, private research or raw
internal work records are included.

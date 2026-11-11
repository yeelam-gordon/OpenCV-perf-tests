# DLS source-table CI experiment (not adoption)

This branch prepares an explicitly dispatched, same-job source-shape experiment.
It does not establish a performance win, Windows/Mac parity, numerical
equivalence, Debug qualification, or a recommendation to adopt the candidate.
The benchmark remains OpenCV 4.10.0 with the existing 23 definitions.

## Two-platform capture repair

`perf/dls-source-ci-repair` repairs evidence bookkeeping on the published
experiment, not the OpenCV source candidate or workload. It supersedes the
unreleased Mac-only repair. The registered workflow path retains exactly the
original two jobs: Windows `windows-11-arm` at 120 minutes and Mac `macos-15`
at 60 minutes, with independent concurrency group
`dls-source-table-two-platform-capture-repair`. There are no extra jobs, dispatch
inputs or automatic retries. Parent review and explicit GO are required before
committing, pushing or dispatching this branch.

Both original jobs completed their first build warmup but failed subsequent
evidence bookkeeping, accepting zero observations. Neither failed warmup is a
score or an observation imported into the repaired batch. Fresh Windows and
Mac studies retain all original excluded warmups and balanced scored orders.
Source patch/tree, all 23 definitions, tools/compiler/profile, features,
language accounting and timer boundaries are unchanged; no required dependency
or compile work is moved outside the timer.

### Stable Mac inputs versus mutable build outputs

| Classification | Files or guard |
|---|---|
| Stable Make recipes and dispatch | `Makefile`, `Makefile2`, `build.make`, `flags.make`, `link.txt`, generated clean/install recipes |
| Stable regeneration/compiler metadata | `Makefile.cmake`, `DependInfo.cmake`, CMake compiler/system description files |
| Stable configuration and source inventory | `CMakeCache.txt`, `compile_commands.json` |
| Stable feature/CPU headers | `cvconfig.h`, `opencv2/opencv_modules.hpp`, `cv_cpu_config.h` |
| Tool identity | Configured CMake, Make, C/C++/Objective-C/C++/ASM compiler, archiver/ranlib/linker paths and file hashes |
| Source and harness identity | Existing source Git pin/cleanliness guards plus benchmark/scripts/tests/toolchain/CI file hashing |
| Mutable outputs, not frozen | `compiler_depend.make`, `depend.make`, `progress.make`, dependency caches, progress markers and object/output files |

Stable-input changes still fail closed. `frozen-input-drift.json` retains the
action and exact **changed** expected/actual SHA256 pairs, **added** hashes and
**missing** expected hashes, including deleted recipes or headers.

### Source-bound DLS object capture

Capture requires exactly one compiler entry for the canonical
`modules/calib3d/src/dls.cpp`, not an object found by recursive basename search.
For MSBuild, its world Release command-tlog identity and `/Fo` must agree:
a directory `/Fo"OPENCV_WORLD.DIR\RELEASE\\"` maps the source basename to
`modules/world/opencv_world.dir/Release/dls.obj`; an explicit matching
`dls.obj` output is also accepted. Unrelated projects, prototype objects,
missing/ambiguous source bindings, conflicting output flags and missing
objects fail closed.

Ninja and Make resolve the matching compile-database entry's output, retaining
their existing `dls.cpp.obj` and `dls.cpp.o` names under the configured world
target. The generator/source/build-relative object binding is retained in the
hash receipt. This does not change compiled work, command options, object
bytes or the rule that uploaded hashes are not retained-binary proof.

## Public source identity

`dls-source-variant.json` pins the public upstream base, the literal SHA256 of
`patches/dls-source-table.patch`, the one allowed path, and the expected base
and variant Git blobs/trees. The patch contains only the OpenCV source diff,
not a commit envelope or author metadata. `.gitattributes` preserves its bytes.
No nonpublic source commit is fetched.

`prepare-dls-source.py` requires a clean base at the public pin, applies the
verified patch in a fresh detached worktree, verifies the staged path/blob/tree,
and creates a **runner-local** clean snapshot with the public Actions bot
identity and Copilot coauthor trailer. This commit is never pushed. Git
blob/tree identity is cross-platform; recorded raw source SHA256 values are
runner-local and may differ between Windows CRLF and Mac LF.

The candidate gets its own copy of the public scripts/tests/toolchain profiles
and benchmark configuration. Only its `opencv_commit` field changes. The
control configuration is never rewritten; existing `Assert-Source` and setup
configuration-hash guards are unchanged.

## Bounded protocol

The registered `.github/workflows/hosted-arm-storage.yml` path is reused:
Windows `windows-11-arm` (120 minutes) and Mac `macos-15` (60 minutes), two jobs
only, pinned Actions, read-only contents permission, no persisted credentials.
There is no Dev Drive, compiler downgrade, LLVM, retry, extra CI batch or lab.

Windows uses the existing native compiler/SDK discovery and pinned CMake/Ninja
archives. The four-logical-processor host is required. Original MSBuild
defaults, including `/MP`, remain untouched; only the two aligned Ninja cases
receive `-Parallel 4`. After three excluded case warmups:

```
original_1 current_1 table_1 table_2 current_2 original_2
```

Each run uses the existing clean Release build runner. Provision, configure,
clean, install, version checks, captures and smoke are outside the build timer.
Frozen generated inputs, tool/configuration hashes and power scheme are guarded.
Actual command/source multisets, three feature/CPU headers and per-world-source
EH/FP/CRT/macros are compared (only `CMAKE_INTDIR`, a configuration location,
is omitted). The source experiment's Ninja cache includes the existing dispatch
alignment and adds Visual Studio's `_WINDLL` only to shared-library targets,
not the dispatched object targets. This alignment is applied identically to
current and table, not by weakening the macro guard. Windows fails closed
unless the original 1,015 required units,
including 107 bundled OpenEXR units, survive. Source CPP differences are
explicitly identified by the manifest's canonical trees and blobs.
This is a **new aligned control**, not the earlier qualified-generator profile;
historical improvement percentages do not transfer to it.

Mac retains the matched 23-definition Unix Makefiles reference, not the
different native examples/world profile. After excluded baseline/table warmups:

```
baseline_1 table_1 table_2 baseline_2
```

Both use the same tools, dependency boundary and observed CPU job count.
Compile-database export is enabled on both only for post-build accounting;
each listed object must actually exist. Hardware, memory, compiler, all six
observations and actual work counts are retained. Compilation entries are
selected once for both source and object accounting: Objective-C/C++ (including
AVFoundation `.mm`) and assembly (`.S`/`.s`) are retained, not filtered by a
C/C++-only suffix list. Ninja still excludes custom source-generation commands
by requiring object outputs. Mac counts/dependencies are
not forced to equal Windows (system versus bundled dependencies can differ);
times are not divided by cores or source counts. Hosted observations are not
a prediction of parity.

Windows captures the actual DLS object and DLL locally after each timer, checks
retained DLL copies with the existing image/matrix smoke, and removes retained
binaries in a finally block. Mac hashes its built libraries and checks the
matching build's smoke. Both capture source/object/output hash receipts.
Uploads run even on failure, using only an explicit text extension allowlist.
No objects, libraries, executables or tokens are uploaded. **Cloud hash receipts
are not retained-binary proof.** Image/matrix smoke is not a DLS fidelity test.
Broader numerical/Debug/runtime assessment and final local evidence audit remain
separate gates.

## Local checks and release boundary

No native benchmark/build or package installation is needed for preparation:

```
python -m unittest discover -s tests -p "test_dls_source*.py"
```

Also run the existing native-generator-selection, generator-failure-cleanup,
generator-smoke-evidence and MSBuild command-manifest tests; parse changed
PowerShell scripts, run `bash -n ci/run-macos-dls-source.sh`, and run available
workflow/shell linters without installing them preemptively. Validate the real
patch using an owned clean local checkout at the pinned upstream base, passing
fresh paths to `prepare-dls-source.py`; inspect its clean snapshot and copied
harness receipt without a build or network.

**Parent release only after local evidence audit.** Nothing in these scripts
pushes, publishes or dispatches a workflow, changes the default branch/settings,
or switches GitHub accounts. The releasing operator must verify the active
account is `yeelam-gordon`, inspect the exact public file allowlist and commit,
then (only once release is authorized) push this independent branch and launch:

```
gh workflow run 412734614 --repo yeelam-gordon/OpenCV-perf-tests --ref perf/dls-source-ci-repair
```

The workflow is already registered through the existing default-branch path;
no default-branch edit or unregistered new workflow is needed. Inspect both
jobs' text artifacts, warmup exclusions, source identity, counts, flags,
dependencies and failure receipts before interpreting medians. Do not mix
unmatched local studies or historical CI runs into this experiment's estimate.

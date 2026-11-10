#!/usr/bin/env bash
set -euo pipefail
profile="${1:?matched or hobl-native required}"
case "$profile" in matched|hobl-native) ;; *) echo "Invalid profile" >&2; exit 1 ;; esac
test "$(uname -m)" = arm64
repo="$GITHUB_WORKSPACE"
evidence="$repo/evidence"
root="$RUNNER_TEMP/opencv-ci"
mkdir -p "$evidence"
test ! -e "$root"
mkdir -p "$root"
trap 'status=$?; printf "%s\n" "$status" > "$evidence/script-exit-code.txt"' EXIT

curl --fail --location --silent --show-error \
  https://github.com/Kitware/CMake/releases/download/v4.1.1/cmake-4.1.1-macos-universal.tar.gz \
  -o "$root/cmake.tar.gz"
echo "3cd1da5341618645bdc85a3b99e273f29c4d48db2f545925a658db992e61f6f9  $root/cmake.tar.gz" | shasum -a 256 -c -
tar -xzf "$root/cmake.tar.gz" -C "$root"
cmake="$root/cmake-4.1.1-macos-universal/CMake.app/Contents/bin/cmake"
test -x "$cmake"
file "$cmake" | tee "$evidence/cmake-architecture.txt"
brew list --versions ffmpeg@6 >/dev/null 2>&1 || brew install ffmpeg@6
command -v pkg-config >/dev/null 2>&1 || brew install pkgconf
export PKG_CONFIG_PATH="$(brew --prefix ffmpeg@6)/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
pkg-config --modversion libavcodec > "$evidence/ffmpeg-version.txt"
git clone --quiet --depth 1 --branch 4.10.0 https://github.com/opencv/opencv.git "$root/opencv"
test "$(git -C "$root/opencv" rev-parse HEAD)" = 71d3237a093b60a27601c20e9ee6c3e52154e8b1
flags=()
if [ "$profile" = matched ]; then
  while IFS= read -r flag; do flags+=("$flag"); done < <(
    python3 -c 'import json; print("\n".join(json.load(open("benchmark.json"))["cmake_flags"]))'
  )
else
  flags=(-DCMAKE_BUILD_TYPE=Release -DBUILD_EXAMPLES=ON -DWITH_PYTHON=OFF
    -DBUILD_opencv_python2=OFF -DBUILD_opencv_python3=OFF
    -DBUILD_opencv_python_bindings_generator=OFF -DBUILD_opencv_python_tests=OFF
    -DOPENCV_SKIP_PYTHON_LOADER=ON -DOPENCV_PYTHON_SKIP_DETECTION=ON
    -DBUILD_PERF_TESTS=OFF -DBUILD_TESTS=OFF
    -DPYTHON_EXECUTABLE= -DPYTHON3_EXECUTABLE= -DPYTHON2_EXECUTABLE=)
fi
printf '%s\n' "${flags[@]}" > "$evidence/configure-definitions.txt"
{
  sw_vers
  uname -a
  sysctl hw.ncpu hw.memsize machdep.cpu.brand_string
  xcodebuild -version
  clang --version
  "$cmake" --version
  file "$(xcrun --find clang)"
  df -h "$root"
  diskutil info /
  printf 'ImageOS=%s\nImageVersion=%s\n' "${ImageOS:-}" "${ImageVersion:-}"
} > "$evidence/environment.txt"
"$cmake" -S "$root/opencv" -B "$root/build" -G "Unix Makefiles" \
  "${flags[@]}" > "$evidence/configure.log" 2>&1
cp "$root/build/CMakeCache.txt" "$evidence/"
cp "$root/build/CMakeFiles/4.1.1/CMakeCXXCompiler.cmake" "$evidence/"
jobs="$(sysctl -n hw.ncpu)"
for index in 1 2; do
  run="$evidence/baseline_$index"
  mkdir "$run"
  make -C "$root/build" clean > "$run/clean.log" 2>&1
  sleep 30
  (
    cd "$root/build"
    /usr/bin/time -p -o "$run/time.log" make -j"$jobs" > "$run/build.log" 2>&1
    test "$(./bin/opencv_version)" = 4.10.0
    file ./bin/opencv_version > "$run/output-architecture.txt"
    ./bin/opencv_version --verbose > "$run/opencv-build-info.txt"
  )
  "$cmake" --fresh -S "$repo/tests" -B "$root/smoke" -G "Unix Makefiles" \
    -DCMAKE_BUILD_TYPE=Release "-DOpenCV_DIR=$root/build" > "$run/smoke-configure.log" 2>&1
  "$cmake" --build "$root/smoke" > "$run/smoke-build.log" 2>&1
  "$root/smoke/opencv_smoke" > "$run/smoke.log" 2>&1
done
python3 - "$evidence" "$profile" "$jobs" <<'PY'
import json
import os
from pathlib import Path
import sys

root = Path(sys.argv[1])
runs = []
for index in (1, 2):
    values = dict(line.split() for line in (root / f"baseline_{index}/time.log").read_text().splitlines())
    runs.append({"label": f"baseline_{index}", "seconds": float(values["real"])})
(root / "study.json").write_text(json.dumps({
    "status": "succeeded", "profile": sys.argv[2], "jobs": int(sys.argv[3]),
    "source": "71d3237a093b60a27601c20e9ee6c3e52154e8b1", "generator": "Unix Makefiles",
    "workflow_commit": os.environ["GITHUB_SHA"], "run_id": os.environ["GITHUB_RUN_ID"],
    "runs": runs, "warmups": 0,
    "limitations": "Two clean builds, no discarded warmup, uncontrolled hosted VM; matched definitions do not make platform dependencies/features or hardware identical. HOBL-native profile is a separate workload, not an interchangeable score."
}, indent=2))
PY

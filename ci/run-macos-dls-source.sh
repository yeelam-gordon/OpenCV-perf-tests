#!/usr/bin/env bash
set -euo pipefail
test "$(uname -m)" = arm64
test "${GITHUB_ACTIONS:-}" = true
repo="$GITHUB_WORKSPACE"
evidence="$repo/evidence"
root="$RUNNER_TEMP/opencv-dls-study"
mkdir -p "$evidence"
test ! -e "$root"
mkdir "$root"
finish() {
  status=$?
  trap - EXIT
  if ! find "$evidence" -type d -name runtime-binaries -exec rm -rf {} +; then
    printf '%s\n' 'Local binary cleanup failed' > "$evidence/cleanup-failure.log"
    status=1
  fi
  if [ "$status" -ne 0 ] && [ -f "$evidence/study.json" ]; then
    python3 "$repo/ci/macos-dls-study.py" "failed:$status" "$root" "$evidence" "${jobs:-0}" || true
  fi
  printf "%s\n" "$status" > "$evidence/script-exit-code.txt"
  exit "$status"
}
trap finish EXIT

curl --fail --location --silent --show-error \
  https://github.com/Kitware/CMake/releases/download/v4.4.4/cmake-4.4.4-macos-universal.tar.gz \
  -o "$root/cmake.tar.gz"
echo "4b7b73704b1db9b374e5c9ab8e17ac6148b817b6396ee75cd94a852cbac9d305  $root/cmake.tar.gz" | shasum -a 256 -c -
tar -xzf "$root/cmake.tar.gz" -C "$root"
cmake="$root/cmake-4.4.4-macos-universal/CMake.app/Contents/bin/cmake"
test -x "$cmake"
file "$cmake" > "$evidence/cmake-architecture.txt"
# Restore only when the existing reference's dependency checks report it missing.
brew list --versions ffmpeg@6 >/dev/null 2>&1 || brew install ffmpeg@6
command -v pkg-config >/dev/null 2>&1 || brew install pkgconf
export PKG_CONFIG_PATH="$(brew --prefix ffmpeg@6)/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
pkg-config --modversion libavcodec > "$evidence/ffmpeg-version.txt"
git clone --quiet --depth 1 --branch 4.10.0 https://github.com/opencv/opencv.git "$root/base"
test "$(git -C "$root/base" rev-parse HEAD)" = 71d3237a093b60a27601c20e9ee6c3e52154e8b1
python3 "$repo/ci/prepare-dls-source.py" --base "$root/base" --candidate "$root/table" \
  --harness "$repo" --candidate-harness "$root/table-harness" --receipt "$evidence/source-variant.json"
flags=()
while IFS= read -r flag; do flags+=("$flag"); done < <(
  python3 -c 'import json; d=json.load(open("benchmark.json")); assert len(d["cmake_flags"])==23; print("\n".join(d["cmake_flags"]))'
)
printf '%s\n' "${flags[@]}" > "$evidence/configure-definitions.txt"
{
  sw_vers
  uname -a
  sysctl hw.ncpu hw.memsize machdep.cpu.brand_string
  xcodebuild -version
  clang --version
  "$cmake" --version
  make --version
  file "$(xcrun --find clang)"
  df -h "$root"
  diskutil info /
  printf 'ImageOS=%s\nImageVersion=%s\n' "${ImageOS:-}" "${ImageVersion:-}"
} > "$evidence/environment.txt"
for variant in base table; do
  "$cmake" -S "$root/$variant" -B "$root/$variant-build" -G "Unix Makefiles" \
    "${flags[@]}" -DCMAKE_EXPORT_COMPILE_COMMANDS=ON > "$evidence/$variant-configure.log" 2>&1
  cp "$root/$variant-build/CMakeCache.txt" "$evidence/$variant-CMakeCache.txt"
  cp "$root/$variant-build/CMakeFiles/4.4.4/CMakeCXXCompiler.cmake" "$evidence/$variant-CMakeCXXCompiler.cmake"
done
jobs="$(sysctl -n hw.ncpu)"
python3 "$repo/ci/macos-dls-study.py" initialize "$root" "$evidence" "$jobs"
for label in warmup_baseline warmup_table baseline_1 table_1 table_2 baseline_2; do
  variant=base
  case "$label" in *table*) variant=table ;; esac
  build="$root/$variant-build"
  run="$evidence/$label"
  mkdir "$run"
  python3 "$repo/ci/macos-dls-study.py" guard "$root" "$evidence" "$jobs"
  make -C "$build" clean > "$run/clean.log" 2>&1
  sleep 30
  (
    cd "$build"
    /usr/bin/time -p -o "$run/time.log" make -j"$jobs" > "$run/build.log" 2>&1
    test "$(./bin/opencv_version)" = 4.10.0
    file ./bin/opencv_version > "$run/output-architecture.txt"
    ./bin/opencv_version --verbose > "$run/opencv-build-info.txt"
  )
  cp "$build/compile_commands.json" "$run/commands.json"
  python3 "$repo/ci/dls-source-evidence.py" capture --source "$root/$variant" --build "$build" \
    --run "$run" --generator Make
  "$cmake" --fresh -S "$repo/tests" -B "$root/smoke-$variant" -G "Unix Makefiles" \
    -DCMAKE_BUILD_TYPE=Release "-DOpenCV_DIR=$build" > "$run/smoke-configure.log" 2>&1
  "$cmake" --build "$root/smoke-$variant" > "$run/smoke-build.log" 2>&1
  "$root/smoke-$variant/opencv_smoke" > "$run/smoke.log" 2>&1
  grep -q 'image and matrix smoke checks passed' "$run/smoke.log"
  python3 "$repo/ci/macos-dls-study.py" "record:$label" "$root" "$evidence" "$jobs"
  python3 "$repo/ci/dls-source-evidence.py" compare --results "$evidence" --platform macos
done
python3 "$repo/ci/macos-dls-study.py" finish "$root" "$evidence" "$jobs"

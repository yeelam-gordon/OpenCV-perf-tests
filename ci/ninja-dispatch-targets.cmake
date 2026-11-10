set(OPENCV_CMAKE_CPU_OPTIMIZATIONS_FORCE_TARGETS ON CACHE BOOL
    "Use the same dispatched object-target structure as the Visual Studio generator" FORCE)

foreach(lang IN ITEMS C CXX)
  set(CMAKE_${lang}_FLAGS_INIT
    "${CMAKE_${lang}_FLAGS_INIT} /D_MBCS /D_ARM64_WINAPI_PARTITION_DESKTOP_SDK_AVAILABLE=1 /Oy-"
    CACHE STRING "Reference MSBuild preprocessing and frame-pointer options" FORCE)
endforeach()

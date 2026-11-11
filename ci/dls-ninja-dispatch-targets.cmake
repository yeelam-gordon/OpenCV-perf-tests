include("${CMAKE_CURRENT_LIST_DIR}/ninja-dispatch-targets.cmake")
set(CMAKE_PROJECT_INCLUDE "${CMAKE_CURRENT_LIST_DIR}/dls-ninja-definitions.cmake"
    CACHE FILEPATH "Match Visual Studio shared-library preprocessing" FORCE)

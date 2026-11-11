foreach(name IN ITEMS unit alloc parallel backend backend_plugin)
  file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/${name}.cpp" "#error This fixture must never compile\n")
endforeach()
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/unit.c" "#error This fixture must never compile\n")
add_library(opencv_world SHARED "${CMAKE_CURRENT_BINARY_DIR}/unit.cpp" "${CMAKE_CURRENT_BINARY_DIR}/unit.c"
  "${CMAKE_CURRENT_BINARY_DIR}/alloc.cpp" "${CMAKE_CURRENT_BINARY_DIR}/parallel.cpp"
  "${CMAKE_CURRENT_BINARY_DIR}/backend.cpp" "${CMAKE_CURRENT_BINARY_DIR}/backend_plugin.cpp")
target_compile_options(opencv_world PRIVATE /MP /EHa)
set_source_files_properties("${CMAKE_CURRENT_BINARY_DIR}/alloc.cpp" PROPERTIES
  COMPILE_DEFINITIONS "HAVE_MALLOC_H=1;HAVE_WIN32_ALIGNED_MALLOC=1")
set_source_files_properties("${CMAKE_CURRENT_BINARY_DIR}/parallel.cpp" PROPERTIES
  COMPILE_DEFINITIONS "PARALLEL_ENABLE_PLUGINS;DEBUG_POSTFIX=\"d\"")
set_source_files_properties("${CMAKE_CURRENT_BINARY_DIR}/backend.cpp" "${CMAKE_CURRENT_BINARY_DIR}/backend_plugin.cpp"
  PROPERTIES COMPILE_DEFINITIONS "DEBUG_POSTFIX=\"d\"")
add_library(dispatched OBJECT "${CMAKE_CURRENT_BINARY_DIR}/unit.cpp")
add_library(static STATIC "${CMAKE_CURRENT_BINARY_DIR}/unit.cpp")

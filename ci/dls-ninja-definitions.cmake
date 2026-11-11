# Visual Studio adds _WINDLL for DLL targets, but not dispatched object targets.
add_compile_definitions("$<$<STREQUAL:$<TARGET_PROPERTY:TYPE>,SHARED_LIBRARY>:_WINDLL>")

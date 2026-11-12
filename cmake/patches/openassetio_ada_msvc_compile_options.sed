# Applied to ada's src/CMakeLists.txt (see cmake/dependencies/openassetio.cmake) with cmake/scripts/apply_sed_filter.cmake.
#
# ada 2.7.4 adds its MSVC flags as INTERFACE compile options, so every target linking ada (here openassetio-core) is compiled with /WX and /sdl, and
# OpenAssetIO's own MSVC warnings (C4251, C4996) become errors. Apply the flags to ada itself only, and without /WX.
s|target_compile_options(ada INTERFACE /WX /W3 /sdl /w34714)|target_compile_options(ada PRIVATE /W3 /sdl /w34714)|

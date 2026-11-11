#
# Copyright Contributors to the OpenRV Project
#
# SPDX-License-Identifier: Apache-2.0
#

#
# OpenAssetIO https://github.com/OpenAssetIO/OpenAssetIO
#
# Builds the OpenAssetIO C++ libraries and Python bindings against RV's Python, then stages:
#
# * the shared libraries (openassetio, openassetio-python, openassetio-ui) into RV_STAGE_LIB_DIR (RV_STAGE_BIN_DIR for Windows DLLs),
# * the 'openassetio' Python package (and its dist-info) into RV_STAGE_PLUGINS_PYTHON_DIR.
#
# OpenAssetIO's own build dependencies (pybind11, toml++, fmt, ada and PCRE2) are header-only or statically linked into the OpenAssetIO libraries with hidden
# symbols. They are built into a private prefix that only the OpenAssetIO build sees, so they never conflict with RV's copies of the same libraries.
#

RV_CREATE_STANDARD_DEPS_VARIABLES("RV_DEPS_OPENASSETIO" "${RV_DEPS_OPENASSETIO_VERSION}" "" "" FORCE_LIB)
RV_SHOW_STANDARD_DEPS_VARIABLES()

SET(_openassetio_private_deps_dir
    ${_base_dir}/private-deps
)
SET(_openassetio_private_prefix
    ${_openassetio_private_deps_dir}/install
)

#
# _RV_OPENASSETIO_ADD_PRIVATE_DEPENDENCY
#
# Builds one of OpenAssetIO's build-only dependencies and installs it into the private prefix.
#
# cmake-format: off
# Usage:
#   _RV_OPENASSETIO_ADD_PRIVATE_DEPENDENCY(
#     NAME <name>              # REQUIRED: suffix of the RV_DEPS_OPENASSETIO_<name> target
#     VERSION <version>        # REQUIRED: used to name the downloaded archive
#     URL <url>                # REQUIRED: source archive
#     URL_MD5 <md5>            # REQUIRED: source archive hash
#     [PATCH_COMMAND <cmd>...] # Command run in the source directory after extraction
#     [CMAKE_ARGS <arg1>...]   # Extra CMake configure arguments
#   )
# cmake-format: on
FUNCTION(_RV_OPENASSETIO_ADD_PRIVATE_DEPENDENCY)
  CMAKE_PARSE_ARGUMENTS(_ARG "" "NAME;VERSION;URL;URL_MD5" "PATCH_COMMAND;CMAKE_ARGS" ${ARGN})

  SET(_dep_target
      RV_DEPS_OPENASSETIO_${_ARG_NAME}
  )
  SET(_dep_source_dir
      ${_openassetio_private_deps_dir}/${_ARG_NAME}/src
  )
  SET(_dep_build_dir
      ${_openassetio_private_deps_dir}/${_ARG_NAME}/build
  )

  EXTERNALPROJECT_ADD(
    ${_dep_target}
    URL ${_ARG_URL}
    URL_MD5 ${_ARG_URL_MD5}
    DOWNLOAD_NAME ${_dep_target}_${_ARG_VERSION}.tar.gz
    DOWNLOAD_DIR ${RV_DEPS_DOWNLOAD_DIR}
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    SOURCE_DIR ${_dep_source_dir}
    BINARY_DIR ${_dep_build_dir}
    INSTALL_DIR ${_openassetio_private_prefix}
    PATCH_COMMAND "${_ARG_PATCH_COMMAND}"
    CONFIGURE_COMMAND
      ${CMAKE_COMMAND} -S ${_dep_source_dir} -B ${_dep_build_dir} "-DCMAKE_INSTALL_PREFIX=${_openassetio_private_prefix}" "-DCMAKE_INSTALL_LIBDIR=lib"
      "-DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE}" "-DCMAKE_OSX_ARCHITECTURES=${CMAKE_OSX_ARCHITECTURES}" "-DCMAKE_POSITION_INDEPENDENT_CODE=ON"
      "-DBUILD_SHARED_LIBS=OFF" ${_ARG_CMAKE_ARGS}
    BUILD_COMMAND ${CMAKE_COMMAND} --build ${_dep_build_dir} --config ${CMAKE_BUILD_TYPE} -j${_cpu_count}
    INSTALL_COMMAND ${CMAKE_COMMAND} --install ${_dep_build_dir} --prefix ${_openassetio_private_prefix} --config ${CMAKE_BUILD_TYPE}
    BUILD_IN_SOURCE FALSE
    BUILD_ALWAYS FALSE
    USES_TERMINAL_BUILD TRUE
  )

  ADD_CUSTOM_TARGET(
    clean-${_dep_target}
    COMMENT "Cleaning '${_dep_target}' ..."
    COMMAND ${CMAKE_COMMAND} -E remove_directory ${_openassetio_private_deps_dir}/${_ARG_NAME}
    COMMAND ${CMAKE_COMMAND} -E remove_directory ${RV_DEPS_BASE_DIR}/cmake/dependencies/${_dep_target}-prefix
  )
ENDFUNCTION()

# pybind11 is only needed for its headers and CMake helpers. PYBIND11_NOPYTHON stops it from looking for a Python at this stage; OpenAssetIO finds RV's Python
# itself below.
_RV_OPENASSETIO_ADD_PRIVATE_DEPENDENCY(
  NAME
  PYBIND11
  VERSION
  ${RV_DEPS_OPENASSETIO_PYBIND11_VERSION}
  URL
  "https://github.com/pybind/pybind11/archive/refs/tags/v${RV_DEPS_OPENASSETIO_PYBIND11_VERSION}.tar.gz"
  URL_MD5
  ${RV_DEPS_OPENASSETIO_PYBIND11_DOWNLOAD_HASH}
  CMAKE_ARGS
  "-DPYBIND11_TEST=OFF"
  "-DPYBIND11_INSTALL=ON"
  "-DPYBIND11_NOPYTHON=ON"
)

_RV_OPENASSETIO_ADD_PRIVATE_DEPENDENCY(
  NAME
  TOMLPLUSPLUS
  VERSION
  ${RV_DEPS_OPENASSETIO_TOMLPLUSPLUS_VERSION}
  URL
  "https://github.com/marzer/tomlplusplus/archive/refs/tags/v${RV_DEPS_OPENASSETIO_TOMLPLUSPLUS_VERSION}.tar.gz"
  URL_MD5
  ${RV_DEPS_OPENASSETIO_TOMLPLUSPLUS_DOWNLOAD_HASH}
)

# OpenAssetIO only uses fmt::fmt-header-only, but fmt's install exports both targets.
_RV_OPENASSETIO_ADD_PRIVATE_DEPENDENCY(
  NAME
  FMT
  VERSION
  ${RV_DEPS_OPENASSETIO_FMT_VERSION}
  URL
  "https://github.com/fmtlib/fmt/archive/refs/tags/${RV_DEPS_OPENASSETIO_FMT_VERSION}.tar.gz"
  URL_MD5
  ${RV_DEPS_OPENASSETIO_FMT_DOWNLOAD_HASH}
  CMAKE_ARGS
  "-DFMT_TEST=OFF"
  "-DFMT_DOC=OFF"
  "-DFMT_INSTALL=ON"
)

_RV_OPENASSETIO_ADD_PRIVATE_DEPENDENCY(
  NAME
  ADA
  VERSION
  ${RV_DEPS_OPENASSETIO_ADA_VERSION}
  URL
  "https://github.com/ada-url/ada/archive/refs/tags/v${RV_DEPS_OPENASSETIO_ADA_VERSION}.tar.gz"
  URL_MD5
  ${RV_DEPS_OPENASSETIO_ADA_DOWNLOAD_HASH}
  PATCH_COMMAND
  ${CMAKE_COMMAND}
  -DINPUT_FILE=src/CMakeLists.txt
  -DOUTPUT_FILE=src/CMakeLists.txt
  -DSED_FILE=${PROJECT_SOURCE_DIR}/cmake/patches/openassetio_ada_msvc_compile_options.sed
  -P
  ${PROJECT_SOURCE_DIR}/cmake/scripts/apply_sed_filter.cmake
  CMAKE_ARGS
  "-DBUILD_TESTING=OFF"
  "-DADA_TOOLS=OFF"
  "-DADA_BENCHMARKS=OFF"
)

# Static 8-bit PCRE2 with JIT, which OpenAssetIO requires (it JIT-compiles its URL patterns). RV's own PCRE2 (cmake/dependencies/pcre2.cmake) is a Windows-only
# shared library without JIT; this copy is linked privately into libopenassetio.
_RV_OPENASSETIO_ADD_PRIVATE_DEPENDENCY(
  NAME
  PCRE2
  VERSION
  ${RV_DEPS_OPENASSETIO_PCRE2_VERSION}
  URL
  "https://github.com/PCRE2Project/pcre2/releases/download/pcre2-${RV_DEPS_OPENASSETIO_PCRE2_VERSION}/pcre2-${RV_DEPS_OPENASSETIO_PCRE2_VERSION}.tar.gz"
  URL_MD5
  ${RV_DEPS_OPENASSETIO_PCRE2_DOWNLOAD_HASH}
  CMAKE_ARGS
  "-DBUILD_STATIC_LIBS=ON"
  "-DPCRE2_STATIC_PIC=ON"
  "-DPCRE2_BUILD_PCRE2_8=ON"
  "-DPCRE2_SUPPORT_JIT=ON"
  "-DPCRE2_BUILD_PCRE2_16=OFF"
  "-DPCRE2_BUILD_PCRE2_32=OFF"
  "-DPCRE2_BUILD_PCRE2GREP=OFF"
  "-DPCRE2_BUILD_TESTS=OFF"
  "-DPCRE2_SUPPORT_LIBBZ2=OFF"
  "-DPCRE2_SUPPORT_LIBZ=OFF"
  "-DPCRE2_SUPPORT_LIBREADLINE=OFF"
  "-DPCRE2_SUPPORT_LIBEDIT=OFF"
  "-DINSTALL_MSVC_PDB=OFF"
)

SET(_openassetio_private_dependencies
    RV_DEPS_OPENASSETIO_PYBIND11 RV_DEPS_OPENASSETIO_TOMLPLUSPLUS RV_DEPS_OPENASSETIO_FMT RV_DEPS_OPENASSETIO_ADA RV_DEPS_OPENASSETIO_PCRE2
)

#
# OpenAssetIO itself
#

# Install the Python package with the same layout relative to the install root as the RV stage (e.g. PlugIns/Python next to lib). OpenAssetIO derives the
# extension module's RPATH from this layout ($ORIGIN/../../../lib), so it stays valid once both are staged.
FILE(RELATIVE_PATH _openassetio_python_sitedir ${RV_STAGE_ROOT_DIR} ${RV_STAGE_PLUGINS_PYTHON_DIR})
SET(_openassetio_python_install_dir
    ${_install_dir}/${_openassetio_python_sitedir}
)

SET(_python3_install_dir
    ${RV_DEPS_BASE_DIR}/RV_DEPS_PYTHON3/install
)
IF(RV_TARGET_WINDOWS)
  SET(_openassetio_python_executable
      ${_python3_install_dir}/bin/python${PYTHON3_EXTRA_WIN_LIBRARY_SUFFIX_IF_DEBUG}.exe
  )
ELSE()
  SET(_openassetio_python_executable
      ${_python3_install_dir}/bin/python3
  )
ENDIF()

LIST(APPEND _configure_options "-DCMAKE_PREFIX_PATH=${_openassetio_private_prefix}")
LIST(APPEND _configure_options "-DCMAKE_INSTALL_LIBDIR=lib")
LIST(APPEND _configure_options "-DBUILD_SHARED_LIBS=ON")
LIST(APPEND _configure_options "-DOPENASSETIO_ENABLE_PYTHON=ON")
LIST(APPEND _configure_options "-DOPENASSETIO_PYTHON_SITEDIR=${_openassetio_python_sitedir}")
# Keeps a dist-info next to the package, so tools inspecting the environment (importlib.metadata, pip) see OpenAssetIO as installed.
LIST(APPEND _configure_options "-DOPENASSETIO_ENABLE_PYTHON_INSTALL_DIST_INFO=ON")
# Stub generation needs pybind11-stubgen in RV's Python, and .pyi files are not useful at runtime.
LIST(APPEND _configure_options "-DOPENASSETIO_ENABLE_PYTHON_STUBGEN=OFF")
LIST(APPEND _configure_options "-DOPENASSETIO_ENABLE_C=OFF")
LIST(APPEND _configure_options "-DOPENASSETIO_ENABLE_TESTS=OFF")
LIST(APPEND _configure_options "-DOPENASSETIO_ENABLE_SIMPLECPPMANAGER=OFF")
# Force CMake to use RV's Python, not a system/registry one (see cmake/dependencies/ocio.cmake).
LIST(APPEND _configure_options "-DPython_ROOT_DIR=${_python3_install_dir}")
LIST(APPEND _configure_options "-DPython_EXECUTABLE=${_openassetio_python_executable}")
LIST(APPEND _configure_options "-DPython_FIND_REGISTRY=NEVER")
LIST(APPEND _configure_options "-DPython_FIND_FRAMEWORK=NEVER")
LIST(APPEND _configure_options "-DPython_FIND_STRATEGY=LOCATION")
IF(RV_TARGET_WINDOWS)
  LIST(APPEND _configure_options "-DPython_INCLUDE_DIR=${_python3_install_dir}/include")
  LIST(APPEND _configure_options
       "-DPython_LIBRARY=${_python3_install_dir}/libs/python${PYTHON_VERSION_MAJOR}${PYTHON_VERSION_MINOR}${PYTHON3_EXTRA_WIN_LIBRARY_SUFFIX_IF_DEBUG}.lib"
  )
ENDIF()

SET(_openassetio_libnames
    openassetio openassetio-python openassetio-ui
)
SET(_byproducts
    ${_openassetio_python_install_dir}/openassetio/__init__.py ${_openassetio_python_install_dir}/openassetio_mediacreation/__init__.py
)
FOREACH(
  _openassetio_libname
  ${_openassetio_libnames}
)
  IF(RV_TARGET_WINDOWS)
    LIST(APPEND _byproducts ${_bin_dir}/${_openassetio_libname}${CMAKE_SHARED_LIBRARY_SUFFIX})
    LIST(APPEND _byproducts ${_lib_dir}/${_openassetio_libname}${CMAKE_IMPORT_LIBRARY_SUFFIX})
  ELSE()
    LIST(APPEND _byproducts ${_lib_dir}/${CMAKE_SHARED_LIBRARY_PREFIX}${_openassetio_libname}${CMAKE_SHARED_LIBRARY_SUFFIX})
  ENDIF()
ENDFOREACH()

EXTERNALPROJECT_ADD(
  ${_target}
  URL "https://github.com/OpenAssetIO/OpenAssetIO/archive/refs/tags/v${_version}.tar.gz"
  URL_MD5 ${RV_DEPS_OPENASSETIO_DOWNLOAD_HASH}
  DOWNLOAD_NAME ${_target}_${_version}.tar.gz
  DOWNLOAD_DIR ${RV_DEPS_DOWNLOAD_DIR}
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
  SOURCE_DIR ${_source_dir}
  BINARY_DIR ${_build_dir}
  INSTALL_DIR ${_install_dir}
  CONFIGURE_COMMAND ${CMAKE_COMMAND} ${_configure_options}
  BUILD_COMMAND ${_cmake_build_command}
  INSTALL_COMMAND ${_cmake_install_command}
  # OpenAssetIO-MediaCreation provides the standard media traits (e.g. LocatableContentTrait). It is pure Python, so its wheel is safe to use. --no-deps stops
  # pip from fetching a second openassetio from PyPI, since this one lives outside RV's Python site-packages.
  COMMAND "${_openassetio_python_executable}" -s -E -I -m pip install --no-deps --only-binary=:all: --no-compile --disable-pip-version-check --upgrade --target
          "${_openassetio_python_install_dir}" "openassetio-mediacreation==${RV_DEPS_OPENASSETIO_MEDIACREATION_VERSION}"
  BUILD_IN_SOURCE FALSE
  BUILD_ALWAYS FALSE
  BUILD_BYPRODUCTS ${_byproducts}
  USES_TERMINAL_BUILD TRUE
  DEPENDS Python::Python ${_openassetio_private_dependencies}
)

#
# Imported targets for the C++ libraries, staged into the RV lib/bin directories.
#

SET(_openassetio_target_names
    OpenAssetIO::openassetio-core OpenAssetIO::openassetio-python-bridge OpenAssetIO::openassetio-ui
)
FOREACH(
  _openassetio_libname
  _openassetio_target_name IN ZIP_LISTS _openassetio_libnames _openassetio_target_names
)
  IF(RV_TARGET_WINDOWS)
    SET(_openassetio_libpath
        ${_bin_dir}/${_openassetio_libname}${CMAKE_SHARED_LIBRARY_SUFFIX}
    )
    SET(_openassetio_implibpath
        ${_lib_dir}/${_openassetio_libname}${CMAKE_IMPORT_LIBRARY_SUFFIX}
    )
  ELSE()
    SET(_openassetio_libpath
        ${_lib_dir}/${CMAKE_SHARED_LIBRARY_PREFIX}${_openassetio_libname}${CMAKE_SHARED_LIBRARY_SUFFIX}
    )
    SET(_openassetio_implibpath
        ""
    )
  ENDIF()
  GET_FILENAME_COMPONENT(_openassetio_soname ${_openassetio_libpath} NAME)

  RV_ADD_IMPORTED_LIBRARY(
    NAME
    ${_openassetio_target_name}
    TYPE
    SHARED
    LOCATION
    ${_openassetio_libpath}
    SONAME
    ${_openassetio_soname}
    IMPLIB
    ${_openassetio_implibpath}
    INCLUDE_DIRS
    ${_include_dir}
    DEPENDS
    ${_target}
    ADD_TO_DEPS_LIST
  )
ENDFOREACH()
TARGET_LINK_LIBRARIES(
  OpenAssetIO::openassetio-python-bridge
  INTERFACE OpenAssetIO::openassetio-core
)
TARGET_LINK_LIBRARIES(
  OpenAssetIO::openassetio-ui
  INTERFACE OpenAssetIO::openassetio-core
)

RV_STAGE_DEPENDENCY_LIBS(TARGET ${_target} TARGET_LIBS ${_openassetio_target_names})

#
# Stage the Python package.
#

SET(_openassetio_stage_python_package_dir
    ${RV_STAGE_PLUGINS_PYTHON_DIR}/openassetio
)
SET(_openassetio_python_stage_commands
    COMMAND ${CMAKE_COMMAND} -E copy_directory ${_openassetio_python_install_dir} ${RV_STAGE_PLUGINS_PYTHON_DIR}
)
IF(RV_TARGET_WINDOWS)
  # Windows has no RPATH: put the DLLs next to the extension module so Python finds them through LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR, whichever executable loads
  # the package (see the PyOpenColorIO staging in cmake/dependencies/ocio.cmake).
  FOREACH(
    _openassetio_libname
    ${_openassetio_libnames}
  )
    LIST(
      APPEND
      _openassetio_python_stage_commands
      COMMAND
      ${CMAKE_COMMAND}
      -E
      copy_if_different
      ${_bin_dir}/${_openassetio_libname}${CMAKE_SHARED_LIBRARY_SUFFIX}
      ${_openassetio_stage_python_package_dir}/
    )
  ENDFOREACH()
ENDIF()

ADD_CUSTOM_COMMAND(
  COMMENT "Staging the OpenAssetIO Python package into ${RV_STAGE_PLUGINS_PYTHON_DIR}"
  OUTPUT ${_openassetio_stage_python_package_dir}/__init__.py ${_openassetio_python_stage_commands}
  COMMAND ${CMAKE_COMMAND} -E touch_nocreate ${_openassetio_stage_python_package_dir}/__init__.py
  # Depend on every installed file, not only the Python sources: cmake --install keeps the timestamps of unchanged files, so a rebuilt library alone must still
  # trigger re-staging (on Windows the DLLs are copied next to the extension module).
  DEPENDS ${_target} ${_byproducts}
  VERBATIM
)
ADD_CUSTOM_TARGET(
  ${_target}-python-stage-target ALL
  DEPENDS ${_openassetio_stage_python_package_dir}/__init__.py
)
ADD_DEPENDENCIES(dependencies ${_target}-python-stage-target)

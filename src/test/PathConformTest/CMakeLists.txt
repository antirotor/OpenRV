#
# Copyright Contributors to the OpenRV Project
#
# SPDX-License-Identifier: Apache-2.0
#

INCLUDE(cxx_defaults)

SET(_target
    "PathConformTest"
)

LIST(APPEND _sources main.cpp)

ADD_EXECUTABLE(
  ${_target}
  ${_sources}
)

TARGET_LINK_LIBRARIES(
  ${_target}
  PRIVATE TwkUtil doctest::doctest
)

ADD_TEST(
  NAME ${_target}
  COMMAND ${CMAKE_COMMAND} -E env LD_LIBRARY_PATH=${RV_STAGE_LIB_DIR} "$<TARGET_FILE:${_target}>"
)

RV_STAGE(TYPE "EXECUTABLE" TARGET ${_target})

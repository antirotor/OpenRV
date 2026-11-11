#
# Copyright Contributors to the OpenRV Project
#
# SPDX-License-Identifier: Apache-2.0
#

IF(NOT RV_ENABLE_OPENASSETIO)
  RETURN()
ENDIF()

SET(_target
    "openassetio_mode"
)

RV_STAGE(TYPE "RVPKG" TARGET ${_target})

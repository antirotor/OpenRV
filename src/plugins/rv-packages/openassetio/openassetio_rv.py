#
# Copyright Contributors to the OpenRV Project
#
# SPDX-License-Identifier: Apache-2.0
#
"""
OpenAssetIO host support for RV: resolves entity references to paths RV
can load.

This module does not depend on RV, so it can be used and tested from a
plain Python interpreter. The RV integration (event bindings, menus,
session properties) lives in openassetio_mode.py.
"""

import logging
import os
import re

from openassetio.access import ResolveAccess
from openassetio.errors import OpenAssetIOException
from openassetio.hostApi import HostInterface, ManagerFactory
from openassetio.log import LoggerInterface, SeverityFilter
from openassetio.pluginSystem import (
    CppPluginSystemManagerImplementationFactory,
    HybridPluginSystemManagerImplementationFactory,
    PythonPluginSystemManagerImplementationFactory,
)
from openassetio.utils import FileUrlPathConverter
from openassetio_mediacreation.traits.content import LocatableContentTrait_v1
from openassetio_mediacreation.traits.timeDomain import FrameRangedTrait_v1

logger = logging.getLogger("OpenAssetIO")

HOST_IDENTIFIER = "io.aswf.openrv"
HOST_DISPLAY_NAME = "OpenRV"

# The traits requested when resolving an entity for viewing.
RESOLVE_TRAIT_SET = {LocatableContentTrait_v1.kId, FrameRangedTrait_v1.kId}

# {frame}, {frame:d}, {frame:4d} or {frame:04d} in a templated location (see LocatableContentTrait_v1.getIsTemplated).
_FRAME_VARIABLE_RE = re.compile(r"\{frame(?::0?(\d*)d?)?\}")
# Any other variable left once the frame variable is replaced. Doubled braces are literal braces.
_OTHER_VARIABLE_RE = re.compile(r"(?<!\{)\{([A-Za-z_][^{}]*)\}(?!\})")


class ResolveError(Exception):
    """An entity reference could not be resolved to a loadable path."""


def is_configured():
    """
    Return whether a default OpenAssetIO manager is configured. Cheap to
    call: does not load any plugin.
    """
    return bool(os.environ.get(ManagerFactory.kDefaultManagerConfigEnvVarName))


def location_to_path(location):
    """
    Convert a LocatableContent location URL to something RV can open.

    file:// URLs become local paths, with forward slashes on Windows as
    everywhere else in RV. Other URLs (e.g. http) are returned unchanged,
    since RV opens them directly.
    """
    if not location.startswith("file:"):
        return location
    path = FileUrlPathConverter().pathFromUrl(location)
    if os.name == "nt":
        path = path.replace("\\", "/")
    return path


def template_to_rv_sequence(path, start_frame=None, end_frame=None):
    """
    Convert a templated location (after URL decoding) to RV's sequence
    syntax: "{frame:04d}" becomes "%04d", prefixed with the frame range
    when it is known (e.g. "plate.1001-1100%04d.exr").

    Raise ResolveError for any other template variable, as RV cannot
    expand it.
    """
    frame_range = ""
    if start_frame is not None and end_frame is not None:
        frame_range = f"{start_frame}-{end_frame}"

    def to_printf(match):
        width = match.group(1)
        return frame_range + (f"%0{width}d" if width else "%d")

    sequence = _FRAME_VARIABLE_RE.sub(to_printf, path)

    others = _OTHER_VARIABLE_RE.findall(sequence)
    if others:
        raise ResolveError(f"Unsupported template variables in '{path}': {', '.join(sorted(set(others)))}")

    return sequence.replace("{{", "{").replace("}}", "}")


class _HostInterface(HostInterface):
    def identifier(self):
        return HOST_IDENTIFIER

    def displayName(self):
        return HOST_DISPLAY_NAME


class _PythonLogger(LoggerInterface):
    """Forwards OpenAssetIO log messages to the Python logging module."""

    _LEVELS = {
        LoggerInterface.Severity.kCritical: logging.CRITICAL,
        LoggerInterface.Severity.kError: logging.ERROR,
        LoggerInterface.Severity.kWarning: logging.WARNING,
        LoggerInterface.Severity.kProgress: logging.INFO,
        LoggerInterface.Severity.kInfo: logging.INFO,
        LoggerInterface.Severity.kDebug: logging.DEBUG,
        LoggerInterface.Severity.kDebugApi: logging.DEBUG,
    }

    def log(self, severity, message):
        logger.log(self._LEVELS.get(severity, logging.INFO), message)


class Resolver:
    """
    Resolves entity references through the default OpenAssetIO manager
    (configured with $OPENASSETIO_DEFAULT_CONFIG).

    The manager is loaded on first use. All resolves share one Context
    until reset_context() is called, so a manager can keep results
    stable for the lifetime of an RV session.
    """

    def __init__(self):
        self._manager = None
        self._context = None
        self._initialized = False

    @property
    def manager(self):
        """The default manager, or None if none is configured or it failed to load."""
        if not self._initialized:
            self._initialized = True
            self._manager = self._load_default_manager()
        return self._manager

    def reset_context(self):
        """Start a new context, e.g. for a new RV session."""
        self._context = None

    def is_entity_reference(self, string):
        manager = self.manager
        return manager is not None and manager.isEntityReferenceString(string)

    def resolve_path(self, reference):
        """
        Resolve an entity reference string to a path RV can load.

        Raise ResolveError if the reference cannot be resolved or has no
        location.
        """
        manager = self.manager
        if manager is None:
            raise ResolveError("No OpenAssetIO manager is configured")

        if self._context is None:
            self._context = manager.createContext()

        try:
            entity_reference = manager.createEntityReference(reference)
            traits_data = manager.resolve(entity_reference, RESOLVE_TRAIT_SET, ResolveAccess.kRead, self._context)
        except OpenAssetIOException as error:
            raise ResolveError(f"Could not resolve '{reference}': {error}") from error

        content = LocatableContentTrait_v1(traits_data)
        location = content.getLocation()
        if not location:
            raise ResolveError(f"'{reference}' has no location ({LocatableContentTrait_v1.kId})")

        try:
            path = location_to_path(location)
        except OpenAssetIOException as error:
            raise ResolveError(f"Could not convert the location of '{reference}' to a path: {error}") from error

        if content.getIsTemplated(False):
            frames = FrameRangedTrait_v1(traits_data)
            path = template_to_rv_sequence(path, frames.getStartFrame(), frames.getEndFrame())

        return path

    @staticmethod
    def _load_default_manager():
        if not is_configured():
            return None

        openassetio_logger = SeverityFilter(_PythonLogger())
        factory = HybridPluginSystemManagerImplementationFactory(
            [
                CppPluginSystemManagerImplementationFactory(openassetio_logger),
                PythonPluginSystemManagerImplementationFactory(openassetio_logger),
            ],
            openassetio_logger,
        )

        try:
            manager = ManagerFactory.defaultManagerForInterface(_HostInterface(), factory, openassetio_logger)
        except OpenAssetIOException as error:
            logger.error("Could not load the default OpenAssetIO manager: %s", error)
            return None

        if manager is None:
            return None

        if not manager.hasCapability(manager.Capability.kResolution):
            logger.warning("OpenAssetIO manager '%s' cannot resolve entity references", manager.displayName())
            return None

        logger.info("Using OpenAssetIO manager '%s'", manager.displayName())
        return manager

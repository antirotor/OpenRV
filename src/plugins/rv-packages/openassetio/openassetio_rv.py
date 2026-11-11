#
# Copyright Contributors to the OpenRV Project
#
# SPDX-License-Identifier: Apache-2.0
#
"""
OpenAssetIO host support for RV: resolves entity references to paths RV
can load.

This module depends neither on RV nor on Qt, so it can be used and
tested from a plain Python interpreter. The RV integration (event
bindings, menus, dialogs, session properties) lives in
openassetio_mode.py.
"""

import logging
import os
import re

from openassetio.access import DefaultEntityAccess, ResolveAccess
from openassetio.errors import OpenAssetIOException
from openassetio.hostApi import HostInterface, ManagerFactory
from openassetio.log import LoggerInterface, SeverityFilter
from openassetio.pluginSystem import (
    CppPluginSystemManagerImplementationFactory,
    HybridPluginSystemManagerImplementationFactory,
    PythonPluginSystemManagerImplementationFactory,
)
from openassetio.trait import TraitsData
from openassetio.ui.access import UIAccess
from openassetio.ui.hostApi import UIDelegateFactory, UIDelegateRequestInterface
from openassetio.ui.pluginSystem import (
    CppPluginSystemUIDelegateImplementationFactory,
    HybridPluginSystemUIDelegateImplementationFactory,
    PythonPluginSystemUIDelegateImplementationFactory,
)
from openassetio.utils import FileUrlPathConverter
from openassetio_mediacreation.traits.content import LocatableContentTrait_v1
from openassetio_mediacreation.traits.timeDomain import FrameRangedTrait_v1
from openassetio_mediacreation.traits.ui import BrowserTrait_v1, DetachedTrait_v1, EntityProviderTrait_v1
from openassetio_mediacreation.traits.uiPolicy import ManagedTrait_v1

logger = logging.getLogger("OpenAssetIO")

HOST_IDENTIFIER = "io.aswf.openrv"
HOST_DISPLAY_NAME = "OpenRV"

# The traits requested when resolving an entity for viewing.
RESOLVE_TRAIT_SET = {LocatableContentTrait_v1.kId, FrameRangedTrait_v1.kId}

# The traits of the entities RV can load: anything with a location.
LOADABLE_ENTITY_TRAIT_SET = {LocatableContentTrait_v1.kId}

# The UI requested from the manager's UI delegate to choose entities to load: a browser, returned as a new widget that RV
# places in a dialog, whose state updates carry the chosen entity references.
BROWSER_UI_TRAIT_SET = {BrowserTrait_v1.kId, DetachedTrait_v1.kId, EntityProviderTrait_v1.kId}

# {frame}, {frame:d}, {frame:4d} or {frame:04d} in a templated location (see LocatableContentTrait_v1.getIsTemplated).
_FRAME_VARIABLE_RE = re.compile(r"\{frame(?::0?(\d*)d?)?\}")
# Any other variable left once the frame variable is replaced. Doubled braces are literal braces.
_OTHER_VARIABLE_RE = re.compile(r"(?<!\{)\{([A-Za-z_][^{}]*)\}(?!\})")


class ResolveError(Exception):
    """An entity reference could not be resolved to a loadable path."""


# Manager and UI delegate plugins are third-party code that may raise any exception, not only OpenAssetIO's. Calls into
# them catch Exception, so that a failing plugin is reported instead of breaking RV's event handling.
_PLUGIN_ERRORS = (Exception,)


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


class _BrowserRequest(UIDelegateRequestInterface):
    """The request RV makes to a UI delegate for a browser of loadable entities."""

    def __init__(self, state_changed_callback):
        UIDelegateRequestInterface.__init__(self)
        self._state_changed_callback = state_changed_callback
        self._entity_traits_data = TraitsData()
        LocatableContentTrait_v1.imbueTo(self._entity_traits_data)

    def entityReferences(self):
        return []

    def entityTraitsDatas(self):
        return [self._entity_traits_data]

    def nativeData(self):
        return None

    def stateChangedCallback(self):
        return self._state_changed_callback


class Browser:
    """
    An asset browser provided by the manager's UI delegate, to choose
    entities to load. See Resolver.create_browser().
    """

    def __init__(self, ui_delegate, context, on_selection_changed=None):
        self._on_selection_changed = on_selection_changed
        self._entity_references = []
        # Keep the request alive as long as the browser: the UI delegate calls back through it.
        self._request = _BrowserRequest(self._state_changed)

        ui_traits_data = TraitsData()
        for trait_id in BROWSER_UI_TRAIT_SET:
            ui_traits_data.addTrait(trait_id)
        self._state = ui_delegate.populateUI(ui_traits_data, UIAccess.kRead, self._request, context)
        if self._state is None:
            raise ResolveError(f"The UI delegate '{ui_delegate.displayName()}' did not provide a browser")
        self._entity_references = self._references_of(self._state)

    @property
    def widget(self):
        """The UI element provided by the UI delegate (a QWidget for a Qt delegate), for RV to attach."""
        return self._state.nativeData()

    @property
    def entity_references(self):
        """The entity reference strings currently chosen in the browser."""
        return list(self._entity_references)

    def _state_changed(self, state):
        self._state = state
        self._entity_references = self._references_of(state)
        if self._on_selection_changed is not None:
            self._on_selection_changed(self.entity_references)

    @staticmethod
    def _references_of(state):
        return [reference.toString() for reference in state.entityReferences()]


class Resolver:
    """
    Resolves entity references through the default OpenAssetIO manager
    (configured with $OPENASSETIO_DEFAULT_CONFIG), and provides the UI
    to choose them.

    The manager and its UI delegate are loaded on first use. All calls
    share one Context until reset_context() is called, so a manager can
    keep results stable for the lifetime of an RV session.
    """

    def __init__(self):
        self._openassetio_logger = SeverityFilter(_PythonLogger())
        self._host_interface = _HostInterface()
        self._manager = None
        self._manager_initialized = False
        self._ui_delegate = None
        self._ui_delegate_initialized = False
        self._context = None

    @property
    def manager(self):
        """The default manager, or None if none is configured or it failed to load."""
        if not self._manager_initialized:
            self._manager_initialized = True
            self._manager = self._load_default_manager()
        return self._manager

    @property
    def ui_delegate(self):
        """The UI delegate of the default manager, or None if it has none."""
        if not self._ui_delegate_initialized:
            self._ui_delegate_initialized = True
            if self.manager is not None:
                self._ui_delegate = self._load_default_ui_delegate()
        return self._ui_delegate

    @property
    def context(self):
        if self._context is None:
            self._context = self.manager.createContext()
        return self._context

    def reset_context(self):
        """Start a new context, e.g. for a new RV session."""
        self._context = None

    def is_entity_reference(self, string):
        manager = self.manager
        if manager is None:
            return False
        try:
            return manager.isEntityReferenceString(string)
        except _PLUGIN_ERRORS as error:
            logger.error("Could not check whether '%s' is an entity reference: %s", string, error)
            return False

    def resolve_path(self, reference):
        """
        Resolve an entity reference string to a path RV can load.

        Raise ResolveError if the reference cannot be resolved or has no
        location.
        """
        manager = self.manager
        if manager is None:
            raise ResolveError("No OpenAssetIO manager is configured")

        try:
            entity_reference = manager.createEntityReference(reference)
            traits_data = manager.resolve(entity_reference, RESOLVE_TRAIT_SET, ResolveAccess.kRead, self.context)
        except _PLUGIN_ERRORS as error:
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

    def default_entity_reference(self):
        """
        The manager's default entity reference for loading media (e.g. the
        current shot), or None if it has none.
        """
        manager = self.manager
        if manager is None or not manager.hasCapability(manager.Capability.kDefaultEntityReferences):
            return None

        try:
            reference = manager.defaultEntityReference(
                LOADABLE_ENTITY_TRAIT_SET, DefaultEntityAccess.kRead, self.context
            )
        except _PLUGIN_ERRORS as error:
            logger.warning("Could not get the default entity reference: %s", error)
            return None

        return reference.toString() if reference is not None else None

    def can_browse(self):
        """Whether the manager's UI delegate provides a browser to choose entities to load."""
        ui_delegate = self.ui_delegate
        if ui_delegate is None:
            return False

        try:
            policy = ui_delegate.uiPolicy(BROWSER_UI_TRAIT_SET, UIAccess.kRead, self.context)
        except _PLUGIN_ERRORS as error:
            logger.warning("Could not query the UI policy of '%s': %s", ui_delegate.displayName(), error)
            return False

        return ManagedTrait_v1.isImbuedTo(policy)

    def create_browser(self, on_selection_changed=None):
        """
        Create the manager's asset browser. on_selection_changed is called
        with the list of chosen entity reference strings whenever the
        selection changes.

        Raise ResolveError if the browser cannot be created; check
        can_browse() first.
        """
        ui_delegate = self.ui_delegate
        if ui_delegate is None:
            raise ResolveError("The OpenAssetIO manager has no UI delegate")

        try:
            return Browser(ui_delegate, self.context, on_selection_changed)
        except ResolveError:
            raise
        except _PLUGIN_ERRORS as error:
            raise ResolveError(f"Could not create the browser of '{ui_delegate.displayName()}': {error}") from error

    def _load_default_manager(self):
        if not is_configured():
            return None

        factory = HybridPluginSystemManagerImplementationFactory(
            [
                CppPluginSystemManagerImplementationFactory(self._openassetio_logger),
                PythonPluginSystemManagerImplementationFactory(self._openassetio_logger),
            ],
            self._openassetio_logger,
        )

        try:
            manager = ManagerFactory.defaultManagerForInterface(self._host_interface, factory, self._openassetio_logger)
        except _PLUGIN_ERRORS as error:
            logger.error("Could not load the default OpenAssetIO manager: %s", error)
            return None

        if manager is None:
            return None

        if not manager.hasCapability(manager.Capability.kResolution):
            logger.warning("OpenAssetIO manager '%s' cannot resolve entity references", manager.displayName())
            return None

        logger.info("Using OpenAssetIO manager '%s'", manager.displayName())
        return manager

    def _load_default_ui_delegate(self):
        factory = HybridPluginSystemUIDelegateImplementationFactory(
            [
                CppPluginSystemUIDelegateImplementationFactory(self._openassetio_logger),
                PythonPluginSystemUIDelegateImplementationFactory(self._openassetio_logger),
            ],
            self._openassetio_logger,
        )

        try:
            ui_delegate = UIDelegateFactory.defaultUIDelegateForInterface(
                self._host_interface, factory, self._openassetio_logger
            )
        except OpenAssetIOException as error:
            # OpenAssetIO 1.0 raises when the manager has no UI delegate plugin; later versions return None.
            logger.debug("No OpenAssetIO UI delegate: %s", error)
            return None
        except _PLUGIN_ERRORS as error:
            logger.error("Could not load the OpenAssetIO UI delegate: %s", error)
            return None

        if ui_delegate is not None:
            logger.info("Using OpenAssetIO UI delegate '%s'", ui_delegate.displayName())
        return ui_delegate

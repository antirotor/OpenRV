#
# Copyright Contributors to the OpenRV Project
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Loads media from asset management systems through OpenAssetIO.

When $OPENASSETIO_DEFAULT_CONFIG points to an OpenAssetIO manager
configuration, paths given to RV (command line, drag and drop, file
browser, session files) that the manager recognizes as entity references
are resolved to the location of their content before loading.

File > Open from Asset Manager chooses entities to load in the
manager's own browser, when its UI delegate provides one, or else asks
for an entity reference.

The entity reference of each loaded source is kept on its RVFileSource
node, in the openassetio.entityReference property, and saved with the
session. File > Re-resolve Asset References resolves them again, e.g. to
pick up a newer version.
"""

import logging

from rv import commands, extra_commands, qtutils, rvtypes

logger = logging.getLogger("OpenAssetIO")

ENTITY_REFERENCE_PROPERTY = "openassetio.entityReference"

# The tag of the sources added by File > Open from Asset Manager (see the incoming-source-path event).
SOURCE_TAG = "openassetio"


def _qt_widgets():
    try:
        from PySide2 import QtWidgets
    except ImportError:
        from PySide6 import QtWidgets
    return QtWidgets


def _exec_dialog(dialog):
    """Run a modal dialog, with PySide2 (exec_) or PySide6 (exec). Return whether it was accepted."""
    run = getattr(dialog, "exec", None) or dialog.exec_
    return bool(run())


class OpenAssetIOMode(rvtypes.MinorMode):
    def __init__(self):
        rvtypes.MinorMode.__init__(self)

        self._resolver = None
        # Resolved paths waiting for their source node, mapped to their entity reference.
        self._pending_references = {}

        # Importing OpenAssetIO and loading a manager plugin can be slow, so stay inert unless a manager is configured.
        bindings = None
        menu = None
        if self._is_configured():
            bindings = [
                ("incoming-source-path", self._incoming_source_path, "Resolve OpenAssetIO entity references"),
                (
                    "source-group-complete",
                    self._source_group_complete,
                    "Keep the OpenAssetIO entity reference of new sources",
                ),
                (
                    "after-session-read",
                    self._after_session_read,
                    "Keep the OpenAssetIO entity reference of session sources",
                ),
                ("after-clear-session", self._after_clear_session, "Start a new OpenAssetIO context"),
            ]
            menu = [
                (
                    "File",
                    [
                        ("Open from Asset Manager...", self._open_from_asset_manager, None, None),
                        ("Re-resolve Asset References", self._re_resolve_sources, None, self._re_resolve_state),
                    ],
                )
            ]

        self.init("openassetio-mode", bindings, None, menu)

    @staticmethod
    def _is_configured():
        try:
            import openassetio_rv
        except ImportError as error:
            logger.warning("OpenAssetIO is not available: %s", error)
            return False
        return openassetio_rv.is_configured()

    @property
    def resolver(self):
        if self._resolver is None:
            import openassetio_rv

            self._resolver = openassetio_rv.Resolver()
        return self._resolver

    def _incoming_source_path(self, event):
        # Let the other handlers of this event run too.
        event.reject()

        #  The contents look like "path;;tag". A previous handler may already have replaced the path.
        path = event.returnContents() or event.contents().split(";;")[0]
        if not self.resolver.is_entity_reference(path):
            return

        import openassetio_rv

        try:
            resolved_path = self.resolver.resolve_path(path)
        except openassetio_rv.ResolveError as error:
            # Leave the path alone: RV reports it as missing media.
            logger.error("%s", error)
            return

        logger.info("Resolved '%s' to '%s'", path, resolved_path)
        self._pending_references[resolved_path] = path
        event.setReturnContent(resolved_path)

    def _source_group_complete(self, event):
        event.reject()
        group = event.contents().split(";;")[0]
        self._store_references(extra_commands.nodesInGroupOfType(group, "RVFileSource"))

    def _after_session_read(self, event):
        event.reject()
        self._store_references(commands.nodesOfType("RVFileSource"))

    def _after_clear_session(self, event):
        event.reject()
        self._pending_references.clear()
        if self._resolver is not None:
            self._resolver.reset_context()

    def _store_references(self, sources):
        """Set the entity reference property on the sources whose media was resolved by this mode."""
        if not self._pending_references:
            return

        for source in sources:
            for media in commands.getStringProperty(f"{source}.media.movie"):
                reference = self._pending_references.pop(media, None)
                if reference is not None:
                    self._set_entity_reference(source, reference)
                    break

    @staticmethod
    def _set_entity_reference(source, reference):
        name = f"{source}.{ENTITY_REFERENCE_PROPERTY}"
        if not commands.propertyExists(name):
            commands.newProperty(name, commands.StringType, 1)
        commands.setStringProperty(name, [reference], True)

    @staticmethod
    def _entity_reference(source):
        name = f"{source}.{ENTITY_REFERENCE_PROPERTY}"
        if not commands.propertyExists(name):
            return None
        values = commands.getStringProperty(name)
        return values[0] if values else None

    def _referenced_sources(self):
        return [source for source in commands.nodesOfType("RVFileSource") if self._entity_reference(source)]

    def _re_resolve_state(self):
        return commands.NeutralMenuState if self._referenced_sources() else commands.DisabledMenuState

    def _re_resolve_sources(self, event):
        import openassetio_rv

        # A new context, so the manager does not return the results it already gave for this session.
        self.resolver.reset_context()

        updated = 0
        for source in self._referenced_sources():
            reference = self._entity_reference(source)
            try:
                resolved_path = self.resolver.resolve_path(reference)
            except openassetio_rv.ResolveError as error:
                logger.error("%s", error)
                continue

            media = commands.getStringProperty(f"{source}.media.movie")
            if media and media[0] == resolved_path:
                continue

            logger.info("Re-resolved '%s' to '%s'", reference, resolved_path)
            # Keep any additional media (e.g. audio) of the source.
            commands.setSourceMedia(source, [resolved_path] + list(media[1:]))
            updated += 1

        extra_commands.displayFeedback(f"OpenAssetIO: updated {updated} source(s)", 3.0)

    def _open_from_asset_manager(self, event):
        resolver = self.resolver
        if resolver.manager is None:
            extra_commands.displayFeedback("OpenAssetIO: no asset manager is available", 3.0)
            return

        references = self._choose_in_browser() if resolver.can_browse() else self._ask_for_reference()
        if references:
            # Like any other path, the references are resolved by the incoming-source-path event.
            commands.addSources(references, SOURCE_TAG)

    def _choose_in_browser(self):
        """Show the browser of the manager's UI delegate in a dialog. Return the chosen entity references."""
        import openassetio_rv

        QtWidgets = _qt_widgets()
        resolver = self.resolver

        dialog = QtWidgets.QDialog(qtutils.sessionWindow())
        dialog.setWindowTitle(f"Open from {resolver.manager.displayName()}")
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Open | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        open_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Open)

        try:
            browser = resolver.create_browser(lambda references: open_button.setEnabled(bool(references)))
        except openassetio_rv.ResolveError as error:
            logger.error("%s", error)
            return self._ask_for_reference()

        widget = browser.widget
        if not isinstance(widget, QtWidgets.QWidget):
            logger.error("The browser of the OpenAssetIO UI delegate is not a Qt widget: %r", widget)
            return self._ask_for_reference()

        open_button.setEnabled(bool(browser.entity_references))
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(widget)
        layout.addWidget(buttons)
        # Browsers are often complete asset browsing tools (AYON's loader has
        # five panels), cramped at their minimum size: use most of the screen.
        available = dialog.screen().availableGeometry()
        hint = dialog.sizeHint()
        dialog.resize(
            min(max(hint.width(), available.width() * 3 // 4), available.width()),
            min(max(hint.height(), available.height() * 3 // 4), available.height()),
        )

        if not _exec_dialog(dialog):
            return []
        return browser.entity_references

    def _ask_for_reference(self):
        """Ask for an entity reference, starting from the manager's default one. Return it in a list."""
        QtWidgets = _qt_widgets()
        resolver = self.resolver
        manager_name = resolver.manager.displayName()

        text, accepted = QtWidgets.QInputDialog.getText(
            qtutils.sessionWindow(),
            f"Open from {manager_name}",
            "Entity reference:",
            text=resolver.default_entity_reference() or "",
        )
        reference = text.strip()
        if not accepted or not reference:
            return []

        if not resolver.is_entity_reference(reference):
            extra_commands.displayFeedback(f"OpenAssetIO: '{reference}' is not a {manager_name} entity reference", 5.0)
            return []
        return [reference]


def createMode():
    return OpenAssetIOMode()

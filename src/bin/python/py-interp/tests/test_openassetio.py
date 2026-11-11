#
# Copyright Contributors to the OpenRV Project
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Tests for openassetio_rv, the OpenAssetIO support module of the
OpenAssetIO RV package. Entity references are resolved through a small
test manager plugin written to a temporary directory.

Skipped when RV is built without OpenAssetIO (RV_ENABLE_OPENASSETIO=OFF).
"""

import os
import tempfile
import textwrap
import unittest
from unittest import mock

try:
    import openassetio_rv
except ImportError:
    openassetio_rv = None

MANAGER_IDENTIFIER = "io.aswf.openrv.test.manager"

# File URLs must be absolute paths on the current platform.
ROOT_URL = "file:///C:/shows/demo" if os.name == "nt" else "file:///mnt/shows/demo"

# A minimal OpenAssetIO manager: references are "rvtest:///<name>", resolved from the ENTITIES table.
MANAGER_PLUGIN = textwrap.dedent(
    f"""
    from openassetio.errors import BatchElementError
    from openassetio.managerApi import ManagerInterface
    from openassetio.pluginSystem import PythonPluginSystemManagerPlugin
    from openassetio.trait import TraitsData
    from openassetio_mediacreation.traits.content import LocatableContentTrait_v1
    from openassetio_mediacreation.traits.timeDomain import FrameRangedTrait_v1

    PREFIX = "rvtest:///"

    # name: (location, isTemplated, startFrame, endFrame)
    ENTITIES = {{
        "movie": ("{ROOT_URL}/sh010/comp.mov", None, None, None),
        "plate": ("{ROOT_URL}/sh010/plate.%7Bframe:04d%7D.exr", True, 1001, 1100),
        "plate-no-range": ("{ROOT_URL}/sh010/plate.%7Bframe:04d%7D.exr", True, None, None),
        "stereo": ("{ROOT_URL}/sh010/plate.%7Bview%7D.%7Bframe:04d%7D.exr", True, 1001, 1100),
        "stream": ("https://example.com/review/sh010.mp4", None, None, None),
        "no-location": (None, None, None, None),
    }}


    class TestManager(ManagerInterface):
        def identifier(self):
            return "{MANAGER_IDENTIFIER}"

        def displayName(self):
            return "RV Test Manager"

        def hasCapability(self, capability):
            return capability in (
                ManagerInterface.Capability.kEntityReferenceIdentification,
                ManagerInterface.Capability.kManagementPolicyQueries,
                ManagerInterface.Capability.kEntityTraitIntrospection,
                ManagerInterface.Capability.kResolution,
                ManagerInterface.Capability.kDefaultEntityReferences,
            )

        def managementPolicy(self, traitSets, policyAccess, context, hostSession):
            return [TraitsData() for _ in traitSets]

        def isEntityReferenceString(self, someString, hostSession):
            return someString.startswith(PREFIX)

        def entityTraits(self, refs, access, context, hostSession, success, error):
            for index, _ in enumerate(refs):
                success(index, {{LocatableContentTrait_v1.kId}})

        def defaultEntityReference(self, traitSets, access, context, hostSession, success, error):
            for index, _ in enumerate(traitSets):
                success(index, self._createEntityReference(PREFIX + "movie"))

        def resolve(self, refs, traitSet, access, context, hostSession, success, error):
            for index, ref in enumerate(refs):
                entity = ENTITIES.get(ref.toString()[len(PREFIX):])
                if entity is None:
                    error(index, BatchElementError(BatchElementError.ErrorCode.kEntityResolutionError, "Unknown entity"))
                    continue
                location, templated, start, end = entity
                data = TraitsData()
                if location is not None:
                    content = LocatableContentTrait_v1(data)
                    content.setLocation(location)
                    if templated is not None:
                        content.setIsTemplated(templated)
                if start is not None:
                    frames = FrameRangedTrait_v1(data)
                    frames.setStartFrame(start)
                    frames.setEndFrame(end)
                success(index, data)


    class TestManagerPlugin(PythonPluginSystemManagerPlugin):
        @classmethod
        def identifier(cls):
            return "{MANAGER_IDENTIFIER}"

        @classmethod
        def interface(cls):
            return TestManager()


    openassetioPlugin = TestManagerPlugin
    """
)


# The UI delegate of the test manager. Its browser "widget" is a plain object that tests use to simulate a selection.
UI_DELEGATE_PLUGIN = textwrap.dedent(
    f"""
    from openassetio import EntityReference
    from openassetio.trait import TraitsData
    from openassetio.ui.managerApi import UIDelegateInterface, UIDelegateStateInterface
    from openassetio.ui.pluginSystem import PythonPluginSystemUIDelegatePlugin
    from openassetio_mediacreation.traits.ui import BrowserTrait_v1, DetachedTrait_v1, EntityProviderTrait_v1
    from openassetio_mediacreation.traits.uiPolicy import ManagedTrait_v1


    class State(UIDelegateStateInterface):
        def __init__(self, references, widget):
            UIDelegateStateInterface.__init__(self)
            self._references = references
            self._widget = widget

        def entityReferences(self):
            return self._references

        def entityTraitsDatas(self):
            return []

        def nativeData(self):
            return self._widget

        def updateRequestCallback(self):
            return None


    class BrowserWidget:
        def __init__(self, request):
            self.request = request

        def select(self, references):
            refs = [EntityReference(reference) for reference in references]
            self.request.stateChangedCallback()(State(refs, self))


    class TestUIDelegate(UIDelegateInterface):
        def identifier(self):
            return "{MANAGER_IDENTIFIER}"

        def displayName(self):
            return "RV Test UI Delegate"

        def uiPolicy(self, uiTraitSet, uiAccess, context, hostSession):
            policy = TraitsData()
            if BrowserTrait_v1.kId in uiTraitSet:
                ManagedTrait_v1.imbueTo(policy)
            return policy

        def populateUI(self, uiTraitsData, uiAccess, uiRequest, context, hostSession):
            required = (BrowserTrait_v1, DetachedTrait_v1, EntityProviderTrait_v1)
            if not all(trait.isImbuedTo(uiTraitsData) for trait in required):
                return None
            return State([], BrowserWidget(uiRequest))


    class TestUIDelegatePlugin(PythonPluginSystemUIDelegatePlugin):
        @classmethod
        def identifier(cls):
            return "{MANAGER_IDENTIFIER}"

        @classmethod
        def interface(cls):
            return TestUIDelegate()


    openassetioUIPlugin = TestUIDelegatePlugin
    """
)


@unittest.skipIf(openassetio_rv is None, "RV is built without OpenAssetIO")
class TestTemplates(unittest.TestCase):
    def test_frame_variable_becomes_printf(self):
        self.assertEqual(openassetio_rv.template_to_rv_sequence("/s/plate.{frame:04d}.exr"), "/s/plate.%04d.exr")
        self.assertEqual(openassetio_rv.template_to_rv_sequence("/s/plate.{frame:4d}.exr"), "/s/plate.%04d.exr")
        # As returned by the AYON manager plugin.
        self.assertEqual(openassetio_rv.template_to_rv_sequence("/s/plate.{frame:04}.exr"), "/s/plate.%04d.exr")
        self.assertEqual(openassetio_rv.template_to_rv_sequence("/s/plate.{frame:d}.exr"), "/s/plate.%d.exr")
        self.assertEqual(openassetio_rv.template_to_rv_sequence("/s/plate.{frame}.exr"), "/s/plate.%d.exr")

    def test_frame_range_prefixes_the_frame_token(self):
        self.assertEqual(
            openassetio_rv.template_to_rv_sequence("/s/plate.{frame:04d}.exr", 1001, 1100), "/s/plate.1001-1100%04d.exr"
        )

    def test_doubled_braces_are_literal(self):
        self.assertEqual(
            openassetio_rv.template_to_rv_sequence("/s/{{v1}}/plate.{frame:04d}.exr"), "/s/{v1}/plate.%04d.exr"
        )

    def test_other_variables_are_rejected(self):
        with self.assertRaises(openassetio_rv.ResolveError):
            openassetio_rv.template_to_rv_sequence("/s/plate.{view}.{frame:04d}.exr")


@unittest.skipIf(openassetio_rv is None, "RV is built without OpenAssetIO")
class TestLocationToPath(unittest.TestCase):
    def test_file_url_becomes_path(self):
        path = openassetio_rv.location_to_path(f"{ROOT_URL}/plate%20v2.exr")
        self.assertTrue(path.endswith("/shows/demo/plate v2.exr"), path)
        self.assertNotIn("file:", path)
        # RV uses forward slashes on Windows too.
        self.assertNotIn("\\", path)

    def test_other_urls_are_kept(self):
        self.assertEqual(openassetio_rv.location_to_path("https://example.com/a.mp4"), "https://example.com/a.mp4")


@unittest.skipIf(openassetio_rv is None, "RV is built without OpenAssetIO")
class TestResolverWithoutManager(unittest.TestCase):
    def test_inert_without_configuration(self):
        with mock.patch.dict(os.environ, {"OPENASSETIO_DEFAULT_CONFIG": ""}):
            self.assertFalse(openassetio_rv.is_configured())
            resolver = openassetio_rv.Resolver()
            self.assertIsNone(resolver.manager)
            self.assertFalse(resolver.is_entity_reference("rvtest:///movie"))
            with self.assertRaises(openassetio_rv.ResolveError):
                resolver.resolve_path("rvtest:///movie")


class _ManagerTestCase(unittest.TestCase):
    """Configures the test manager (and optionally its UI delegate) as the default OpenAssetIO manager."""

    manager_plugin = MANAGER_PLUGIN
    with_ui_delegate = False

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        environment = {
            "OPENASSETIO_DEFAULT_CONFIG": os.path.join(self._tmp.name, "openassetio_config.toml"),
            "OPENASSETIO_PLUGIN_PATH": self._write_plugin("plugins", self.manager_plugin),
            "OPENASSETIO_UI_PLUGIN_PATH": "",
        }
        if self.with_ui_delegate:
            environment["OPENASSETIO_UI_PLUGIN_PATH"] = self._write_plugin("ui_plugins", UI_DELEGATE_PLUGIN)
        with open(environment["OPENASSETIO_DEFAULT_CONFIG"], "w") as config_file:
            config_file.write(f'[manager]\nidentifier = "{MANAGER_IDENTIFIER}"\n')

        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.resolver = openassetio_rv.Resolver()

    def _write_plugin(self, directory, source):
        plugin_dir = os.path.join(self._tmp.name, directory, "rv_test_plugin")
        os.makedirs(plugin_dir)
        with open(os.path.join(plugin_dir, "__init__.py"), "w") as plugin:
            plugin.write(source)
        return os.path.dirname(plugin_dir)


@unittest.skipIf(openassetio_rv is None, "RV is built without OpenAssetIO")
class TestResolver(_ManagerTestCase):
    def test_loads_configured_manager(self):
        self.assertTrue(openassetio_rv.is_configured())
        self.assertIsNotNone(self.resolver.manager)
        self.assertEqual(self.resolver.manager.identifier(), MANAGER_IDENTIFIER)

    def test_recognizes_entity_references(self):
        self.assertTrue(self.resolver.is_entity_reference("rvtest:///movie"))
        self.assertFalse(self.resolver.is_entity_reference("/mnt/shows/demo/sh010/comp.mov"))

    def test_resolves_movie_to_path(self):
        path = self.resolver.resolve_path("rvtest:///movie")
        self.assertTrue(path.endswith("/shows/demo/sh010/comp.mov"), path)
        self.assertNotIn("file:", path)

    def test_resolves_sequence_with_frame_range(self):
        path = self.resolver.resolve_path("rvtest:///plate")
        self.assertTrue(path.endswith("/sh010/plate.1001-1100%04d.exr"), path)

    def test_resolves_sequence_without_frame_range(self):
        path = self.resolver.resolve_path("rvtest:///plate-no-range")
        self.assertTrue(path.endswith("/sh010/plate.%04d.exr"), path)

    def test_keeps_non_file_urls(self):
        self.assertEqual(self.resolver.resolve_path("rvtest:///stream"), "https://example.com/review/sh010.mp4")

    def test_unknown_entity_raises(self):
        with self.assertRaises(openassetio_rv.ResolveError):
            self.resolver.resolve_path("rvtest:///missing")

    def test_entity_without_location_raises(self):
        with self.assertRaises(openassetio_rv.ResolveError):
            self.resolver.resolve_path("rvtest:///no-location")

    def test_unsupported_template_variable_raises(self):
        with self.assertRaises(openassetio_rv.ResolveError):
            self.resolver.resolve_path("rvtest:///stereo")

    def test_reset_context_keeps_resolving(self):
        first = self.resolver.resolve_path("rvtest:///movie")
        self.resolver.reset_context()
        self.assertEqual(self.resolver.resolve_path("rvtest:///movie"), first)

    def test_default_entity_reference(self):
        self.assertEqual(self.resolver.default_entity_reference(), "rvtest:///movie")

    def test_cannot_browse_without_ui_delegate(self):
        self.assertIsNone(self.resolver.ui_delegate)
        self.assertFalse(self.resolver.can_browse())
        with self.assertRaises(openassetio_rv.ResolveError):
            self.resolver.create_browser()


@unittest.skipIf(openassetio_rv is None, "RV is built without OpenAssetIO")
class TestFailingManager(_ManagerTestCase):
    """A manager plugin raising a non-OpenAssetIO exception (e.g. a missing dependency) must not break RV."""

    manager_plugin = MANAGER_PLUGIN.replace(
        "class TestManager(ManagerInterface):\n",
        "class TestManager(ManagerInterface):\n"
        "    def initialize(self, managerSettings, hostSession):\n"
        "        raise RuntimeError('Cannot reach the asset management system')\n\n",
    )
    assert "raise RuntimeError" in manager_plugin

    def test_manager_is_unavailable(self):
        with self.assertLogs("OpenAssetIO", level="ERROR"):
            self.assertIsNone(self.resolver.manager)
        self.assertFalse(self.resolver.is_entity_reference("rvtest:///movie"))
        with self.assertRaises(openassetio_rv.ResolveError):
            self.resolver.resolve_path("rvtest:///movie")
        self.assertFalse(self.resolver.can_browse())


@unittest.skipIf(openassetio_rv is None, "RV is built without OpenAssetIO")
class TestBrowser(_ManagerTestCase):
    with_ui_delegate = True

    def test_loads_ui_delegate(self):
        self.assertIsNotNone(self.resolver.ui_delegate)
        self.assertEqual(self.resolver.ui_delegate.identifier(), MANAGER_IDENTIFIER)

    def test_can_browse(self):
        self.assertTrue(self.resolver.can_browse())

    def test_browser_provides_the_delegate_widget(self):
        browser = self.resolver.create_browser()
        widget = browser.widget
        self.assertEqual(type(widget).__name__, "BrowserWidget")
        self.assertEqual(browser.entity_references, [])

        # RV asks for entities with a location.
        (entity_traits,) = widget.request.entityTraitsDatas()
        self.assertTrue(entity_traits.hasTrait("openassetio-mediacreation:content.LocatableContent"))

    def test_selection_reaches_rv(self):
        selections = []
        browser = self.resolver.create_browser(selections.append)

        browser.widget.select(["rvtest:///plate", "rvtest:///movie"])

        self.assertEqual(selections, [["rvtest:///plate", "rvtest:///movie"]])
        self.assertEqual(browser.entity_references, ["rvtest:///plate", "rvtest:///movie"])
        # The chosen references resolve like any other.
        self.assertTrue(self.resolver.resolve_path(browser.entity_references[0]).endswith("plate.1001-1100%04d.exr"))


if __name__ == "__main__":
    unittest.main()

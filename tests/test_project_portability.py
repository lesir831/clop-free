"""Platform-independent checks for the standalone Clop Free Xcode project.

These validate source/configuration invariants, not macOS compilation or signing.
Run with: python3 -m unittest discover -s tests -p 'test_project_portability.py'
"""
from pathlib import Path
import json
import plistlib
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "Clop.xcodeproj/project.pbxproj"


def read_openstep(path):
    """Parse the dictionary/array/string subset used by Xcode pbxproj files."""
    source = path.read_text()
    token_re = re.compile(r'\s+|/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|[{}()=;,]|[^\s{}()=;,]+', re.S)
    tokens = [match.group() for match in token_re.finditer(source)
              if not match.group().isspace() and not match.group().startswith(('/*', '//'))]
    index = 0

    def take(expected=None):
        nonlocal index
        if index >= len(tokens):
            raise ValueError("Unexpected end of project")
        token = tokens[index]
        index += 1
        if expected is not None and token != expected:
            raise ValueError(f"Expected {expected!r}, found {token!r}")
        return token

    def value():
        token = take()
        if token == '{':
            result = {}
            while tokens[index] != '}':
                key = value()
                take('=')
                item = value()
                take(';')
                if key in result:
                    raise ValueError(f"Duplicate key {key!r}")
                result[key] = item
            take('}')
            return result
        if token == '(':
            result = []
            while tokens[index] != ')':
                result.append(value())
                if tokens[index] != ')':
                    take(',')
            take(')')
            return result
        if token.startswith('"'):
            # Preserve Swift/Xcode escapes. No test depends on interpreting them.
            return token[1:-1]
        return token

    result = value()
    if index != len(tokens):
        raise ValueError("Unexpected trailing project data")
    return result


class ProjectPortabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = read_openstep(PROJECT)
        cls.objects = cls.project['objects']
        cls.app_info = plistlib.loads((ROOT / 'Clop/Info.plist').read_bytes())

    def test_project_references_resolve(self):
        def check(value):
            if isinstance(value, dict):
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
            elif re.fullmatch(r'[A-Z0-9]{24}', value):
                self.assertIn(value, self.objects, f'Dangling object reference: {value}')
        check(self.project)

    def test_only_public_remote_packages(self):
        packages = [v for v in self.objects.values() if v.get('isa') == 'XCRemoteSwiftPackageReference']
        self.assertGreater(len(packages), 0)
        self.assertFalse(any(v.get('isa') == 'XCLocalSwiftPackageReference' for v in self.objects.values()))
        for package in packages:
            self.assertTrue(package['repositoryURL'].startswith('https://github.com/'))
        lowtech = next(p for p in packages if p['repositoryURL'].endswith('/Lowtech'))
        self.assertEqual(lowtech['requirement'], {
            'kind': 'revision', 'revision': '947d6a1c7073352cec64486b3c6ea0b2a17e62b4',
        })

    def test_no_payment_updater_telemetry_or_transfer_products(self):
        names = {v['productName'] for v in self.objects.values()
                 if v.get('isa') == 'XCSwiftPackageProductDependency'}
        self.assertEqual(names, {'Lowtech', 'Ignore', 'SymbolPicker', 'JxlCoder', 'ArgumentParser'})

    def test_all_target_configurations_use_independent_ids(self):
        ids = [v['buildSettings']['PRODUCT_BUNDLE_IDENTIFIER'] for v in self.objects.values()
               if v.get('isa') == 'XCBuildConfiguration' and 'PRODUCT_BUNDLE_IDENTIFIER' in v['buildSettings']]
        self.assertCountEqual(ids, ['com.clop-free.Clop'] * 2 + ['com.clop-free.Clop.CLI'] * 2)

    def test_no_author_signing_requirement(self):
        for obj in self.objects.values():
            settings = obj.get('buildSettings', {})
            if 'CODE_SIGN_STYLE' in settings:
                self.assertEqual(settings['CODE_SIGN_STYLE'], 'Manual')
                self.assertEqual(settings['CODE_SIGN_IDENTITY'], '-')
            if 'DEVELOPMENT_TEAM' in settings:
                self.assertEqual(settings['DEVELOPMENT_TEAM'], '')
        self.assertNotIn('/Users/', PROJECT.read_text())

    def test_ui_hotkey_handlers_are_main_actor_isolated(self):
        source = (ROOT / 'Clop/ClopApp.swift').read_text()
        for name in ('handleBareHotkey', 'handleCommandHotkey', 'handleHotkey'):
            self.assertRegex(source, rf'@MainActor\s+func {name}\(')

    def test_plists_and_entitlements_are_valid(self):
        for folder in ('Clop', 'ClopCLI'):
            for glob in ('*.plist', '*.entitlements'):
                for path in (ROOT / folder).glob(glob):
                    with self.subTest(path=path):
                        self.assertIsInstance(plistlib.loads(path.read_bytes()), dict)

    def test_application_identity_and_update_isolation(self):
        self.assertEqual(self.app_info['NSPrincipalClass'], 'NSApplication')
        self.assertEqual(self.app_info['CFBundleURLTypes'][0]['CFBundleURLSchemes'], ['clop-free'])
        self.assertEqual(self.app_info['CFBundleURLTypes'][0]['CFBundleURLName'], 'com.clop-free.Clop')
        self.assertNotIn('SUFeedURL', self.app_info)
        self.assertNotIn('SUPublicEDKey', self.app_info)
        self.assertNotIn('OSLogPreferences', self.app_info)
        self.assertFalse(self.app_info['ClopFreeICloudEnabled'])

    def test_adhoc_entitlements_do_not_require_icloud(self):
        for path in ('Clop/Clop.entitlements', 'ClopCLI/ClopCLI.entitlements'):
            entitlements = plistlib.loads((ROOT / path).read_bytes())
            self.assertFalse(any(key.startswith('com.apple.developer.') for key in entitlements))
            self.assertTrue(entitlements['com.apple.security.automation.apple-events'])
            self.assertNotIn('com.lowtechguys.', (ROOT / path).read_text())

    def test_shared_scheme_remains_and_has_no_license_environment(self):
        scheme = ROOT / 'Clop.xcodeproj/xcshareddata/xcschemes/Clop.xcscheme'
        root = ET.parse(scheme).getroot()
        self.assertEqual(root.find('.//BuildableReference').attrib['BuildableName'], 'Clop.app')
        self.assertNotIn('ANTICRACK', scheme.read_text())
        self.assertFalse(any(path.is_file() and 'xcuserdata' in path.parts
                             for path in (ROOT / 'Clop.xcodeproj').rglob('*')))

    def test_resolved_packages_do_not_include_removed_webrtc(self):
        resolved = json.loads((ROOT / 'Clop.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved').read_text())
        self.assertNotIn('webrtc', {pin['identity'] for pin in resolved['pins']})
        lowtech = next(pin for pin in resolved['pins'] if pin['identity'] == 'lowtech')
        self.assertEqual(lowtech['state']['revision'], '947d6a1c7073352cec64486b3c6ea0b2a17e62b4')

    def test_unavailable_link_sharing_has_no_network_backend(self):
        source = (ROOT / 'Clop/WarpDropManager.swift').read_text()
        self.assertIn('let WARP_DROP_AVAILABLE = false', source)
        self.assertIn('optimiser.overlayMessage = WARP_DROP_UNAVAILABLE_MESSAGE', source)
        for forbidden in ('import WarpDrop', 'WarpDropClient(', 'https://drop.lowtechguys.com', 'Task.detached'):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()

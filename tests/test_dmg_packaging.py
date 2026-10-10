"""Portable guards for the native-only release packaging path."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DmgPackagingTests(unittest.TestCase):
    def test_shell_syntax(self):
        subprocess.run(['bash', '-n', str(ROOT / 'Scripts/package-dmg.sh')], check=True)

    def test_release_is_read_only_and_source_pinned(self):
        workflow = (ROOT / '.github/workflows/package-release.yml').read_text()
        self.assertIn('contents: read', workflow)
        self.assertNotIn('contents: write', workflow)
        self.assertNotIn('pull_request:', workflow)
        self.assertNotIn('secrets.', workflow)
        self.assertIn('405a131ec3f35c718622a57c189f61f1b99426fe', workflow)
        self.assertIn('test "$(git -C source rev-parse HEAD)" = "$SOURCE_COMMIT"', workflow)
        self.assertIn('persist-credentials: false', workflow)
        self.assertNotIn('gh release', workflow)

    def test_dmg_is_verified_and_provenance_is_preserved(self):
        script = (ROOT / 'Scripts/package-dmg.sh').read_text()
        for check in ['-format UDZO', 'hdiutil verify', 'hdiutil attach -readonly',
                      'codesign --verify --deep --strict', 'lipo "$target/Contents/MacOS/Clop" -verify_arch arm64 x86_64',
                      'diff -qr', 'cmp "$SOURCE/LICENSE"', 'cmp "$SOURCE/NOTICE.md"',
                      'shasum -a 256 -c SHA256SUMS', 'notarized\': False',
                      'Unresolved Lowtech/swift-ignore redistribution grants']:
            self.assertIn(check, script)
        self.assertNotIn('spctl --master-disable', script)
        self.assertNotIn('xattr -', script)
        self.assertNotIn('git tag', script)


if __name__ == '__main__':
    unittest.main()

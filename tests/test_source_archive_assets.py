import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fetch_source_assets", ROOT / "Scripts/fetch_source_assets.py")
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


class SourceArchiveAssetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "Clop").mkdir()
        self.archive = self.root / "Clop/bin.tar.lrz"
        self.pointer = b"version https://git-lfs.github.com/spec/v1\n"
        self.archive.write_bytes(self.pointer)
        self.payload = b"test optimizer bytes"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        (self.root / "Clop/bin.tar.lrz.sha256").write_text(self.digest)
        self.sha = patch.object(assets, "EXPECTED_SHA256", self.digest)
        self.size = patch.object(assets, "EXPECTED_SIZE", len(self.payload))
        self.sha.start()
        self.size.start()
        self.addCleanup(self.sha.stop)
        self.addCleanup(self.size.stop)

    def test_verified_download_replaces_pointer(self):
        with patch.object(assets.urllib.request, "urlopen", return_value=io.BytesIO(self.payload)) as get:
            assets.fetch(self.root)
        get.assert_called_once_with(assets.ASSET_URL, timeout=120)
        self.assertEqual(self.archive.read_bytes(), self.payload)
        self.assertFalse(list(self.archive.parent.glob("*.tmp")))

    def test_bad_download_preserves_pointer(self):
        for content in [b"short", b"x" * len(self.payload), self.payload + b"oversize"]:
            with self.subTest(content=content):
                with patch.object(assets.urllib.request, "urlopen", return_value=io.BytesIO(content)):
                    with self.assertRaises(ValueError):
                        assets.fetch(self.root)
                self.assertEqual(self.archive.read_bytes(), self.pointer)
                self.assertFalse(list(self.archive.parent.glob("*.tmp")))

    def test_existing_good_resource_needs_no_network(self):
        self.archive.write_bytes(self.payload)
        with patch.object(assets.urllib.request, "urlopen") as get:
            assets.fetch(self.root)
        get.assert_not_called()

    def test_changed_pin_needs_review_before_network(self):
        (self.root / "Clop/bin.tar.lrz.sha256").write_text("0" * 64)
        with patch.object(assets.urllib.request, "urlopen") as get:
            with self.assertRaisesRegex(ValueError, "Review and update"):
                assets.fetch(self.root)
        get.assert_not_called()

    def test_immutable_https_url_and_non_git_fallback(self):
        self.assertIn(assets.UPSTREAM_REVISION, assets.ASSET_URL)
        self.assertTrue(assets.ASSET_URL.startswith("https://media.githubusercontent.com/media/FuzzyIdeas/Clop/"))
        shell = (ROOT / "Scripts/fetch-assets.sh").read_text()
        self.assertLess(shell.index("python3 Scripts/fetch_source_assets.py"), shell.index("command -v git-lfs"))


if __name__ == "__main__":
    unittest.main()

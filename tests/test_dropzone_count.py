"""Source regressions for drop fallback safety, not macOS runtime validation."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DropZoneCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "Clop/DropZone.swift").read_text()
        cls.drop = source.split("func optimiseDroppedItems(", 1)[1].split(
            "\nextension NSSecureCoding", 1
        )[0]

    def test_provider_count_is_snapshotted_before_async_fan_out(self):
        declaration = "let itemProvidersCount = itemProviders.count"
        self.assertEqual(self.drop.count(declaration), 1)
        self.assertLess(self.drop.index(declaration), self.drop.index("tryAsync {"))
        self.assertLess(
            self.drop.index(declaration),
            self.drop.index("for itemProvider in itemProviders {"),
        )
        # Snapshot the drag state before it is cleared at the end of this function.
        self.assertLess(
            self.drop.index("let itemsToOptimise = DM.itemsToOptimise"),
            self.drop.index("tryAsync {"),
        )
        self.assertLess(
            self.drop.rindex("itemProvidersCount == 1"),
            self.drop.index("DM.itemsToOptimise = []"),
        )

    def test_each_media_fallback_requires_one_provider_and_a_real_item(self):
        for media in ("IMAGE", "VIDEO", "AUDIO"):
            with self.subTest(media=media):
                branch = self.drop.split(f"case {media}_FORMATS.map(\\.identifier):", 1)[1]
                branch = re.split(r"\n            (?:case |default:)", branch, maxsplit=1)[0]
                self.assertEqual(branch.count("itemsToOptimise.first"), 1)
                condition = (
                    "itemProvidersCount == 1, let item = itemsToOptimise.first, "
                    "item != .file(FilePath.tmp)"
                )
                self.assertIn(condition, branch)
                if media == "IMAGE":
                    self.assertIn("if path == nil, data == nil, nsImage == nil, " + condition, branch)
                else:
                    failure = "guard let item = try? await itemProvider.loadItem(forTypeIdentifier: identifier) else {"
                    self.assertIn(failure, branch)
                    self.assertLess(branch.index(failure), branch.index(condition))

    def test_provider_count_is_only_used_for_single_item_fallbacks(self):
        # It is structural state, not a limit on how many drops can be processed.
        self.assertEqual(len(re.findall(r"\bitemProvidersCount\b", self.drop)), 4)
        self.assertEqual(self.drop.count("itemProvidersCount == 1"), 3)
        self.assertNotIn("droppedItemCount", self.drop)
        self.assertNotRegex(self.drop, r"(?:itemProviders|droppedFileProviders)\.count\s*(?:>=|>)\s*5\b")


if __name__ == "__main__":
    unittest.main()

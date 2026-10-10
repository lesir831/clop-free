"""Source regression checks; run Scripts/test_feature_policy.py on macOS for behavior."""
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("feature_policy", ROOT / "Scripts/test_feature_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class FeaturePolicyTests(unittest.TestCase):
    def test_production_sources_are_extracted(self):
        source = policy.policy_sources()
        self.assertIn("return try await action()", source)
        self.assertIn("guard !BM.decompressingBinaries", source)
        self.assertIn("guard Defaults[.mcpEnabled]", source)
        self.assertIn("!Defaults[.mcpAllowScriptSteps]", source)
        self.assertIn('pipeline.contains(name)', source)

    def test_no_licensing_or_count_bypass_stubs(self):
        paths = list((ROOT / "Clop").glob("*.swift")) + list((ROOT / "ClopCLI").glob("*.swift"))
        for path in paths:
            text = path.read_text()
            for forbidden in ["proactive", "proGuard", "validReq(", "invalidReq(", "LowtechPro", "import Paddle", "OptimisationCounter", "Get Clop Pro"]:
                self.assertNotIn(forbidden, text, f"{path}: {forbidden}")

    def test_mcp_still_asks_the_user(self):
        text = (ROOT / "Clop/MCPInstaller.swift").read_text()
        self.assertIn("if askToEnable()", text)
        self.assertIn('alert.addButton(withTitle: "Not now")', text)
        self.assertIn('"requiresPro": false', text)
        pane = (ROOT / "Clop/MCPSettingsPane.swift").read_text()
        self.assertIn("if !askAboutScripts()", pane)

    def test_installer_quotes_cli_path(self):
        text = (ROOT / "Clop/MCPInstaller.swift").read_text()
        self.assertIn("mcpShellQuotedArgument(cliPath)", text)
        self.assertIn("func mcpShellQuotedArgument", policy.policy_sources())
        self.assertIn("/Users/O'Neil/Clop Free.app", policy.harness())

    def test_icloud_opt_in_requires_distributor_capability(self):
        app = (ROOT / "Clop/ClopApp.swift").read_text()
        guard = app.index('guard Bundle.main.object(forInfoDictionaryKey: "ClopFreeICloudEnabled")')
        self.assertLess(guard, app.index("Zephyr.observe(keys: SETTINGS_TO_SYNC)"))

    def test_batch_features_have_no_paid_condition(self):
        for name in ["Clop/BatchOptimiser.swift", "Clop/DropZone.swift"]:
            text = (ROOT / name).read_text()
            self.assertIn("batchModeFileCountThreshold", text)
            self.assertNotIn("proactive", text)

    def test_fork_ipc_and_cli_do_not_target_official_app(self):
        for name in ["Shared.swift", "ClopCLI/main.swift", "Clop/MCPInstaller.swift"]:
            text = (ROOT / name).read_text()
            self.assertNotIn("com.lowtechguys.Clop", text)
            self.assertIn("com.clop-free.Clop", text)
        install = (ROOT / "Clop/InstallCLI.swift").read_text()
        self.assertIn('let CLOP_CLI_BIN_LINK = "\\(CLI_BIN_DIR)/clop-free"', install)


if __name__ == "__main__":
    unittest.main()

# Fork changes

## 2026-10-10 — independent free build

Base: upstream main `af3cdb95faf330f16508ab6cd0b334053478a827`.

- Removed paid-feature conditions in application and CLI, including batch routing and MCP, along with optimisation counters, activation callbacks, trial UI and licence purchase prompts
- Kept binary-readiness errors, ordinary operation failures, MCP opt-in and separate arbitrary-script consent
- Removed the LowtechPro, LowtechProSentry and LowtechIndie linked products and the upstream payment, crash-reporting and automatic-update configuration
- Preserved the public base Lowtech utilities at their existing exact revision
- Separated app/CLI bundle IDs, preferences, Mach ports, URL scheme, MCP configuration and CLI symlink from the official application
- Replaced missing local sharing SDK with an explicit unavailable capability and pipeline error; ordinary file sharing integrations remain
- Disabled iCloud synchronization unless the distributor configures its own capability
- Added independent build, ad-hoc/Developer ID signing and optional notarization tooling
- Added verified Git LFS asset preparation and pinned asset recovery for standalone source ZIPs, source regression tests, isolated Swift policy tests and macOS build CI
- Added upstream merge synchronization that opens draft pull requests only after validation and stops on conflicts

Native macOS compilation, notarization and runtime behavior must be checked on macOS; Linux source checks are not equivalent to those validations.

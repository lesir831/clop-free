# clop-free

An independent fork of [Clop](https://github.com/FuzzyIdeas/Clop), the macOS image, video, audio, PDF and clipboard optimiser. Distributed under the [GNU GPL v3](LICENSE).

The public optimisation implementations are available without purchase, activation, a trial period or a five-file session limit. This project is not affiliated with or endorsed by the upstream authors.

## Features

- Clipboard and watched-folder optimisation
- Image/video resizing, conversion and compression
- PDF and audio processing
- Batch optimisation and processing pipelines
- macOS Shortcuts, Finder integration and command-line tools
- MCP automation, with the user's opt-in and separate permission for agent-authored inline scripts

## Build

Requires macOS, Xcode 26.3 or newer, Python 3 and Git LFS. No upstream signing identity or private `required.swift` file is needed.

```sh
git clone https://github.com/lesir831/clop-free.git
cd clop-free
make assets
make build
```

The default build uses **ad-hoc signing**. That is a local integrity signature, not an Apple Developer ID signature or notarization. macOS Gatekeeper may block a downloaded ad-hoc build. The project does not disable Gatekeeper or alter system security settings.

If you have a source ZIP, extract it and run `make assets`, `make check`, and `make build` in its `clop-free` folder. Asset recovery works without Git history; upstream synchronization requires a full clone.

See [build and signing instructions](docs/BUILDING.md) for requirements, output paths, validation, your own Developer ID certificate, optional notarization and upstream synchronization.

The distributable is named **Clop Free.app**. Its bundle IDs, preferences, IPC names, URL scheme and MCP registration are separate from the upstream app. The optional command-line installer uses `~/.local/bin/clop-free`.

## What changed

- Removed application and CLI paid-feature checks, per-session counters and trial/purchase UI
- Removed linked payment, licence-management and crash-reporting products, plus official update feeds and support-account parameters
- Retained user permissions for MCP, scripts, automation and file access
- Replaced author-specific build paths, signing identities and external release tooling
- Added explicit asset verification, regression checks and macOS CI
- Added merge-based upstream synchronization through reviewable pull requests; conflicts and failed checks stop automation

Updates are installed manually from this fork's releases. This fork does not use the original application's update service.

MCP keeps upstream's permission model. It is not a sandbox: saved user-authored pipelines and Shortcuts can execute code, and the inline-script check does not recursively inspect saved pipeline names. Review those automations before allowing an agent to run them.

## Known limitations

- **Secure link sharing is unavailable.** The public upstream project refers to a local WarpDrop SDK that is not supplied in its repository. This fork removes that unresolved build dependency and shows an explicit unavailable message. It does not invent links or contact the upstream sharing backend. AirDrop and the other supported sharing-app integrations remain separate
- **iCloud settings sync is disabled by default.** Enabling it requires a distributor's own Apple capabilities and matching entitlements. Ad-hoc builds do not provide those
- Optimiser tools are supplied by upstream in a Git LFS archive. `make assets` retrieves and verifies the pinned bytes. The tools are not independently rebuilt from source here
- The public Lowtech utility package remains a pinned dependency. Its manifest can resolve unused payment-related packages even though this app does not link the payment or telemetry products. This repository does not vendor or relicense that package
- Source checks do not prove that the complete macOS application builds or works. A successful macOS CI build and runtime smoke test are required before treating a binary as verified
- The dedicated v3.5.0 DMG workflow packages the exact existing tag and uploads release candidates with checksums and source provenance. Ordinary PR/build jobs remain build-only. Lowtech, swift-ignore and bundled-tool redistribution rights and corresponding-source obligations remain unresolved; a successful build does not settle them. See [release packaging](docs/BUILDING.md#versioned-dmg-packaging)

## Upstream and licensing

Based on FuzzyIdeas/Clop, with original authorship and copyright notices preserved. Initial base: `af3cdb95faf330f16508ab6cd0b334053478a827` (main after v3.5.0).

Changes in this fork are documented in [FORK_CHANGELOG.md](FORK_CHANGELOG.md). The original release history remains in [CHANGELOG.md](CHANGELOG.md). See [NOTICE.md](NOTICE.md) for provenance and distribution considerations.

Contributors and distributors are responsible for satisfying the licences of the app and all dependencies, including corresponding-source obligations for any binaries they distribute.

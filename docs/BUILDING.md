# Building, signing and updating clop-free

This fork is built from the public [Clop source](https://github.com/FuzzyIdeas/Clop).
The GPL license and upstream notices are preserved. No upstream developer account,
private configuration file, signing certificate or release server is required.

## Requirements

- A Mac with **full Xcode 26 or newer**, including the macOS 26 SDK. Command Line
  Tools alone and Xcode 16 cannot compile the newer UI APIs, even though those APIs
  have runtime availability checks. CI explicitly selects Xcode 26.3 on `macos-15`
- Python 3.9 or newer and the command-line tools supplied by Xcode; Git and Git LFS for repository checkouts and synchronization
- Network access to GitHub and the binary artifact locations used by the pinned
  Swift packages, plus sufficient space for Xcode DerivedData and expanded media tools

The app and CLI targets declare macOS 13 deployment targets. This is not a claim
that every dependency or feature has been runtime-tested on macOS 13. Test the
macOS versions and CPU architectures you intend to support before distributing.

Select a particular installed Xcode without changing system settings:

```sh
export DEVELOPER_DIR=/Applications/Xcode_26.3.app/Contents/Developer
xcodebuild -version
```

## Local build

From a checkout of this repository:

```sh
make assets
make check
make build
```

The output is `build/Clop Free.app`. The Xcode scheme and internal build product
remain `Clop` and `Clop.app` to limit unnecessary upstream merge conflicts. The
staged distributable has a separate name and the bundle ID `com.clop-free.Clop`;
the embedded CLI uses `com.clop-free.Clop.CLI`. The CLI installer creates
`~/.local/bin/clop-free`.

`make build` builds both `arm64` and `x86_64`, disables Xcode account-based signing,
then explicitly ad-hoc signs the completed bundle. It does not install or launch
the app, register an account, upload a build, or change Gatekeeper. To test locally,
open the output app yourself and grant only the permissions you need. A downloaded
ad-hoc app may be blocked by Gatekeeper; ad-hoc signing is not notarization.

The build command applies the application's macOS 13.0 deployment target to all
targets, including Swift packages. This prevents a transitive package's older
default deployment target from conflicting with a dependency's minimum version.
It also opts out of Swift explicit module builds using
`SWIFT_ENABLE_EXPLICIT_MODULES=NO`: the pinned IgnoreRust XCFramework contains
duplicate module maps that conflict in Xcode 26's eager dependency scanner.
The compatibility setting leaves the pinned dependency files unchanged.

Optional environment variables:

```sh
# A faster development build for the current architecture
CONFIGURATION=Debug ARCHS="$(uname -m)" make build

# A different generated-output directory
BUILD_DIR="$PWD/build/custom" make build

# ZIP for local sharing/testing, with a SHA-256 sidecar
make package
```

`CONFIGURATION` accepts `Debug` or `Release`. `ARCHS` defaults to `arm64 x86_64`.
`make package` produces `build/clop-free.zip` and `build/clop-free.zip.sha256`.
Generated output is replaced on a subsequent successful build; source resources
are never re-signed or repacked in place.

### Optimizer assets

`Clop/bin.tar.lrz` is a Git LFS resource. A normal source archive or a checkout with
LFS smudging disabled contains only a small pointer, not the media tools. For a Git checkout, `make
assets` retrieves the object from the public upstream LFS endpoint and checks its
SHA-256 against the committed `Clop/bin.tar.lrz.sha256`. The current pinned archive
is 65,922,782 bytes. This verifies the expected upstream bytes, not an independent
source rebuild or security audit of every tool.

For an extracted source ZIP, `make assets` instead downloads from an immutable upstream revision on GitHub, verifies both the pinned byte count and SHA-256, and atomically replaces the pointer only after success. It does not need Git or Git LFS in that mode. A checksum change requires manual review of the source-ZIP download pin as well.

The checkout fetch script uses command-scoped Git LFS filters, so it also works without
running `git lfs install`; it does not change global Git configuration or hooks.
To use an existing named remote's LFS store instead:

```sh
LFS_REMOTE=origin make assets
```

A missing pointer payload, invalid hash, or failed download stops the build.
Do not replace the checksum merely to silence an integrity failure. Review
upstream asset changes together with their provenance and licenses.

### Swift package resolution

Builds use the committed `Package.resolved` and refuse automatic dependency
updates. The public Lowtech utility package is still used at the pinned revision.
Its manifest declares additional packages, including unused payment-related
dependencies; removing app product links does not prevent SwiftPM from resolving
every manifest dependency.

If Xcode reports an out-of-date lockfile, explicitly resolve and review the diff:

```sh
make resolve
git diff -- Clop.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved
make check
make build
```

Do not claim a working macOS build based only on portable source checks.

## Signing with your own Developer ID

Ad-hoc signing is the default and requires no Apple Developer membership. For a
Developer ID build, provide an **already installed** Developer ID Application
identity in your local Keychain:

```sh
SIGN_IDENTITY='Developer ID Application: Your Name (YOURTEAMID)' make package
```

The tooling does not create, import, export or upload certificates or private
keys. It does not use automatic provisioning or inherit an upstream team ID.
Signing identities other than ad-hoc or Developer ID Application fail validation.
Developer ID signing alone does not guarantee Gatekeeper acceptance.

The signing script:

1. Verifies the copied optimizer archive, then expands it into disposable staging
2. Rejects archive traversal, unsafe links, duplicate paths and special devices
3. Signs Mach-O helpers and nested code inside-out, applying process entitlements
   only to executables, never dylibs
4. Repackages the signed helpers as gzip-compressed tar at the legacy resource
   filename `bin.tar.lrz`, updating the copied hash file. macOS `tar` detects the
   compression from the file contents; the application does not depend on its suffix
5. Signs embedded code and finally the app, then strictly verifies the whole bundle

No recursive `codesign --deep` signing is used. `--deep` is used only for final
signature verification. Hardened-runtime signing and secure timestamps are used
for Developer ID builds. Ad-hoc builds omit secure timestamps and do not enable
hardened runtime: their teamless signatures cannot satisfy its same-Team-ID
library checks. This changes only the generated app's signature, never system
security settings or the Developer ID signing policy.

### Optional notarization

Notarization sends your signed application and its expanded signed optimizer
helpers to Apple's notary service. It is opt-in and may take several minutes.
Use an **existing** `notarytool` Keychain profile that you have configured locally:

```sh
SIGN_IDENTITY='Developer ID Application: Your Name (YOURTEAMID)' \
NOTARY_PROFILE='your-existing-profile' make package
```

The script submits a temporary ZIP containing the app and the expanded helpers so
the service can inspect code otherwise stored inside the compressed resource. It
requires a JSON status of `Accepted`, then staples and validates the app's ticket,
and performs a Gatekeeper assessment. Rejected or inconclusive submissions stop
the build; they are never described as successfully notarized. The final ZIP is
created after stapling. Submission IDs are printed for diagnosing a rejection.

For Apple's current requirements, see [notarizing macOS software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
and [creating distribution-signed code](https://developer.apple.com/documentation/xcode/creating-distribution-signed-code-for-the-mac).
Credentials are not stored in this repository or in the supplied workflows.

## Checks and CI

```sh
make check
bash -n Scripts/build.sh Scripts/fetch-assets.sh Scripts/sync-upstream.sh
python3 Scripts/test_feature_policy.py --check-only

# On a Mac: compile and run extracted, actual application policy functions
python3 Scripts/test_feature_policy.py
```

Portable tests cover archive validation, signing command construction, executable
versus library entitlements, asset integrity, rejection handling, project
structure, known feature-policy regressions, and isolated Git merge scenarios.
The macOS policy harness tests more than five operations and preserves tool
readiness, error propagation, MCP opt-in and script consent.

The build workflow runs portable checks, the policy harness, asset verification,
and a universal ad-hoc build. Successful runs retain the app ZIP, hash, GPL license
and matching application source snapshot as short-lived artifacts. They do not
publish a release or use Developer ID/notarization credentials. Source snapshots
alone do not satisfy every dependency's corresponding-source obligations; see
[NOTICE.md](../NOTICE.md) before distributing binaries.

A maintainer must still smoke-test launch, optimization, batch/Shortcuts/CLI/MCP
behavior, permissions, and helper extraction on real Macs. Native build, signing,
notarization and runtime behavior cannot be verified by a Linux-only source check.

## Upstream synchronization

The fork keeps upstream history and adds its own changes as ordinary commits.
Synchronization makes a merge candidate; it never resets the fork to upstream,
rebases away fork changes, applies blanket "ours/theirs" conflict resolution, or
auto-merges a pull request.

### Local review

A source ZIP has no Git history and cannot synchronize upstream by itself. Start from a full clone when using synchronization.

Start from a clean, full-history checkout with fork changes already committed:

```sh
make sync-upstream

# Or use an already fetched reference without network access
UPSTREAM_REF=upstream/main make sync-upstream
```

By default, the script fetches `FuzzyIdeas/Clop`'s `main` through a temporary,
command-scoped remote definition. It prepares a merge in an isolated worktree,
validates with a copy of the fork's original checker, and creates a local branch
named `sync/upstream-<upstream-sha>-<base-sha>`. It also writes a candidate Git bundle
and JSON manifest to `build/upstream-sync/`. The current branch and checkout are
unchanged; the script never pushes.

It fails without creating a candidate when:

- The checkout is dirty, shallow, or has no common history with upstream
- Git reports a merge conflict
- The merge changes protected build, workflow, test or validation controls
- Known paid gates, upstream identities, provisioning-only entitlements, updater
  configuration or telemetry/payment configuration reappear
- The preserved GPL license changes or required source files disappear

Conflict paths are recorded in `build/upstream-sync/conflicts.txt`. Changes needing
manual control review are recorded in `manual-review.txt`. Resolve those cases on
a separate review branch, preserve both upstream fixes and fork behavior, and rerun
all checks and the macOS build. Static checks recognize known restrictions; they
cannot prove that new upstream logic introduces no new restriction or service.

### Draft pull requests from GitHub Actions

After the repository is published and Actions is enabled, run **Review upstream
changes** manually from its default branch. To opt in to its weekly Monday 08:00
UTC schedule, set the repository Actions variable `ENABLE_UPSTREAM_SYNC` to `true`.
No personal token or certificate secret is required. The repository must allow
its `GITHUB_TOKEN` to create pull requests.

The workflow separates trust and permissions:

1. A read-only job prepares and validates the merge with the trusted baseline
2. Another read-only job runs the candidate's tests and macOS build without secrets
3. Only after success, a separate job with narrowly scoped write permissions pushes
   the exact verified commit and opens a **draft** PR. It executes no candidate code

The publisher checks both merge parents and that the default branch has not moved.
It never force-pushes and never changes the default branch. Conflicts, failed
validation/builds, a moved base, or denied repository permissions stop the workflow.
Review the workflow logs and any blocker artifact, then fix the cause and rerun.

Events created with `GITHUB_TOKEN` do not generally trigger another Actions
workflow, so sync performs its own complete checks before opening the PR. If
branch protection requires the ordinary build workflow's check names, run **Build
clop-free** manually on the candidate branch or push a maintainer-reviewed update.
Never bypass branch protection to compensate for a missing check.

## Deliberate limitations

The unavailable author-local secure-sharing SDK is not included; that action
reports its unavailability. iCloud settings sync is disabled because its capability
requires a distributor's own provisioning and entitlements. Ordinary permissions
for files, automation, MCP and scripts are retained. See the repository README for
the complete fork scope and verification status.

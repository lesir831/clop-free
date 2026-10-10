# Notices and provenance

## Clop

This is a modified version of [FuzzyIdeas/Clop](https://github.com/FuzzyIdeas/Clop).

Original source identifies Alin Panaitiu and The low-tech guys as its authors. Original source headers, assets, release history and the GNU General Public License v3 text in `LICENSE` are retained. The independent fork is named **clop-free**, with the application display name **Clop Free**; the names do not imply endorsement by the original authors.

Initial upstream revision: `af3cdb95faf330f16508ab6cd0b334053478a827`.

Fork modifications dated 2026-10-10 remove commercial feature gating and author-specific release infrastructure, separate application identity, and add portable build, signing, checks and synchronization tools. See `FORK_CHANGELOG.md` for details.

## Dependencies and bundled tools

Swift dependency locations and exact resolutions are recorded in the Xcode project and `Package.resolved`. The retained Lowtech utility dependency is public but its repository does not currently contain a root licence file; it is not copied into this repository or relicensed by this fork. Verify the necessary rights before redistributing its code or linked binaries. Public availability alone is not a redistribution licence.

The pinned `alin23/swift-ignore` revision `4fc142964621eda7835a4524e567388f5ef6f1a0` likewise has no repository licence file and bundles an `IgnoreRust` static library without its Rust source or build manifest. The build-time module-map repair does not establish redistribution rights or provide that missing source. Binary distribution remains withheld pending review of both Lowtech and swift-ignore.

The inherited `lrzip` executable is also tracked directly in this repository, so an ordinary Git source archive includes executable code. Its exact corresponding-source/build provenance and required notices need review before redistribution; CI therefore withholds all artifact uploads rather than describing its archives as binary-free.

JxlCoder 1.9.1's wrapper licence does not by itself cover every bundled binary framework. Its Brotli, Highway, libjxl and other compiled components require their own notices and source/provenance review before an app release.

The upstream Git LFS archive contains separately authored optimisation tools, including ffmpeg, Ghostscript, pngquant, jpegoptim, gifsicle, libvips, gifski and supporting components. Those tools have their own licences. Their archive is inherited, not independently rebuilt or comprehensively audited by this fork. Distributors must verify included notices, licence compatibility and corresponding-source availability for the exact binaries they publish.

No rights in third-party trademarks are granted by this notice. The original project's GPL notice does not replace the individual obligations of dependencies.

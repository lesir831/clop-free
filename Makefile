SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help assets verify-assets check test resolve build package sync-upstream

help:
	@printf '%s\n' \
	  'make assets          Fetch and verify the pinned optimizer archive (Git LFS)' \
	  'make check           Validate fork invariants and run portable tests' \
	  'make resolve         Resolve Swift packages explicitly (review lockfile changes)' \
	  'make build           Build and ad-hoc sign build/Clop Free.app on macOS' \
	  'make package         Build and create build/clop-free.zip' \
	  'make sync-upstream   Prepare a validated local upstream-merge branch, no push' \
	  'See docs/BUILDING.md for Developer ID signing and optional notarization'

assets:
	bash Scripts/fetch-assets.sh

verify-assets:
	python3 Scripts/verify_assets.py

test:
	python3 -m unittest discover -s tests -v

check:
	python3 Scripts/validate_fork.py
	$(MAKE) test

resolve:
	xcodebuild -resolvePackageDependencies -project Clop.xcodeproj -scheme Clop

build:
	bash Scripts/build.sh

package:
	PACKAGE=1 bash Scripts/build.sh

sync-upstream:
	bash Scripts/sync-upstream.sh

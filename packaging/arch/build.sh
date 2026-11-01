#!/usr/bin/env bash

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$HERE"
make dist >/dev/null
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
cp packaging/arch/PKGBUILD packaging/arch/glitterde.install "$W/"; cp "dist/glitterde-$(cat VERSION).tar.gz" "$W/"
( cd "$W" && makepkg -f --nodeps >/dev/null 2>&1 || makepkg -f )
mkdir -p dist; cp "$W"/*.pkg.tar.* dist/; ls dist/*.pkg.tar.*

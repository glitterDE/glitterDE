#!/usr/bin/env bash

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$HERE"
VERSION="$(cat VERSION)"; make dist >/dev/null
TOP="$(mktemp -d)"; trap 'rm -rf "$TOP"' EXIT
mkdir -p "$TOP"/{SOURCES,SPECS,BUILD,RPMS,SRPMS}
cp "dist/glitterde-$VERSION.tar.gz" "$TOP/SOURCES/"; cp packaging/rpm/glitterde.spec "$TOP/SPECS/"
NODEPS=""; command -v dnf >/dev/null || command -v zypper >/dev/null || NODEPS="--nodeps"
rpmbuild -bb $NODEPS --define "_topdir $TOP" --define "pkgversion $VERSION" "$TOP/SPECS/glitterde.spec" >/dev/null
mkdir -p dist; cp "$TOP"/RPMS/*/*.rpm dist/; ls dist/*.rpm

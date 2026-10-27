#!/usr/bin/env bash

cd "$(dirname "${BASH_SOURCE[0]}")/.."
command -v dpkg-deb >/dev/null && packaging/deb/build.sh || echo "skipped .deb: dpkg-deb not found"
command -v rpmbuild >/dev/null && packaging/rpm/build.sh || echo "skipped .rpm: rpmbuild not found"
command -v makepkg  >/dev/null && packaging/arch/build.sh || echo "skipped Arch package: makepkg not found"

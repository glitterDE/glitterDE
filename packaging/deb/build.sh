#!/usr/bin/env bash

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$HERE"
VERSION="$(cat VERSION)"
ARCH="$(dpkg --print-architecture)"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
make >/dev/null && make install DESTDIR="$STAGE" PREFIX=/usr >/dev/null
install -d "$STAGE/DEBIAN" "$STAGE/usr/share/doc/glitterde"
cat > "$STAGE/usr/share/doc/glitterde/copyright" <<C
Upstream-Name: glitterDE
Files: *
License: GPL-3
C
cat > "$STAGE/DEBIAN/control" <<C
Package: glitterde
Version: $VERSION-1
Architecture: $ARCH
Maintainer: rubythecutie <228643222+rubythecutie@users.noreply.github.com>
Installed-Size: $(du -sk "$STAGE/usr" | cut -f1)
Section: x11
Priority: optional
Depends: python3 (>= 3.9), python3-gi, python3-gi-cairo, python3-cairo, python3-xlib, python3-pil, gir1.2-gtk-3.0, gir1.2-pango-1.0, gir1.2-gdkpixbuf-2.0, gir1.2-wnck-3.0, gir1.2-vte-2.91, libx11-6, libx11-xcb1, libxcb1, libxcb-present0, libxcomposite1, libxdamage1, libxfixes3, libxext6, libcairo2, librsvg2-common, dbus-user-session | dbus-x11, xdg-utils, libglib2.0-bin
Recommends: udisks2, network-manager, bluez, wireplumber, brightnessctl, power-profiles-daemon, fonts-inter, fonts-jetbrains-mono, libnotify-bin, xdg-user-dirs, gvfs
Suggests: policykit-1-gnome | lxpolkit | mate-polkit, udisks2, pipewire-pulse | pulseaudio, gammastep
Homepage: https://glitterde.github.io
Description: A customisable but pretty desktop environment :3
C
cat > "$STAGE/DEBIAN/postinst" <<'C'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -f /usr/share/icons/hicolor 2>/dev/null || true
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications 2>/dev/null || true
    python3 -m compileall -q /usr/lib/glitterde/glitterde 2>/dev/null || true
    for f in /home/*/.local/bin/glitterde-* /home/*/.local/bin/glitter-* /home/*/.local/bin/spark*; do
        [ -e "$f" ] && echo "glitterde: WARNING: $f is a stale copy from an older install; delete it (it can shadow /usr/bin)." >&2
    done
fi
exit 0
C
cat > "$STAGE/DEBIAN/postrm" <<'C'
#!/bin/sh
set -e
case "$1" in remove|purge) rm -rf /usr/lib/glitterde ;; esac
exit 0
C
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"
mkdir -p dist; OUT="dist/glitterde_${VERSION}-1_${ARCH}.deb"
dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$OUT" >/dev/null
echo "built $OUT"

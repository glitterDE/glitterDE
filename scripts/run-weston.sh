#!/usr/bin/env bash
# Run glitterDE inside a nested Weston compositor (Wayland session) with an isolated D-Bus session.
# usage: scripts/run-weston.sh [WIDTHxHEIGHT] [extra glitterde-shell args...]
# Works from an X11 session (weston x11 backend) or a Wayland session (wayland backend).
# Note: window-list/workspace integration (libwnck) is X11-only; under Wayland the dock shows pinned apps only.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIZE="${1:-1536x1024}"; [[ $# -gt 0 ]] && shift
command -v weston >/dev/null || { echo "weston not found (Debian/Ubuntu: sudo apt install weston)"; exit 1; }
W="${SIZE%x*}"; H="${SIZE#*x}"
export PATH="$HERE/bin:$PATH"
export XDG_DATA_DIRS="$HERE/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
SOCK="glitterde-$$"
CFG="$(mktemp --suffix=.ini)"
cat > "$CFG" <<INI
[core]
shell=desktop

[shell]
panel-position=none
background-color=0xff17131c
INI
EXTRA=(); [[ -n "${WESTON_RENDERER:-}" ]] && EXTRA+=(--renderer="$WESTON_RENDERER")
weston --config="$CFG" --socket="$SOCK" --width="$W" --height="$H" "${EXTRA[@]}" &
WPID=$!
trap 'kill $WPID 2>/dev/null || true; rm -f "$CFG"' EXIT
RT="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
for _ in $(seq 80); do [[ -S "$RT/$SOCK" ]] && break; sleep 0.1; done
[[ -S "$RT/$SOCK" ]] || { echo "Weston did not come up (see messages above)"; exit 1; }

export WAYLAND_DISPLAY="$SOCK" GDK_BACKEND=wayland GSK_RENDERER=cairo GLITTERDE_NESTED=1 NO_AT_BRIDGE=1 GIO_USE_VFS=local
unset DISPLAY
echo "glitterDE running in Weston ($SOCK)  (Ctrl+Q to exit)"
if [[ -n "${GLITTERDE_ISOLATED_BUS:-}" ]] && command -v dbus-run-session >/dev/null; then
  # The isolated bus has no xdg-desktop-portal / settings daemons: tell toolkits not to wait for them (25 s timeouts).
  export GTK_USE_PORTAL=0 QT_NO_XDG_DESKTOP_PORTAL=1 GDK_DEBUG=${GDK_DEBUG:-} MOZ_ENABLE_WAYLAND=${MOZ_ENABLE_WAYLAND:-0}
  echo "note: using an isolated D-Bus session (media players and portals on your real bus are not visible)"
  dbus-run-session -- "$HERE/bin/glitterde-shell" "$@"
else
  "$HERE/bin/glitterde-shell" "$@"
fi

#!/usr/bin/env bash
# Run glitterDE inside a nested X11 server (Xephyr) with a window manager + isolated D-Bus session.
# usage: scripts/run-xephyr.sh [WIDTHxHEIGHT] [extra glitterde-shell args...]   e.g.  run-xephyr.sh 1920x1080
# env:   GLITTERDE_XEPHYR_ARGS=-glamor   extra Xephyr flags (hardware acceleration makes a big difference)
#        GLITTERDE_NO_COMP=1     run without the compositor (cheaper, no blur/shadows)
#        GLITTERDE_WM=openbox    use another window manager instead of glitter-wm
#        GLITTERDE_ISOLATED_BUS=1  private D-Bus session instead of yours (default: your real one, so media players and portals work)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIZE="${1:-1536x1024}"; [[ $# -gt 0 ]] && shift
command -v Xephyr >/dev/null || { echo "Xephyr not found (Debian/Ubuntu: sudo apt install xserver-xephyr)"; exit 1; }

export PATH="$HERE/bin:$PATH"
export XDG_DATA_DIRS="$HERE/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"   # Spark* .desktop files + icons
WM="${GLITTERDE_WM:-}"
if [[ -z "$WM" ]]; then
  if python3 -c "import Xlib" 2>/dev/null; then WM="$HERE/bin/glitter-wm"
  else
    echo "note: python3-xlib missing, falling back to another WM (sudo apt install python3-xlib for glitter-wm)"
    for c in openbox xfwm4 icewm marco metacity fluxbox fvwm; do command -v "$c" >/dev/null && { WM="$c"; break; }; done
  fi
fi
[[ -n "$WM" ]] || echo "warning: no window manager found - apps will open without title bars"

N=2; while [[ -e "/tmp/.X11-unix/X$N" || -e "/tmp/.X$N-lock" ]]; do N=$((N+1)); done
Xephyr ":$N" +extension Composite -screen "$SIZE" -ac ${GLITTERDE_XEPHYR_ARGS:-} -br -title "glitterDE (Xephyr)" &
XPID=$!
trap 'kill $XPID 2>/dev/null || true' EXIT
for _ in $(seq 50); do [[ -e "/tmp/.X11-unix/X$N" ]] && break; sleep 0.1; done

export DISPLAY=":$N" GDK_BACKEND=x11 GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1 GLITTERDE_NESTED=1 NO_AT_BRIDGE=1 GIO_USE_VFS=local
# compositor (real glass: shadows, alpha, blur-behind). Built on first run; optional.
COMP=""
if [[ -z "${GLITTERDE_NO_COMP:-}" ]]; then
  [[ -x "$HERE/bin/glitter-comp" ]] || make -C "$HERE/comp" >/dev/null 2>&1 || \
    echo "note: could not build glitter-comp (sudo apt install build-essential pkg-config libx11-dev libxcomposite-dev libxdamage-dev libxfixes-dev libxext-dev libcairo2-dev) - continuing without compositing"
  [[ -x "$HERE/bin/glitter-comp" ]] && COMP="$HERE/bin/glitter-comp"
fi
export COMP
INNER='[[ -n "${COMP:-}" ]] && { "$COMP" >/dev/null 2>&1 & sleep 0.5; }
       [[ -n "${WM:-}" ]] && { "$WM" >/dev/null 2>&1 & sleep 0.6; }
       exec "$HERE/bin/glitterde-shell" --size "$SIZE" --as-desktop "$@"'
echo "glitterDE running in Xephyr on $DISPLAY with WM='${WM:-none}'  (Ctrl+Q or Quit in the power menu to exit)"
export WM HERE SIZE
if [[ -n "${GLITTERDE_ISOLATED_BUS:-}" ]] && command -v dbus-run-session >/dev/null; then
  # The isolated bus has no xdg-desktop-portal / settings daemons: tell toolkits not to wait for them (25 s timeouts).
  export GTK_USE_PORTAL=0 QT_NO_XDG_DESKTOP_PORTAL=1 GDK_DEBUG=${GDK_DEBUG:-} MOZ_ENABLE_WAYLAND=${MOZ_ENABLE_WAYLAND:-0}
  echo "note: using an isolated D-Bus session (media players and portals on your real bus are not visible)"
  dbus-run-session -- bash -c "$INNER" _ "$@"
else
  bash -c "$INNER" _ "$@"
fi

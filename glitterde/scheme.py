"""Light/dark colour scheme for windows, menus and the launcher.

setting  appearance.color_scheme = auto | light | dark
auto     follows the active theme's  [appearance] app_scheme  (default "light")
The shell chrome (panel, cards, dock) is always glass; this switches the app surfaces and their ink colour.
"""
from . import config

NAVY = (0.165, 0.176, 0.43, 1)
SNOW = (0.93, 0.92, 0.98, 1)

_cache = None


def mode():
    """'light' or 'dark' for this process (cached; refresh() re-reads the config)."""
    global _cache
    if _cache is None:
        _cache = _resolve()
    return _cache


def _resolve():
    cfg = config.load()
    pref = str(cfg.get("appearance", {}).get("color_scheme", "auto")).lower()
    if pref in ("light", "dark"):
        return pref
    try:
        from . import tokens
        return "dark" if str(tokens.active().meta.get("appearance", {}).get("app_scheme", "light")).lower() == "dark" else "light"
    except Exception:
        return "light"


def refresh():
    """Re-read config; returns True if the scheme changed."""
    global _cache
    old, _cache = _cache, None
    return mode() != old


def is_dark():
    return mode() == "dark"


def ink():
    """Foreground colour (RGBA tuple) for icons/text drawn by code on the current scheme's surfaces."""
    return SNOW if is_dark() else NAVY


def panel_class():
    return "darkpanel" if is_dark() else "lightpanel"


def app_material(name):
    """Map the light app material to its dark counterpart when the dark scheme is active."""
    return "window_dark" if (name == "window_light" and is_dark()) else name


_applied = None


def apply_system():
    """Tell the rest of the desktop (GTK apps, Firefox/Chromium via the settings portal) whether the desktop is dark.

    Browsers answer `prefers-color-scheme` from GTK / the freedesktop settings portal, not from glitterDE's own config,
    so we mirror our scheme into GTK's settings.ini and GSettings (org.gnome.desktop.interface color-scheme, which
    xdg-desktop-portal-gtk serves as the portal's `color-scheme`). Safe to call repeatedly; only writes on change."""
    global _applied
    dark = is_dark()
    if _applied == dark:
        return
    _applied = dark
    try:
        import os
        from gi.repository import Gio, GLib
        for d in ("gtk-3.0", "gtk-4.0"):
            folder = os.path.join(GLib.get_user_config_dir(), d)
            f = os.path.join(folder, "settings.ini")
            kf = GLib.KeyFile()
            try:
                kf.load_from_file(f, GLib.KeyFileFlags.NONE)
            except GLib.Error:
                pass
            try:
                if kf.get_boolean("Settings", "gtk-application-prefer-dark-theme") == dark:
                    continue
            except GLib.Error:
                pass
            os.makedirs(folder, exist_ok=True)
            kf.set_boolean("Settings", "gtk-application-prefer-dark-theme", dark)
            kf.save_to_file(f)
        src = Gio.SettingsSchemaSource.get_default()
        if src is not None and src.lookup("org.gnome.desktop.interface", True) is not None:
            st = Gio.Settings.new("org.gnome.desktop.interface")
            st.set_string("color-scheme", "prefer-dark" if dark else "prefer-light")
            cur = st.get_string("gtk-theme")
            if cur in ("", "Adwaita", "Adwaita-dark"):          # never override a theme the user picked themselves
                st.set_string("gtk-theme", "Adwaita-dark" if dark else "Adwaita")
            Gio.Settings.sync()
    except Exception as e:                                       # a missing schema / read-only config must never break the shell
        import sys
        print("glitterde: could not publish colour scheme:", e, file=sys.stderr)

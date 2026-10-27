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

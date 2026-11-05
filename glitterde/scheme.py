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


def menu_material():
    """Material for menus, popups and flyouts: light glass under the light scheme, dark glass under the dark one."""
    return "window_dark" if is_dark() else "window_light"


def app_material(name):
    """Map the light app material to its dark counterpart when the dark scheme is active."""
    return "window_dark" if (name == "window_light" and is_dark()) else name


_applied = None


def _theme_exists(name):
    import os
    from gi.repository import GLib
    dirs = [os.path.expanduser("~/.themes"), os.path.join(GLib.get_user_data_dir(), "themes")]
    dirs += [os.path.join(d, "themes") for d in GLib.get_system_data_dirs()]
    return any(os.path.isdir(os.path.join(d, name)) for d in dirs)


def _gtk_variant(cur, dark):
    """The light or dark twin of the GTK theme `cur` (Yaru-purple <-> Yaru-purple-dark), or None when there is no such twin."""
    base = cur[:-5] if cur.endswith("-dark") else cur
    if base in ("", "Adwaita"):
        return "Adwaita-dark" if dark else "Adwaita"
    want = base + "-dark" if dark else base
    return want if (want == cur or _theme_exists(want)) else None


def _gsettings_cli(dark, theme):
    import subprocess
    cmds = [["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", "prefer-dark" if dark else "prefer-light"]]
    if theme:
        cmds.append(["gsettings", "set", "org.gnome.desktop.interface", "gtk-theme", theme])
    for c in cmds:
        try:
            subprocess.run(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass


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
    apply_gtk_css()
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
            changed = False
            try:
                same = kf.get_boolean("Settings", "gtk-application-prefer-dark-theme") == dark
            except GLib.Error:
                same = False
            if not same:
                kf.set_boolean("Settings", "gtk-application-prefer-dark-theme", dark); changed = True
            try:
                tn = kf.get_string("Settings", "gtk-theme-name")
            except GLib.Error:
                tn = ""
            tw = _gtk_variant(tn or "Adwaita", dark) if (tn or dark) else None   # no theme chosen + dark: say "Adwaita-dark" instead of leaving GTK to guess
            if tw and tw != tn:                                                   # (this was skipped whenever the dark flag already matched)
                kf.set_string("Settings", "gtk-theme-name", tw); changed = True
            if changed:
                os.makedirs(folder, exist_ok=True)
                kf.save_to_file(f)
        src = Gio.SettingsSchemaSource.get_default()
        if src is not None and src.lookup("org.gnome.desktop.interface", True) is not None:
            st = Gio.Settings.new("org.gnome.desktop.interface")
            st.set_string("color-scheme", "prefer-dark" if dark else "prefer-light")
            cur = st.get_string("gtk-theme")
            want = _gtk_variant(cur, dark)                       # Adwaita, Yaru, Yaru-purple ... <-> their -dark twin; unknown themes are left alone
            if want and want != cur:
                st.set_string("gtk-theme", want)
            Gio.Settings.sync()
            try:
                backend = type(Gio.SettingsBackend.get_default()).__name__.lower()
            except Exception:
                backend = ""
            if "memory" in backend or "null" in backend:     # no dconf in this session: GTK4 / portal dialogs would never see the change
                _gsettings_cli(dark, want)
    except Exception as e:                                       # a missing schema / read-only config must never break the shell
        import sys
        print("glitterde: could not publish colour scheme:", e, file=sys.stderr)


_GTK_BEGIN, _GTK_END = "/* >>> glitterDE menus (managed, do not edit) >>> */", "/* <<< glitterDE menus <<< */"


def gtk_menu_css(dark):
    """One consistent look for context menus and popovers of GTK 3 / GTK 4 / libadwaita apps (Files, Firefox, GIMP ...): the same surface for
    the menu and its submenus (no darker inner block), rounded rows with even padding, one separator style."""
    if dark:
        bg, ink, hover, sep, sel = "rgba(34,30,84,0.86)", "#ecebfa", "rgba(255,255,255,0.14)", "rgba(255,255,255,0.14)", "rgba(168,150,255,0.40)"
    else:
        bg, ink, hover, sep, sel = "rgba(236,232,252,0.88)", "#2a2d6e", "rgba(96,108,255,0.18)", "rgba(42,45,110,0.16)", "rgba(96,108,255,0.34)"
    return """%(b)s
/* GTK 3 */
menu, .menu, .context-menu { background-color: %(bg)s; background-image: none; color: %(ink)s; border: 1px solid rgba(255,255,255,0.30); border-radius: 12px; padding: 5px; box-shadow: none; }
menu menu, .menu .menu { margin: 0; }
menuitem { color: %(ink)s; border-radius: 8px; padding: 6px 10px; margin: 1px 0; background-image: none; }
menuitem:hover, menuitem:selected { background-color: %(hover)s; color: %(ink)s; }
menuitem label, menuitem accelerator, menuitem arrow { color: %(ink)s; }
menu separator, .menu separator { background-color: %(sep)s; margin: 4px 6px; min-height: 1px; }
/* GTK 4 / libadwaita popovers: the parent menu and every submenu share ONE surface */
popover.background, popover.menu { background: transparent; box-shadow: none; }
popover.background > contents, popover.menu > contents { background-color: %(bg)s; background-image: none; color: %(ink)s; border: 1px solid rgba(255,255,255,0.30);
                                                          border-radius: 12px; padding: 5px; box-shadow: none; }
popover.menu box.inline-buttons, popover.menu box.circular-buttons { background: transparent; }
popover.menu modelbutton, popover.menu button.model { color: %(ink)s; background-image: none; border-radius: 8px; padding: 6px 10px; min-height: 26px; margin: 1px 0; }
popover.menu modelbutton:hover, popover.menu modelbutton:selected, popover.menu modelbutton:focus { background-color: %(hover)s; }
popover.menu modelbutton:checked { background-color: %(sel)s; }
popover.menu scrolledwindow, popover.menu stack, popover.menu box, popover.menu viewport, popover.menu list, popover.menu row { background-color: transparent; background-image: none; }
popover.menu separator { background-color: %(sep)s; margin: 4px 6px; min-height: 1px; }
popover.menu label { color: %(ink)s; }
%(e)s
""" % dict(b=_GTK_BEGIN, e=_GTK_END, bg=bg, ink=ink, hover=hover, sep=sep, sel=sel)


def apply_gtk_css():
    """Write the menu stylesheet into ~/.config/gtk-3.0/gtk.css and gtk-4.0/gtk.css (our block only; anything else the person wrote stays)."""
    import os
    try:
        from gi.repository import GLib
        css = gtk_menu_css(is_dark())
        for d in ("gtk-3.0", "gtk-4.0"):
            folder = os.path.join(GLib.get_user_config_dir(), d)
            f = os.path.join(folder, "gtk.css")
            try:
                with open(f, encoding="utf-8") as fh:
                    old = fh.read()
            except OSError:
                old = ""
            if _GTK_BEGIN in old and _GTK_END in old:
                a, b = old.index(_GTK_BEGIN), old.index(_GTK_END) + len(_GTK_END)
                new = old[:a].rstrip("\n") + ("\n" if old[:a].strip() else "") + css.rstrip("\n") + old[b:]
            else:
                new = (old.rstrip("\n") + "\n\n" if old.strip() else "") + css
            if new != old:
                os.makedirs(folder, exist_ok=True)
                with open(f, "w", encoding="utf-8") as fh:
                    fh.write(new)
    except Exception as e:
        import sys
        print("glitterde: could not write the GTK menu stylesheet:", e, file=sys.stderr)

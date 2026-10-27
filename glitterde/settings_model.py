"""Structured settings model: each setting has id, title, description, type,
default and constraints. SparkSettings generates its controls and search from this; shell/WM/apps read values via get()."""
import os

from . import config


def S(id, title, desc, typ, default, **c):
    d = dict(id=id, title=title, desc=desc, type=typ, default=default)
    d.update(c)
    return d


YN = lambda *a, **k: S(*a, **k)
SETTINGS = [
    # --- Appearance
    S("appearance.color_scheme", "Colour scheme", "Light or dark windows, menus and launcher. Automatic follows the theme.", "choice", "auto",
      choices=[("auto", "Automatic"), ("light", "Light"), ("dark", "Dark")], page="Theme"),
    S("appearance.transparency", "Transparency", "Tinted, translucent glass surfaces. Off maps every material to an opaque surface (reduced-effects mode).", "bool", True, page="Transparency"),
    S("appearance.blur_level", "Blur behind surfaces", "How strongly the background is blurred behind glass.", "choice", "normal",
      choices=[("off", "Off"), ("light", "Light"), ("normal", "Normal"), ("strong", "Strong")], page="Transparency"),
    S("appearance.glass_opacity", "Glass opacity", "Scales the opacity of every glass surface (1.0 = theme default).", "float", 1.0, min=0.5, max=1.2, step=0.05, page="Transparency"),
    S("appearance.radius_scale", "Corner roundness", "Scales the corner radius of windows, cards and popups.", "float", 1.0, min=0.0, max=1.5, step=0.1, page="Transparency"),
    # --- Windows
    S("window.titlebar_height", "Titlebar height", "Height of window titlebars, in pixels.", "int", 38, min=28, max=52, page="Windows"),
    S("window.layout", "Titlebar layout", "Button order, button style and title position.", "choice", "glitter",
      choices=[("glitter", "Glitter (default)"), ("windows", "Windows"), ("macos", "macOS"), ("gnome", "GNOME"), ("kde", "KDE Plasma"),
               ("elementary", "elementary"), ("ubuntu", "Ubuntu"), ("chromeos", "ChromeOS"), ("minimal", "Minimal (close only)")], page="Windows"),
    S("window.button_side", "Window button side", "Which side the minimise / maximise / close buttons are on.", "choice", "right", choices=[("right", "Right"), ("left", "Left")], page="Windows"),
    S("window.button_size", "Window button size", "Size of the titlebar button icons.", "int", 13, min=10, max=18, page="Windows"),
    S("window.button_shape", "Window button hover shape", "Shape of the highlight behind a titlebar button.", "choice", "rounded", choices=[("rounded", "Rounded square"), ("circle", "Circle")], page="Windows"),
    S("window.inactive_opacity", "Inactive window opacity", "Opacity of window frames that do not have focus.", "float", 0.9, min=0.5, max=1.0, step=0.05, page="Windows"),
    S("window.shadow", "Window shadows", "Soft shadows under windows (needs the compositor).", "bool", True, page="Windows"),
    S("window.edge_margin", "Screen edge gap", "Minimum gap between windows and the panel / screen edge.", "int", 6, min=0, max=24, page="Windows"),
    S("window.focus_follows_mouse", "Focus follows mouse", "Focus the window under the pointer without clicking.", "bool", False, page="Windows"),
    S("workspaces.count", "Number of workspaces", "How many workspaces exist (1-8).", "int", 4, min=1, max=8, page="Windows"),
    # --- Panel
    S("panel.height", "Panel height", "Height of the top panel in pixels.", "int", 38, min=30, max=52, page="Panel"),
    S("panel.position", "Panel position", "Put the panel at the top or the bottom of the screen.", "choice", "top", choices=[("top", "Top"), ("bottom", "Bottom")], page="Panel"),
    S("panel.show_greeting", "Show greeting", "Show 'Good evening, name' in the panel.", "bool", False, page="Panel"),
    S("panel.show_search", "Show search field", "Show the launcher search field in the panel.", "bool", True, page="Panel"),
    S("panel.tray_wifi", "Show network icon", "Quick settings: network.", "bool", True, page="Panel"),
    S("panel.tray_bluetooth", "Show Bluetooth icon", "Quick settings: Bluetooth.", "bool", True, page="Panel"),
    S("panel.tray_volume", "Show audio icon", "Quick settings: audio output.", "bool", True, page="Panel"),
    S("panel.tray_brightness", "Show brightness icon", "Quick settings: brightness and night light.", "bool", True, page="Panel"),
    S("panel.tray_battery", "Show battery / power icon", "Quick settings: power. Hidden automatically on desktops without a battery.", "bool", True, page="Panel"),
    S("panel.clock_24h", "24-hour clock", "Use 24-hour time in the panel and clock widget.", "bool", True, page="Panel"),
    S("panel.clock_date", "Show date in panel clock", "Show the weekday and date next to the time.", "bool", True, page="Panel"),
    # --- Dock
    S("dock.style", "Where applications live", "A floating dock, or the panel itself (left next to the logo, exactly in the centre, or to the right). In the panel modes there is no dock window and the search field moves aside when the apps take the centre.", "choice", "dock",
      choices=[("dock", "Floating dock"), ("panel_left", "In the panel, left"), ("panel_center", "In the panel, centre"), ("panel_right", "In the panel, right")], page="Dock"),
    S("dock.position", "Dock position", "Which screen edge the floating dock sits on (ignored when applications are in the panel).", "choice", "bottom", choices=[("bottom", "Bottom"), ("left", "Left"), ("right", "Right")], page="Dock"),
    S("dock.reserve_space", "Keep windows clear of the dock", "Maximised windows stop at the dock instead of going under it.", "bool", True, page="Dock"),
    S("dock.icon_size", "Dock icon size", "Size of application icons in the dock.", "int", 38, min=28, max=56, page="Dock"),
    S("dock.indicator_position", "Indicator position", "Put the running-app dot below or above the app icon.", "choice", "below", choices=[("below", "Below the icon"), ("above", "Above the icon")], page="Dock"),
    S("dock.indicators", "Running-app indicators", "Show a dot under apps that are running.", "bool", True, page="Dock"),
    # --- Drives
    S("drives.automount", "Mount drives when plugged in", "USB sticks, SD cards and external disks are mounted automatically as soon as they are connected (and when you log in). Internal disks are never touched.", "bool", True, page="Drives"),
    S("drives.notify", "Notify when a drive is mounted", "Show a notification with an Open button.", "bool", True, page="Drives"),
    S("drives.open_after_mount", "Open the drive in SparkFiles", "Open a file window on the drive right after it is mounted.", "bool", False, page="Drives"),
    # --- Launcher
    S("launcher.button_icon", "Apps menu icon", "Icon on the button that opens the launcher.", "icon", "sparkle_logo", page="Launcher"),
    S("launcher.layout", "Apps menu layout", "Shape and size of the apps menu.", "choice", "glitter",
      choices=[("glitter", "Glitter (default)"), ("grid", "Full-screen grid"), ("start", "Start menu (Windows)"), ("launchpad", "Launchpad (macOS)"),
               ("overview", "Overview (GNOME)"), ("kickoff", "Classic menu (KDE)"), ("list", "Compact list")], page="Launcher"),
    S("launcher.view", "Apps view", "Icons in a grid or one app per row. The button next to the search box switches it too.", "choice", "grid",
      choices=[("grid", "Grid"), ("list", "List")], page="Launcher"),
    S("launcher.position", "Launcher position", "Where the application launcher opens.", "choice", "left", choices=[("left", "Left edge"), ("center", "Centre"), ("right", "Right edge")], page="Launcher"),
    S("launcher.columns", "Columns", "Number of app columns.", "int", 5, min=3, max=8, page="Launcher"),
    S("launcher.icon_size", "Icon size", "Size of application icons in the launcher.", "int", 44, min=32, max=72, page="Launcher"),
    S("launcher.list_icon_size", "List icon size", "Size of the icons when apps are shown one per row (list view, Classic menu, Compact list).", "int", 32, min=16, max=64, page="Launcher"),
    S("launcher.height", "Height", "Height of the launcher in pixels.", "int", 440, min=300, max=760, page="Launcher"),
    S("launcher.show_categories", "Show category list", "The category sidebar on the left of the launcher.", "bool", True, page="Launcher"),
    S("launcher.opacity", "Launcher opacity", "Extra opacity for the launcher so text stays readable over busy backgrounds.", "float", 1.2, min=0.8, max=1.6, step=0.05, page="Launcher"),
    # --- Notifications
    S("notifications.popups", "Pop-up notifications", "Show a pop-up when a notification arrives (they are always kept in the list).", "bool", True, page="Notifications"),
    S("notifications.popup_seconds", "Pop-up duration", "Seconds a pop-up stays on screen.", "int", 5, min=2, max=15, page="Notifications"),
    S("notifications.position", "Pop-up position", "Where pop-ups appear.", "choice", "top-center", choices=[("top-center", "Top centre"), ("top-right", "Top right"), ("top-left", "Top left")], page="Notifications"),
    # --- Desktop
    S("desktop.show_icons", "Show desktop icons", "Show the files of your Desktop folder (and Home / Trash below) on the desktop. Hiding them does not delete anything.", "bool", True, page="Desktop icons"),
    S("desktop.icon_size", "Desktop icon size", "Size of icons for files on the desktop.", "choice", "medium", choices=[("small", "Small"), ("medium", "Medium"), ("large", "Large")], page="Desktop icons"),
    S("desktop.sort", "Sort desktop icons", "Order of icons from your Desktop folder.", "choice", "name", choices=[("name", "Name"), ("type", "Type"), ("modified", "Last modified")], page="Desktop icons"),
    S("desktop.show_hidden", "Show hidden files", "Include dot-files from your Desktop folder.", "bool", False, page="Desktop icons"),
    S("desktop.show_workspaces", "Show workspace selector", "The workspace pill in the corner of the desktop (logo, numbered workspaces, +). Workspaces still exist when it is hidden; use Ctrl+Alt+arrows or the window menu.", "bool", True, page="Desktop icons"),
    S("desktop.show_home", "Show Home on the desktop", "A shortcut to your home folder.", "bool", False, page="Desktop icons"),
    S("desktop.show_trash", "Show Trash on the desktop", "A shortcut to the trash.", "bool", False, page="Desktop icons"),
    S("desktop.wallpaper_fit", "Wallpaper fit", "How the wallpaper is fitted to the screen.", "choice", "cover", choices=[("cover", "Fill (crop)"), ("fit", "Fit (letterbox)"), ("center", "Centre"), ("stretch", "Stretch")], page="Wallpaper"),
    # --- Fonts
    S("fonts.ui", "Interface font", "Font family for the shell and Spark apps (empty = Inter).", "font", "", page="Fonts"),
    S("fonts.monospace", "Terminal font", "Monospace font used by SparkTerm.", "font", "JetBrains Mono 10", page="Fonts"),
]
# Settings that exist but do not do anything useful yet are tagged experimental=True. They are hidden in SparkSettings
# until "Show experimental settings" (About page) is switched on. Whole pages are tagged in sparksettings.EXPERIMENTAL_PAGES.
SETTINGS.append(S("experimental.show", "Show experimental settings",
                  "Show settings that are unfinished.", "bool", False, page="About", internal=True))
BY_ID = {s["id"]: s for s in SETTINGS}
_cache = {"mt": None, "data": {}}


def _data():
    try:
        mt = os.path.getmtime(config.path())
    except OSError:
        mt = 0
    if mt != _cache["mt"]:
        _cache["mt"], _cache["data"] = mt, config.load()
    return _cache["data"]


def get(id, default=None):
    sec, key = id.split(".", 1)
    s = BY_ID.get(id)
    d = s["default"] if s else default
    v = _data().get(sec, {}).get(key, d)
    if s and s["type"] in ("int", "float"):
        try:
            v = max(s["min"], min(s["max"], (int if s["type"] == "int" else float)(v)))
        except (TypeError, ValueError):
            v = d
    return v


def set(id, value):
    sec, key = id.split(".", 1)
    config.set(sec, key, value)


def reset(id):
    sec, key = id.split(".", 1)
    d = config.load()
    d.get(sec, {}).pop(key, None)
    if sec in d and not d[sec]:
        d.pop(sec)
    config.save(d)
    _cache["mt"] = None


def experimental_enabled():
    return bool(get("experimental.show"))


def visible_settings(include_experimental=None):
    """Settings SparkSettings may show (hides internal ones and, unless enabled, experimental ones)."""
    if include_experimental is None:
        include_experimental = experimental_enabled()
    return [s for s in SETTINGS if not s.get("internal") and (include_experimental or not s.get("experimental"))]

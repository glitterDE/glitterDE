"""User settings (~/.config/glitterde/settings.toml): written by SparkSettings, read by shell/WM/apps."""
import contextlib
import os

from .tokens import _load


BUNDLED_ICONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "share", "icons")
DEFAULT_CURSOR = "glitterde"


def _setup_xcursor_path():
    """libXcursor does not look in our checkout, so add the bundled icon dir (before the system ones)."""
    cur = os.environ.get("XCURSOR_PATH")
    if cur is None:
        cur = "~/.local/share/icons:~/.icons:/usr/share/icons:/usr/share/pixmaps"
    if BUNDLED_ICONS not in cur:
        os.environ["XCURSOR_PATH"] = BUNDLED_ICONS + ":" + cur


_setup_xcursor_path()


def _icon_dirs():
    dirs = [BUNDLED_ICONS, os.path.expanduser("~/.local/share/icons"), os.path.expanduser("~/.icons")]
    dirs += [os.path.join(d, "icons") for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    return dirs


def cursor_theme():
    """Configured cursor theme, else the bundled/installed glitterde theme (when present), else None (system default)."""
    t = load().get("cursor", {}).get("theme")
    if t:
        return str(t)
    return DEFAULT_CURSOR if any(os.path.isdir(os.path.join(d, DEFAULT_CURSOR, "cursors")) for d in _icon_dirs()) else None


def config_dir():
    d = os.environ.get("GLITTERDE_CONFIG_HOME") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "glitterde")
    return d


def path(name="settings.toml"):
    return os.path.join(config_dir(), name)


def load(name="settings.toml"):
    try:
        return _load(path(name))
    except (OSError, ValueError):
        return {}
    except Exception:                      # corrupt file must never take the session down
        return {}


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return "0.0"                                       # nan / inf are not valid settings (and not valid TOML)
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return '"' + s + '"'


def save(data, name="settings.toml"):
    os.makedirs(config_dir(), exist_ok=True)
    out = []
    for sec, vals in data.items():
        out.append("[%s]" % sec)
        out += ["%s = %s" % (k, _fmt(v)) for k, v in vals.items()]
        out.append("")
    tmp = "%s.%d.tmp" % (path(name), os.getpid())           # per-process name: the shell, WM and Settings can all save at once
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(out))
        os.replace(tmp, path(name))
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise            # atomic: watchers never see a half-written file


@contextlib.contextmanager
def edit(name="settings.toml"):
    """Locked read-modify-write:   with config.edit() as d: d["panel"]["x"] = 1   (saved when the block ends, not saved if it raises).
    The shell, the WM and Settings all change this file; without the lock two near-simultaneous changes each started from the same old
    contents and one of them was silently lost."""
    os.makedirs(config_dir(), exist_ok=True)
    lock = None
    try:
        import fcntl
        lock = open(path(name) + ".lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX)
    except (ImportError, OSError):
        lock = None
    try:
        d = load(name)
        yield d
        save(d, name)
    finally:
        if lock is not None:
            lock.close()


def update(changes, name="settings.toml"):
    """Several settings in ONE write: update({"panel": {"position": "top"}, "dock": {"position": "left"}}). One write means one reload
    in the shell and the WM instead of one per setting."""
    with edit(name) as d:
        for section, vals in changes.items():
            d.setdefault(section, {}).update(vals)


def set(section, key, value, name="settings.toml"):
    update({section: {key: value}}, name)


def remove(section, key=None, name="settings.toml"):
    """Delete one setting, or the whole section when key is None. An emptied section is removed too."""
    with edit(name) as d:
        if key is None:
            d.pop(section, None)
        else:
            d.get(section, {}).pop(key, None)
            if section in d and not d[section]:
                d.pop(section)

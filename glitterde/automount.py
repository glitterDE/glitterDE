"""Mount removable drives (USB sticks, SD cards, external disks) when they are plugged in, like a desktop environment should.

Uses GIO's volume monitor, which talks to udisks2, so no root and no extra daemon: it works wherever udisks2 (or gvfs) is installed and
silently does nothing where it is not. Only *removable* volumes are touched; internal disks, loop devices and anything already mounted
are left alone. Encrypted volumes are not unlocked automatically (that needs a password); they appear in the file manager as usual.

on_event(kind, name, detail) is called on the main loop:
    "mounted"  detail = file:// URI of the mount root
    "failed"   detail = error text
    "removed"  detail = ""   (a drive that was mounted is gone: safe to say "removed")
"""
import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402


def is_removable(volume):
    """True for volumes on USB sticks, SD cards, external drives and optical discs; False for internal disks and loop devices."""
    try:
        if (volume.get_identifier("class") or "device") not in ("device", ""):      # e.g. "loop", "network"
            return False
        drive = volume.get_drive()
        if drive is None:
            return False
        return bool(drive.is_removable() or drive.is_media_removable() or drive.can_eject())
    except Exception:
        return False


class AutoMounter:
    def __init__(self, on_event=None, enabled=lambda: True):
        self.on_event = on_event or (lambda *a: None)
        self.enabled = enabled
        self.monitor = Gio.VolumeMonitor.get()
        self._busy = set()                       # volumes with a mount in flight
        self._tried = set()                      # volumes that already failed once: do not retry in a loop
        self._ours = set()                       # mounts we made: tell the user when they disappear
        self.monitor.connect("volume-added", lambda _m, v: self.consider(v))
        self.monitor.connect("volume-changed", lambda _m, v: self.consider(v))           # media inserted into a card reader / disc drive
        self.monitor.connect("mount-removed", self._on_mount_removed)
        GLib.idle_add(self.scan)

    def scan(self):
        """Drives that were already plugged in when the session started."""
        for v in self.monitor.get_volumes():
            self.consider(v)
        return False

    def consider(self, volume):
        try:
            if not self.enabled() or not self._eligible(volume):
                return
            key = volume.get_uuid() or volume.get_identifier("unix-device") or volume.get_name()
            if key in self._busy or key in self._tried:
                return
            self._busy.add(key)
            volume.mount(Gio.MountMountFlags.NONE, Gio.MountOperation(), None, self._done, key)
        except GLib.Error:
            pass

    @staticmethod
    def _eligible(volume):
        return bool(volume.can_mount() and volume.get_mount() is None and is_removable(volume))

    def _done(self, volume, res, key):
        self._busy.discard(key)
        try:
            volume.mount_finish(res)
        except GLib.Error as e:
            self._tried.add(key)
            self.on_event("failed", volume.get_name(), e.message)
            return
        m = volume.get_mount()
        if m is not None:
            self._ours.add(m.get_name())
            self.on_event("mounted", m.get_name(), m.get_root().get_uri())

    def _on_mount_removed(self, _mon, mount):
        name = mount.get_name()
        if name in self._ours:
            self._ours.discard(name)
            self.on_event("removed", name, "")
        self._tried.clear()                       # a re-plugged drive gets a fresh attempt

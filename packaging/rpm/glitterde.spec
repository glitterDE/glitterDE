# glitterDE RPM (Fedora / RHEL-family / openSUSE-style names).  Build:  packaging/rpm/build.sh
%global debug_package %{nil}
%global _build_id_links none

Name:           glitterde
Version:        %{?pkgversion}%{!?pkgversion:0.13.1}
Release:        1%{?dist}
Summary:        A customisable but pretty desktop environment :3
License:        GPL-3.0-only
URL:            https://glitterde.github.io
Source0:        glitterde-%{version}.tar.gz

BuildRequires:  gcc
BuildRequires:  make
BuildRequires:  pkgconfig(x11)
BuildRequires:  pkgconfig(xcomposite)
BuildRequires:  pkgconfig(xdamage)
BuildRequires:  pkgconfig(xfixes)
BuildRequires:  pkgconfig(xext)
BuildRequires:  pkgconfig(cairo)
BuildRequires:  pkgconfig(x11-xcb)
BuildRequires:  pkgconfig(xcb)
BuildRequires:  pkgconfig(xcb-present)
BuildRequires:  autoconf
BuildRequires:  automake
BuildRequires:  libtool
BuildRequires:  intltool
BuildRequires:  gettext
BuildRequires:  pkgconfig(gtk+-3.0)

Requires:       python3 >= 3.9
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       python3-xlib
Requires:       python3-pillow
Requires:       gtk3
Requires:       libwnck3
Requires:       vte291
Requires:       gdk-pixbuf2
Requires:       pango
Requires:       cairo
Requires:       libX11
Requires:       libxcb
Requires:       librsvg2
Requires:       libXcomposite
Requires:       libXdamage
Requires:       libXfixes
Requires:       libXext
Requires:       dbus-daemon
Requires:       xdg-utils
Recommends:     NetworkManager
Recommends:     bluez
Recommends:     wireplumber
Recommends:     brightnessctl
Recommends:     power-profiles-daemon
Recommends:     rsms-inter-fonts
Recommends:     jetbrains-mono-fonts
Recommends:     libnotify
Recommends:     gvfs
Suggests:       polkit-gnome
Suggests:       gammastep

%description
A customisable but pretty desktop environment :3

%prep
%autosetup -n glitterde-%{version}

%build
make %{?_smp_mflags}

%install
make install DESTDIR=%{buildroot} PREFIX=%{_prefix} LIBDIR=%{_prefix}/lib/glitterde

%post
/usr/bin/gtk-update-icon-cache -q -f %{_datadir}/icons/hicolor &>/dev/null || :
/usr/bin/update-desktop-database -q %{_datadir}/applications &>/dev/null || :

%files
%{_prefix}/lib/glitterde
%{_bindir}/glitterde-session
%{_bindir}/glitterde-screenshot
%{_bindir}/glitterde-shell
%{_bindir}/glitterde-welcome
%{_bindir}/glitterde-autostart
%{_bindir}/glitter-wm
%{_bindir}/glitter-comp
%{_bindir}/sparkfiles
%{_bindir}/sparksettings
%{_bindir}/sparkterm
%{_datadir}/applications/glitterde-*.desktop
%{_datadir}/xsessions/glitterde.desktop
%{_datadir}/icons/hicolor/*/apps/glitterde-*
%{_datadir}/icons/glitterde
%{_datadir}/icons/glitterde-glass
%{_datadir}/doc/glitterde

%changelog
* Tue Oct 27 2026 rubythecutie <228643222+rubythecutie@users.noreply.github.com> - 0.13.1-1
- Share source publicly for the first time

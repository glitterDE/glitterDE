# glitterDE - build the compositor and install the desktop environment.
#   make                      build bin/glitter-comp (needs libx11/xcomposite/xdamage/xfixes/xext/xcb-present/cairo dev packages)
#                             and, when autoconf is installed, bin/yad (the glitterDE-themed YAD 0.40.0 from third_party/yad)
#   make yad                  build only the themed yad (needs autoconf automake libtool intltool gettext libgtk-3-dev)
#   sudo make install         install to /usr (PREFIX=/usr/local to keep it separate)
#   make install DESTDIR=pkg  stage into a package root (used by the deb/rpm/Arch recipes in packaging/)
PREFIX  ?= /usr
DESTDIR ?=
LIBDIR  ?= $(PREFIX)/lib/glitterde
BINDIR  ?= $(PREFIX)/bin
DATADIR ?= $(PREFIX)/share
VERSION := $(shell cat VERSION)
APPS    := glitterde-screenshot glitterde-session glitterde-shell glitterde-welcome glitterde-autostart glitter-wm glitter-comp sparkfiles sparksettings sparkterm sparkcode

YAD_OK := $(shell command -v autoreconf >/dev/null 2>&1 && command -v intltoolize >/dev/null 2>&1 && echo yes)

all: bin/glitter-comp $(if $(YAD_OK),bin/yad)

yad: bin/yad

bin/yad: third_party/yad-glitterde.patch
	rm -rf build/yad && mkdir -p build && cp -a third_party/yad build/yad
	cd build/yad && autoreconf -if >/dev/null 2>&1 && ./configure --with-gtk=gtk3 --disable-html --disable-spell --disable-sourceview \
	    --disable-icon-browser >/dev/null && $(MAKE) -s
	install -m755 build/yad/src/yad bin/yad

bin/glitter-comp: comp/glitter-comp.c
	$(MAKE) -C comp

install: all
	install -d $(DESTDIR)$(LIBDIR)/bin $(DESTDIR)$(BINDIR) $(DESTDIR)$(DATADIR)/applications $(DESTDIR)$(DATADIR)/xsessions \
	           $(DESTDIR)$(DATADIR)/icons $(DESTDIR)$(DATADIR)/doc/glitterde
	cp -a glitterde themes wallpapers $(DESTDIR)$(LIBDIR)/
	find $(DESTDIR)$(LIBDIR) -name __pycache__ -prune -exec rm -rf {} +
	for a in $(APPS); do \
	    install -m755 bin/$$a $(DESTDIR)$(LIBDIR)/bin/$$a; \
	    printf '#!/bin/sh\nexec %s/bin/%s "$$@"\n' "$(LIBDIR)" "$$a" > $(DESTDIR)$(BINDIR)/$$a; chmod 755 $(DESTDIR)$(BINDIR)/$$a; \
	done
	for f in share/applications/*.desktop; do \
	    sed -e 's|^Exec=\([a-z-]*\)|Exec=$(BINDIR)/\1|' -e 's|^TryExec=\([a-z-]*\)|TryExec=$(BINDIR)/\1|' $$f > $(DESTDIR)$(DATADIR)/applications/$$(basename $$f); \
	    chmod 644 $(DESTDIR)$(DATADIR)/applications/$$(basename $$f); \
	done
	sed -e 's|^Exec=.*|Exec=$(BINDIR)/glitterde-session|' -e 's|^TryExec=.*|TryExec=$(BINDIR)/glitterde-session|' packaging/glitterde.desktop \
	    > $(DESTDIR)$(DATADIR)/xsessions/glitterde.desktop; chmod 644 $(DESTDIR)$(DATADIR)/xsessions/glitterde.desktop
	cp -a share/icons/hicolor $(DESTDIR)$(DATADIR)/icons/
	cp -a share/icons/glitterde share/icons/glitterde-glass $(DESTDIR)$(DATADIR)/icons/
	[ ! -x bin/yad ] || install -m755 bin/yad $(DESTDIR)$(LIBDIR)/bin/yad
	install -m644 README.md VERSION $(DESTDIR)$(DATADIR)/doc/glitterde/

uninstall:
	rm -rf $(DESTDIR)$(LIBDIR) $(DESTDIR)$(DATADIR)/doc/glitterde $(DESTDIR)$(DATADIR)/xsessions/glitterde.desktop \
	       $(DESTDIR)$(DATADIR)/icons/glitterde $(DESTDIR)$(DATADIR)/icons/glitterde-glass
	for a in $(APPS); do rm -f $(DESTDIR)$(BINDIR)/$$a; done
	rm -f $(DESTDIR)$(DATADIR)/applications/glitterde-*.desktop

# source tarball for the package recipes: dist/glitterde-VERSION.tar.gz (no build products, no caches)
dist:
	mkdir -p dist
	tar --exclude=__pycache__ --exclude=bin/glitter-comp --exclude=bin/yad --exclude=build --exclude=dist --exclude=.git \
	    --transform 's,^\.,glitterde-$(VERSION),' -czf dist/glitterde-$(VERSION).tar.gz .

clean:
	$(MAKE) -C comp clean
	rm -rf build bin/yad
	find . -name __pycache__ -prune -exec rm -rf {} +

.PHONY: all yad install uninstall dist clean

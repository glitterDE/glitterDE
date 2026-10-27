CC ?= gcc
CFLAGS ?= -O2 -Wall
LIBS = $(shell pkg-config --cflags --libs cairo x11 x11-xcb xcb xcb-present xcomposite xdamage xfixes xext)
../bin/glitter-comp: glitter-comp.c
	$(CC) $(CFLAGS) -o $@ $< $(LIBS) -lm
clean:
	rm -f ../bin/glitter-comp

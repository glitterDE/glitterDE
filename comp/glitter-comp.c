/* glitter-comp: compositing manager for glitterDE.
 * XComposite (manual redirect) + XDamage + cairo-xlib. Draws shadows, alpha-blends translucent windows and blurs
 * whatever is behind windows that carry _GLITTER_BLUR=1 (real glass). Per-window hints (CARDINAL, set by glitter-wm):
 *   _GLITTER_BLUR 0/1   _GLITTER_SHADOW 0/1   _GLITTER_RADIUS px (corner radius used for blur clip and shadow)
 * It only reads the stacking order and window contents; it never manages windows.
 *
 * Tear-free output: finished dirty rectangles are handed to the X Present extension (xcb_present_pixmap), which copies them
 * to the overlay window at the next vertical blank, one frame in flight at a time (so the paint rate follows the monitor's
 * refresh rate). Without Present, or with GLITTERDE_VSYNC=0, the old direct copy is used.
 * Resize hold: when a window changes size, its previous contents stay on screen until the client has redrawn at the new
 * size (or 150 ms passed), so you never see the blank / half-drawn frames that look like tearing while resizing.
 */
#define _GNU_SOURCE
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <X11/extensions/Xcomposite.h>
#include <X11/extensions/Xdamage.h>
#include <X11/extensions/Xfixes.h>
#include <X11/extensions/shape.h>
#include <cairo/cairo.h>
#include <cairo/cairo-xlib.h>
#include <X11/Xlib-xcb.h>
#include <xcb/xcb.h>
#include <xcb/present.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <time.h>
#include <unistd.h>

typedef struct Win {
    Window id;
    int x, y, w, h, viewable, depth;
    Visual *visual;
    Damage damage;
    Pixmap pix;
    cairo_surface_t *surf;
    int blur, shadow, radius;
    XRectangle *shape; int nshape; int shape_valid;
    cairo_surface_t *blur_surf; int blur_valid, bx, by, bw, bh;      /* cached blurred backdrop */
    cairo_surface_t *shadow_surf; int sh_w, sh_h, sh_r;             /* cached shadow bitmap */
    Window above_id; int has_above;                                 /* sibling below us, from the last ConfigureNotify */
    Pixmap old_pix; cairo_surface_t *old_surf; int old_w, old_h;    /* resize hold: contents from before the last resize */
    double hold_until; int body_y;                                  /* hold deadline (ms); y where the client area starts inside the frame */
    struct Win *next;
} Win;

static Display *dpy;
static Window root, overlay, mgr;
static int W, H, scr, damage_ev, shape_ev, debug;
static Win *wins;                       /* bottom -> top */
static Pixmap bb;
static cairo_surface_t *bb_surf, *ov_surf;
static int dirty = 1, running = 1;
static long n_blur, n_restack, n_damage;          /* statistics (GLITTERDE_COMP_STATS=1) */
static int dx1 = 0, dy1 = 0, dx2 = 0, dy2 = 0;   /* dirty rectangle (screen coords), empty when dx2<=dx1 */
#define PAD 64
static Atom a_blur, a_shadow, a_radius, a_body;
static double now_ms(void);

static int on_error(Display *d, XErrorEvent *e) { (void)d; (void)e; return 0; }
static volatile sig_atomic_t dump_stats;
static void on_term(int s) { (void)s; running = 0; }
static void on_usr1(int s) { (void)s; dump_stats = 1; }

static Win *find(Window id) { for (Win *w = wins; w; w = w->next) if (w->id == id) return w; return NULL; }


static void add_dirty(int x, int y, int w, int h) {
    int x2 = x + w, y2 = y + h;
    if (x < 0) x = 0;
    if (y < 0) y = 0;
    if (x2 > W) x2 = W;
    if (y2 > H) y2 = H;
    if (x2 <= x || y2 <= y) return;
    if (dx2 <= dx1 || dy2 <= dy1) { dx1 = x; dy1 = y; dx2 = x2; dy2 = y2; }
    else { if (x < dx1) dx1 = x; if (y < dy1) dy1 = y; if (x2 > dx2) dx2 = x2; if (y2 > dy2) dy2 = y2; }
    dirty = 1;
}
static void dirty_win(Win *w) { add_dirty(w->x - PAD, w->y - PAD, w->w + 2 * PAD, w->h + 2 * PAD); }
/* the cached blur of a window only depends on what is painted inside its own rectangle: invalidate just the ones touched */
static int overlap(int ax, int ay, int aw, int ah, int bx, int by, int bw, int bh);
static void blur_invalidate_rect(int x, int y, int w, int h) {
    for (Win *o = wins; o; o = o->next)
        if (o->blur && o->blur_valid && overlap(x, y, w, h, o->x, o->y, o->w, o->h)) o->blur_valid = 0;
}
static int overlap(int ax, int ay, int aw, int ah, int bx, int by, int bw, int bh) {
    return ax < bx + bw && bx < ax + aw && ay < by + bh && by < ay + ah;
}
/* something under (above-stack) windows changed: their cached blur is stale */
static void blur_invalidate_above(Win *d, int x, int y, int w, int h) {
    for (Win *o = d->next; o; o = o->next)
        if (o->blur && overlap(x, y, w, h, o->x, o->y, o->w, o->h)) o->blur_valid = 0;
}

static long get_card(Window id, Atom a, long def) {
    Atom t; int f; unsigned long n, b; unsigned char *d = NULL; long v = def;
    if (XGetWindowProperty(dpy, id, a, 0, 1, False, XA_CARDINAL, &t, &f, &n, &b, &d) == Success && d) {
        if (n == 1 && f == 32) v = *(long *)d;
        XFree(d);
    }
    return v;
}

static void props(Win *w) {
    w->blur = (int)get_card(w->id, a_blur, 0);
    w->shadow = (int)get_card(w->id, a_shadow, 0);
    w->radius = (int)get_card(w->id, a_radius, 0);
    w->body_y = (int)get_card(w->id, a_body, 0);
}

static void drop_pix(Win *w) {
    if (w->surf) { cairo_surface_destroy(w->surf); w->surf = NULL; }
    if (w->pix) { XFreePixmap(dpy, w->pix); w->pix = 0; }
}

static void drop_old(Win *w) {
    if (w->old_surf) { cairo_surface_destroy(w->old_surf); w->old_surf = NULL; }
    if (w->old_pix) { XFreePixmap(dpy, w->old_pix); w->old_pix = 0; }
    w->hold_until = 0;
}

/* the window is being resized: keep what it showed until the client has drawn the new size */
static void hold_old(Win *w) {
    if (w->old_surf) { drop_pix(w); return; }               /* already holding the oldest good picture: keep that one */
    if (w->surf && w->pix) {
        w->old_surf = w->surf; w->old_pix = w->pix; w->old_w = w->w; w->old_h = w->h;
        w->surf = NULL; w->pix = 0;
        w->hold_until = now_ms() + 150;
    } else drop_pix(w);
}

static void load_shape(Win *w) {
    if (w->shape) { XFree(w->shape); w->shape = NULL; }
    int ord, n = 0, bounding;
    w->nshape = 0; w->shape_valid = 1;
    XShapeQueryExtents(dpy, w->id, &bounding, &(int){0}, &(int){0}, &(unsigned){0}, &(unsigned){0},
                       &(int){0}, &(int){0}, &(int){0}, &(unsigned){0}, &(unsigned){0});
    if (!bounding) return;
    w->shape = XShapeGetRectangles(dpy, w->id, ShapeBounding, &n, &ord);
    w->nshape = n;
}

static void refresh_attrs(Win *w) {
    XWindowAttributes a;
    if (!XGetWindowAttributes(dpy, w->id, &a)) return;
    if (a.width != w->w || a.height != w->h || a.x != w->x || a.y != w->y) { /* geometry may change contents */ }
    w->x = a.x; w->y = a.y; w->w = a.width; w->h = a.height;
    w->visual = a.visual; w->depth = a.depth;
    w->viewable = a.map_state == IsViewable;
}

static void add_win(Window id) {
    if (find(id) || id == overlay || id == mgr) return;
    XWindowAttributes a;
    if (!XGetWindowAttributes(dpy, id, &a) || a.class == InputOnly) return;
    Win *w = calloc(1, sizeof *w);
    w->id = id;
    refresh_attrs(w);
    XSelectInput(dpy, id, PropertyChangeMask);
    XShapeSelectInput(dpy, id, ShapeNotifyMask);
    props(w);
    if (w->viewable) w->damage = XDamageCreate(dpy, id, XDamageReportDeltaRectangles);
    Win **p = &wins;
    while (*p) p = &(*p)->next;
    *p = w;
    dirty_win(w); blur_invalidate_rect(w->x, w->y, w->w, w->h);
}

static void del_win(Window id) {
    for (Win **p = &wins; *p; p = &(*p)->next)
        if ((*p)->id == id) {
            Win *w = *p; *p = w->next;
            drop_pix(w); drop_old(w);
            if (w->damage) XDamageDestroy(dpy, w->damage);
            if (w->shape) XFree(w->shape);
            if (w->blur_surf) cairo_surface_destroy(w->blur_surf);
            if (w->shadow_surf) cairo_surface_destroy(w->shadow_surf);
            dirty_win(w); blur_invalidate_rect(w->x, w->y, w->w, w->h);
            free(w);
            return;
        }
}

/* Re-read the real stacking order from the X server (bottom -> top). Needed when a ConfigureNotify names a sibling we do not
   track (input-only resize handles, the overlay, ...): guessing "top" there let docks jump in front of fullscreen windows. */
static void resync_order(void) {
    Window r, p, *kids = NULL; unsigned n = 0;
    if (!XQueryTree(dpy, DefaultRootWindow(dpy), &r, &p, &kids, &n) || !n) { if (kids) XFree(kids); return; }
    Win **order = calloc(n, sizeof(Win *)); unsigned m = 0;
    for (unsigned i = 0; i < n; i++) { Win *w = find(kids[i]); if (w) order[m++] = w; }   /* look everything up BEFORE relinking */
    XFree(kids);
    if (m) {
        for (unsigned i = 0; i < m; i++) order[i]->next = (i + 1 < m) ? order[i + 1] : NULL;
        wins = order[0];
    }
    free(order);
}

/* Is w really right above `above` in OUR list? The "last sibling seen" alone is not enough: other windows can be raised past it in
   between, and the same ConfigureNotify (w above X) then arrives again for a different real position - the window stayed visually
   behind while the WM and the X server had it on top. */
static int stacked_above(Win *w, Window above) {
    if (above == None) return wins == w;
    Win *s = find(above);
    return s && s->next == w;
}

static void restack(Win *w, Window above) {
    n_restack++;
    if (debug) fprintf(stderr, "restack 0x%lx above 0x%lx\n", (unsigned long)w->id, (unsigned long)above);
    for (Win **p = &wins; *p; p = &(*p)->next) if (*p == w) { *p = w->next; break; }
    if (above == None) { w->next = wins; wins = w; }
    else {
        Win *s = find(above);
        if (!s) { Win **p = &wins; while (*p) p = &(*p)->next; w->next = NULL; *p = w; resync_order(); }
        else { w->next = s->next; s->next = w; }
    }
    dirty_win(w); blur_invalidate_rect(w->x, w->y, w->w, w->h);
}

static cairo_surface_t *win_surface(Win *w) {
    if (!w->viewable || w->w < 1 || w->h < 1) return NULL;
    if (!w->surf) {
        w->pix = XCompositeNameWindowPixmap(dpy, w->id);
        if (!w->pix) return NULL;
        w->surf = cairo_xlib_surface_create(dpy, w->pix, w->visual, w->w, w->h);
    }
    return w->surf;
}

static void rrect(cairo_t *c, double x, double y, double w, double h, double r) {
    if (r > w / 2) r = w / 2;
    if (r > h / 2) r = h / 2;
    cairo_new_sub_path(c);
    cairo_arc(c, x + w - r, y + r, r, -M_PI / 2, 0);
    cairo_arc(c, x + w - r, y + h - r, r, 0, M_PI / 2);
    cairo_arc(c, x + r, y + h - r, r, M_PI / 2, M_PI);
    cairo_arc(c, x + r, y + r, r, M_PI, 1.5 * M_PI);
    cairo_close_path(c);
}

static void shape_path(cairo_t *c, Win *w) {
    if (!w->shape_valid) load_shape(w);
    if (w->nshape > 1 || (w->nshape == 1 && (w->shape[0].width != w->w || w->shape[0].height != w->h))) {
        for (int i = 0; i < w->nshape; i++)
            cairo_rectangle(c, w->x + w->shape[i].x, w->y + w->shape[i].y, w->shape[i].width, w->shape[i].height);
    } else if (w->radius > 0) rrect(c, w->x, w->y, w->w, w->h, w->radius);
    else cairo_rectangle(c, w->x, w->y, w->w, w->h);
}

static void draw_shadow(cairo_t *c, Win *w) {
    const double blur = 26, dy = 10, alpha = 0.34;
    double r = w->radius > 0 ? w->radius : 6;
    if (!w->shadow_surf || w->sh_w != w->w || w->sh_h != w->h || w->sh_r != (int)r) {
        if (w->shadow_surf) cairo_surface_destroy(w->shadow_surf);
        w->shadow_surf = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, w->w + 2 * PAD, w->h + 2 * PAD);
        cairo_t *s = cairo_create(w->shadow_surf);
        for (int i = 0; i < 14; i++) {
            double g = blur * (1 - i / 14.0);
            rrect(s, PAD - g, PAD - g + dy, w->w + 2 * g, w->h + 2 * g, r + g);
            cairo_set_source_rgba(s, 0.08, 0.03, 0.30, alpha / 14 * 1.9);
            cairo_fill(s);
        }
        cairo_destroy(s);
        w->sh_w = w->w; w->sh_h = w->h; w->sh_r = (int)r;
    }
    cairo_save(c);
    cairo_rectangle(c, w->x - PAD, w->y - PAD, w->w + 2 * PAD, w->h + 2 * PAD);
    rrect(c, w->x, w->y, w->w, w->h, r);
    cairo_set_fill_rule(c, CAIRO_FILL_RULE_EVEN_ODD);
    cairo_clip(c);                                  /* never darken the window body itself */
    cairo_set_source_surface(c, w->shadow_surf, w->x - PAD, w->y - PAD);
    cairo_paint(c);
    cairo_restore(c);
}

static cairo_surface_t *scaled(cairo_surface_t *src, int sw, int sh, int dw, int dh, cairo_filter_t f) {
    cairo_surface_t *d = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, dw > 0 ? dw : 1, dh > 0 ? dh : 1);
    cairo_t *c = cairo_create(d);
    cairo_scale(c, (double)dw / sw, (double)dh / sh);
    cairo_set_source_surface(c, src, 0, 0);
    cairo_pattern_set_filter(cairo_get_source(c), f);
    cairo_pattern_set_extend(cairo_get_source(c), CAIRO_EXTEND_PAD);
    cairo_paint(c);
    cairo_destroy(c);
    return d;
}

static void blur_rect(Win *w, int *x, int *y, int *bw, int *bh) {
    int x1 = w->x < 0 ? 0 : w->x, y1 = w->y < 0 ? 0 : w->y;
    int x2 = w->x + w->w > W ? W : w->x + w->w, y2 = w->y + w->h > H ? H : w->y + w->h;
    *x = x1; *y = y1; *bw = x2 - x1; *bh = y2 - y1;
}

/* Build the blurred copy of whatever is currently in the back buffer under w (needs that area fully painted). */
static void blur_compute(Win *w) {
    n_blur++;
    int x, y, bw, bh;
    blur_rect(w, &x, &y, &bw, &bh);
    if (bw < 8 || bh < 8) return;
    int level = w->blur, steps = level >= 3 ? 3 : 2, passes = level >= 3 ? 3 : level == 2 ? 2 : 1;
    /* shrink on the X server (XRender), halving per step, and read back only the small result. Reading the big pixmap back
       (what cairo does when an xlib surface is used as a scaled source) stalls the GPU pipeline on real hardware. */
    cairo_surface_t *src = bb_surf; Pixmap srcpm = 0;
    int cw = bw, ch = bh; double ox = x, oy = y;
    for (int k = 0; k < steps; k++) {
        int nw = (cw + 1) / 2, nh = (ch + 1) / 2;
        if (nw < 1) nw = 1;
        if (nh < 1) nh = 1;
        Pixmap pm = XCreatePixmap(dpy, root, nw, nh, DefaultDepth(dpy, scr));
        cairo_surface_t *ds = cairo_xlib_surface_create(dpy, pm, DefaultVisual(dpy, scr), nw, nh);
        cairo_t *cc = cairo_create(ds);
        cairo_scale(cc, (double)nw / cw, (double)nh / ch);
        cairo_set_source_surface(cc, src, -ox, -oy);
        cairo_pattern_set_filter(cairo_get_source(cc), CAIRO_FILTER_BILINEAR);
        cairo_pattern_set_extend(cairo_get_source(cc), CAIRO_EXTEND_PAD);
        cairo_paint(cc);
        cairo_destroy(cc);
        if (src != bb_surf) { cairo_surface_destroy(src); XFreePixmap(dpy, srcpm); }
        src = ds; srcpm = pm; cw = nw; ch = nh; ox = oy = 0;
    }
    int sw = cw, sh = ch;
    cairo_surface_t *s1 = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, sw, sh);
    cairo_t *c1 = cairo_create(s1);
    cairo_set_source_surface(c1, src, 0, 0);
    cairo_set_operator(c1, CAIRO_OPERATOR_SOURCE);
    cairo_paint(c1);
    cairo_destroy(c1);
    if (src != bb_surf) { cairo_surface_destroy(src); XFreePixmap(dpy, srcpm); }
    for (int k = 0; k < passes; k++) {
        int tw = sw / 2 > 1 ? sw / 2 : 1, th = sh / 2 > 1 ? sh / 2 : 1;
        cairo_surface_t *t = scaled(s1, sw, sh, tw, th, CAIRO_FILTER_BILINEAR);
        cairo_surface_t *u = scaled(t, tw, th, sw, sh, CAIRO_FILTER_BILINEAR);
        cairo_surface_destroy(t); cairo_surface_destroy(s1); s1 = u;
    }
    if (w->blur_surf) cairo_surface_destroy(w->blur_surf);
    w->blur_surf = s1; w->bx = x; w->by = y; w->bw = bw; w->bh = bh; w->blur_valid = 1;
}

static void blur_paint(cairo_t *c, Win *w) {
    if (!w->blur_surf) return;
    int sw = cairo_image_surface_get_width(w->blur_surf), sh = cairo_image_surface_get_height(w->blur_surf);
    cairo_save(c);
    shape_path(c, w);
    cairo_clip(c);
    cairo_translate(c, w->bx, w->by);
    cairo_scale(c, (double)w->bw / sw, (double)w->bh / sh);
    cairo_set_source_surface(c, w->blur_surf, 0, 0);
    cairo_pattern_set_filter(cairo_get_source(c), CAIRO_FILTER_BILINEAR);
    cairo_paint(c);
    cairo_restore(c);
}

/* ------------------------------------------------------------------ vsynced presentation (X Present extension) */
static xcb_connection_t *xc;
static xcb_special_event_t *pev;
static uint32_t present_eid, present_serial;
static int present_on, in_flight;
static double flight_since;
static uint64_t last_msc;
static GC copy_gc;
static long n_present;

static void present_init(void) {
    const char *e = getenv("GLITTERDE_VSYNC");
    if (e && !strcmp(e, "0")) { fprintf(stderr, "glitter-comp: vsync disabled (GLITTERDE_VSYNC=0)\n"); return; }
    xc = XGetXCBConnection(dpy);
    if (!xc) return;
    const xcb_query_extension_reply_t *ext = xcb_get_extension_data(xc, &xcb_present_id);
    if (!ext || !ext->present) { fprintf(stderr, "glitter-comp: no Present extension, painting without vsync\n"); return; }
    xcb_present_query_version_reply_t *v = xcb_present_query_version_reply(xc, xcb_present_query_version(xc, 1, 0), NULL);
    if (!v) return;
    free(v);
    present_eid = xcb_generate_id(xc);
    pev = xcb_register_for_special_xge(xc, &xcb_present_id, present_eid, NULL);
    if (!pev) return;
    xcb_present_select_input(xc, present_eid, overlay, XCB_PRESENT_EVENT_MASK_COMPLETE_NOTIFY);
    xcb_present_notify_msc(xc, overlay, 0, 0, 0, 0);          /* learn the current msc */
    xcb_flush(xc);
    XGCValues gv; gv.graphics_exposures = False;
    copy_gc = XCreateGC(dpy, bb, GCGraphicsExposures, &gv);
    present_on = 1;
    fprintf(stderr, "glitter-comp: vsynced presentation through the Present extension\n");
}

/* drain Present events; returns nothing, updates in_flight / last_msc */
static void present_poll(void) {
    if (!present_on) return;
    xcb_generic_event_t *ge;
    while ((ge = xcb_poll_for_special_event(xc, pev))) {
        xcb_ge_generic_event_t *g = (xcb_ge_generic_event_t *)ge;
        if (g->event_type == XCB_PRESENT_COMPLETE_NOTIFY) {
            xcb_present_complete_notify_event_t *cn = (xcb_present_complete_notify_event_t *)ge;
            if (cn->msc > last_msc) last_msc = cn->msc;
            if (cn->kind == XCB_PRESENT_COMPLETE_KIND_PIXMAP && cn->serial == present_serial) in_flight = 0;
        }
        free(ge);
    }
    if (in_flight && now_ms() - flight_since > 250) in_flight = 0;       /* a lost notification must never freeze the desktop */
}

/* copy the finished rectangle of the back buffer into a small pixmap and let the server put it on the overlay at the next vblank */
static int present_rect(int rx, int ry, int rw, int rh) {
    if (!present_on) return 0;
    Pixmap pm = XCreatePixmap(dpy, root, rw, rh, DefaultDepth(dpy, scr));
    XCopyArea(dpy, bb, pm, copy_gc, rx, ry, rw, rh, 0, 0);
    present_serial++;
    xcb_present_pixmap(xc, overlay, (xcb_pixmap_t)pm, present_serial, XCB_NONE, XCB_NONE, rx, ry, XCB_NONE, XCB_NONE, XCB_NONE,
                       XCB_PRESENT_OPTION_NONE, last_msc + 1, 0, 0, 0, NULL);
    xcb_flush(xc);
    XFreePixmap(dpy, pm);                                    /* the server keeps its own reference until the copy has happened */
    in_flight = 1; flight_since = now_ms(); n_present++;
    return 1;
}

static void paint(void) {
    if (dx2 <= dx1 || dy2 <= dy1) { dirty = 0; return; }
    /* a window whose blur is stale must be repainted whole, because the blur is rebuilt from the layers below it */
    for (int again = 1; again;) {
        again = 0;
        for (Win *w = wins; w; w = w->next) {
            if (!w->viewable || !w->blur || w->blur_valid) continue;
            int x, y, bw, bh;
            blur_rect(w, &x, &y, &bw, &bh);
            if (!overlap(dx1, dy1, dx2 - dx1, dy2 - dy1, x, y, bw, bh)) continue;
            if (x < dx1 || y < dy1 || x + bw > dx2 || y + bh > dy2) { add_dirty(x, y, bw, bh); again = 1; }
        }
    }
    int rx = dx1, ry = dy1, rw = dx2 - dx1, rh = dy2 - dy1;
    cairo_t *c = cairo_create(bb_surf);
    cairo_rectangle(c, rx, ry, rw, rh);
    cairo_clip(c);
    cairo_set_source_rgb(c, 0.09, 0.075, 0.16);
    cairo_paint(c);
    for (Win *w = wins; w; w = w->next) {
        if (!w->viewable) continue;
        int pad = w->shadow ? PAD : 0;
        if (!overlap(rx, ry, rw, rh, w->x - pad, w->y - pad, w->w + 2 * pad, w->h + 2 * pad)) continue;
        cairo_surface_t *s = win_surface(w);
        int held = 0;
        if (w->old_surf) {                                           /* resize hold: show the old picture until the client has redrawn */
            if (now_ms() < w->hold_until) { s = w->old_surf; held = 1; } else drop_old(w);
        }
        if (!s) continue;
        if (w->shadow) draw_shadow(c, w);
        if (w->blur) {
            if (!w->blur_valid) blur_compute(w);
            blur_paint(c, w);
        }
        cairo_save(c);
        if (w->nshape > 1 || !w->shape_valid) { shape_path(c, w); cairo_clip(c); }
        cairo_set_source_surface(c, s, w->x, w->y);
        if (held) {                                                  /* never paint outside the part the old picture covers */
            cairo_new_path(c);
            cairo_rectangle(c, w->x, w->y, w->old_w < w->w ? w->old_w : w->w, w->old_h < w->h ? w->old_h : w->h);
            cairo_clip(c);
        }
        cairo_paint(c);
        cairo_restore(c);
    }
    cairo_destroy(c);
    cairo_surface_flush(bb_surf);
    if (!present_rect(rx, ry, rw, rh)) {
        cairo_t *o = cairo_create(ov_surf);
        cairo_rectangle(o, rx, ry, rw, rh);
        cairo_clip(o);
        cairo_set_operator(o, CAIRO_OPERATOR_SOURCE);
        cairo_set_source_surface(o, bb_surf, 0, 0);
        cairo_paint(o);
        cairo_destroy(o);
        cairo_surface_flush(ov_surf);
    }
    XFlush(dpy);
    dx1 = dy1 = dx2 = dy2 = 0;
    dirty = 0;
}

static double now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1000.0 + t.tv_nsec / 1e6; }

static void handle(XEvent *e) {
    Win *w;
    if (e->type == damage_ev + XDamageNotify) {
        XDamageNotifyEvent *d = (XDamageNotifyEvent *)e;
        n_damage++;
        w = find(d->drawable);
        XDamageSubtract(dpy, d->damage, None, None);         /* re-arm; asynchronous (the old code fetched the region: 3 round trips per event) */
        if (!w) return;
        if (w->old_surf && d->area.y + d->area.height > w->body_y) { drop_old(w); w->blur_valid = 0; add_dirty(w->x, w->y, w->w, w->h); }
        add_dirty(w->x + d->area.x, w->y + d->area.y, d->area.width, d->area.height);
        blur_invalidate_above(w, w->x + d->area.x, w->y + d->area.y, d->area.width, d->area.height);
        return;
    }
    if (e->type == shape_ev + ShapeNotify) {
        if ((w = find(((XShapeEvent *)e)->window))) { w->shape_valid = 0; drop_pix(w); drop_old(w); dirty_win(w); blur_invalidate_rect(w->x, w->y, w->w, w->h); }
        return;
    }
    switch (e->type) {
    case CreateNotify:
        if (e->xcreatewindow.parent == root) add_win(e->xcreatewindow.window);
        break;
    case DestroyNotify: del_win(e->xdestroywindow.window); break;
    case ReparentNotify:
        if (e->xreparent.parent == root) add_win(e->xreparent.window); else del_win(e->xreparent.window);
        break;
    case MapNotify:
        if ((w = find(e->xmap.window))) {
            refresh_attrs(w); drop_pix(w); drop_old(w);
            if (!w->damage) w->damage = XDamageCreate(dpy, w->id, XDamageReportDeltaRectangles);
            w->viewable = 1; w->blur_valid = 0; dirty_win(w); blur_invalidate_rect(w->x, w->y, w->w, w->h);
        }
        break;
    case UnmapNotify:
        if ((w = find(e->xunmap.window))) {
            w->viewable = 0; drop_pix(w); drop_old(w);
            if (w->damage) { XDamageDestroy(dpy, w->damage); w->damage = 0; }
            dirty_win(w); blur_invalidate_rect(w->x, w->y, w->w, w->h);
        }
        break;
    case ConfigureNotify:
        if ((w = find(e->xconfigure.window))) {
            XConfigureEvent *c = &e->xconfigure;
            int moved = w->x != c->x || w->y != c->y, resized = w->w != c->width || w->h != c->height;
            int restacked = !w->has_above || w->above_id != c->above || !stacked_above(w, c->above);
            w->has_above = 1; w->above_id = c->above;
            if (!moved && !resized && !restacked) break;          /* the WM re-sent an unchanged configuration */
            int ox = w->x, oy = w->y, ow = w->w, oh = w->h;
            dirty_win(w);                                        /* old position */
            w->x = c->x; w->y = c->y; w->w = c->width; w->h = c->height;
            if (resized) { int nw_ = w->w, nh_ = w->h; w->w = ow; w->h = oh; hold_old(w); w->w = nw_; w->h = nh_; w->shape_valid = 0; }
            if (moved || resized) {
                w->blur_valid = 0;                               /* what is behind a glass window changed with it */
                blur_invalidate_rect(ox, oy, ow, oh);            /* uncovered area: glass windows there see something new */
            }
            if (restacked) restack(w, c->above);                 /* also marks the new position */
            else { dirty_win(w); blur_invalidate_rect(w->x, w->y, w->w, w->h); }
        }
        break;
    case CirculateNotify:
        if ((w = find(e->xcirculate.window))) { dirty_win(w); blur_invalidate_rect(w->x, w->y, w->w, w->h); }
        break;
    case PropertyNotify:
        if ((w = find(e->xproperty.window))) { props(w); w->blur_valid = 0; w->sh_w = -1; dirty_win(w); }
        break;
    default: break;
    }
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; i++) if (!strcmp(argv[i], "-d")) debug = 1;
    if (!(dpy = XOpenDisplay(NULL))) { fprintf(stderr, "glitter-comp: cannot open display\n"); return 1; }
    XSetErrorHandler(on_error);
    signal(SIGTERM, on_term); signal(SIGINT, on_term); signal(SIGUSR1, on_usr1);
    scr = DefaultScreen(dpy); root = RootWindow(dpy, scr);
    W = DisplayWidth(dpy, scr); H = DisplayHeight(dpy, scr);
    int ev, er, maj = 0, min = 0;
    if (!XCompositeQueryExtension(dpy, &ev, &er) || !XDamageQueryExtension(dpy, &damage_ev, &er) ||
        !XFixesQueryExtension(dpy, &ev, &er) || !XShapeQueryExtension(dpy, &shape_ev, &er)) {
        fprintf(stderr, "glitter-comp: X server lacks Composite/Damage/XFixes/Shape (Xephyr needs +extension Composite)\n");
        return 2;
    }
    (void)maj; (void)min;
    a_blur = XInternAtom(dpy, "_GLITTER_BLUR", False);
    a_shadow = XInternAtom(dpy, "_GLITTER_SHADOW", False);
    a_radius = XInternAtom(dpy, "_GLITTER_RADIUS", False);
    a_body = XInternAtom(dpy, "_GLITTER_BODY_Y", False);
    char sel[32]; snprintf(sel, sizeof sel, "_NET_WM_CM_S%d", scr);
    Atom cm = XInternAtom(dpy, sel, False);
    if (XGetSelectionOwner(dpy, cm) != None) { fprintf(stderr, "glitter-comp: another compositor is running\n"); return 3; }
    mgr = XCreateSimpleWindow(dpy, root, -10, -10, 1, 1, 0, 0, 0);
    XSetSelectionOwner(dpy, cm, mgr, CurrentTime);

    XSelectInput(dpy, root, SubstructureNotifyMask | StructureNotifyMask | PropertyChangeMask);
    XCompositeRedirectSubwindows(dpy, root, CompositeRedirectManual);
    overlay = XCompositeGetOverlayWindow(dpy, root);
    XserverRegion empty = XFixesCreateRegion(dpy, NULL, 0);
    XFixesSetWindowShapeRegion(dpy, overlay, ShapeInput, 0, 0, empty);   /* clicks pass through */
    XFixesDestroyRegion(dpy, empty);

    bb = XCreatePixmap(dpy, root, W, H, DefaultDepth(dpy, scr));
    bb_surf = cairo_xlib_surface_create(dpy, bb, DefaultVisual(dpy, scr), W, H);
    ov_surf = cairo_xlib_surface_create(dpy, overlay, DefaultVisual(dpy, scr), W, H);

    present_init();
    Window r, p, *kids; unsigned n;
    XGrabServer(dpy);
    if (XQueryTree(dpy, root, &r, &p, &kids, &n)) {
        for (unsigned i = 0; i < n; i++) add_win(kids[i]);
        XFree(kids);
    }
    XUngrabServer(dpy);
    fprintf(stderr, "glitter-comp: compositing %dx%d\n", W, H);

    double last = 0, pace = 14, ms_paint = 0, px_paint = 0, stat_t = 0; int n_paint = 0;
    int stats = getenv("GLITTERDE_COMP_STATS") != NULL;
    add_dirty(0, 0, W, H);
    while (running) {
        while (XPending(dpy)) { XEvent e; XNextEvent(dpy, &e); handle(&e); }
        if (dump_stats) {
            dump_stats = 0;
            fprintf(stderr, "glitter-comp: [now] paints %d avg %.1f ms | restacks %ld blur-rebuilds %ld damage-ev %ld\n", n_paint,
                    n_paint ? ms_paint / n_paint : 0.0, n_restack, n_blur, n_damage);
            n_paint = 0; ms_paint = px_paint = 0; n_restack = n_blur = n_damage = 0;
        }
        double t = now_ms();
        present_poll();
        for (Win *hw = wins; hw; hw = hw->next)                 /* resize hold ran out: show whatever the window has now */
            if (hw->old_surf && t >= hw->hold_until) { drop_old(hw); hw->blur_valid = 0; add_dirty(hw->x, hw->y, hw->w, hw->h); }
        /* adaptive pacing: never queue paints faster than the X server can finish them (slow software Xephyr),
           otherwise the backlog delays input events and everything feels laggy */
        if (dirty && !in_flight && t - last >= pace) {
            double pw = (dx2 - dx1) * (double)(dy2 - dy1);
            last = t; paint();
            if (!present_on) XSync(dpy, False);               /* without Present, never queue paints faster than the server finishes them */
            double cost = now_ms() - t;
            pace = present_on ? (cost < 4 ? 4 : cost) : (cost * 1.5 < 14 ? 14 : (cost * 1.5 > 100 ? 100 : cost * 1.5));
            if (stats) {
                n_paint++; ms_paint += cost; px_paint += pw;
                if (t - stat_t > 2000) {
                    fprintf(stderr, "glitter-comp: %d paints/2s, avg %.1f ms, avg %.0f kpx, pace %.0f ms%s | restacks %ld blur-rebuilds %ld damage-ev %ld\n", n_paint,
                            ms_paint / n_paint, px_paint / n_paint / 1000, pace, present_on ? " (vsync)" : "", n_restack, n_blur, n_damage);
                    n_restack = n_blur = n_damage = 0;
                    n_paint = 0; ms_paint = px_paint = 0; stat_t = t;
                }
            }
            continue;
        }
        fd_set fds; FD_ZERO(&fds); FD_SET(ConnectionNumber(dpy), &fds);
        struct timeval tv = { 0, (dirty || in_flight) ? 2000 : 500000 };
        select(ConnectionNumber(dpy) + 1, &fds, NULL, NULL, &tv);
    }
    XCompositeReleaseOverlayWindow(dpy, root);
    XCloseDisplay(dpy);
    return 0;
}

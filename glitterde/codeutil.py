"""Pure-Python editing logic for SparkCode (no GTK): undo history, find/replace, indentation, comment toggling, fuzzy file matching.

Kept separate from the window code so it can be tested without a display.
"""
import os
import re
import time


# ------------------------------------------------------------------------------------------------------------------------ undo
class UndoStack:
    """Linear undo / redo of insert ('i') and delete ('d') operations given as (kind, offset, text).

    Typing and backspacing merge into word-sized steps; begin()/end() make everything between them one step. is_clean() is True again
    when undo brings the document back to the state that mark_clean() recorded (the "modified" dot goes away).
    """
    LIMIT = 3000

    def __init__(self):
        self.reset()

    def reset(self):
        self.undo, self.redo = [], []
        self._n = 0
        self.clean_id = 0
        self.depth = 0
        self.busy = False
        self._grp = None

    def _top_id(self):
        return self.undo[-1]["id"] if self.undo else 0

    def mark_clean(self):
        self.clean_id = self._top_id()
        if self.undo:
            self.undo[-1]["merge"] = False          # the next keystroke starts a new step instead of changing the saved one

    def is_clean(self):
        return self._top_id() == self.clean_id

    def _push(self, before):
        self._n += 1
        e = {"id": self._n, "ops": [], "before": before, "after": before, "t": time.monotonic(), "merge": True}
        self.undo.append(e)
        if len(self.undo) > self.LIMIT:
            del self.undo[:len(self.undo) - self.LIMIT]
        return e

    def begin(self, cursor):
        if self.depth == 0:
            self._grp = None
            self._cursor0 = cursor
        self.depth += 1

    def end(self):
        self.depth = max(0, self.depth - 1)
        if self.depth == 0 and self._grp is not None:
            self._grp["merge"] = False
            self._grp = None

    @staticmethod
    def _kind(ch):
        return 0 if ch.isspace() else (1 if (ch.isalnum() or ch == "_") else 2)

    def _can_merge(self, top, kind, off, text):
        if not top["merge"] or len(top["ops"]) != 1 or time.monotonic() - top["t"] > 1.5 or "\n" in text or len(text) != 1:
            return False
        k, o, t = top["ops"][0]
        if k != kind or "\n" in t:
            return False
        if kind == "i":
            return off == o + len(t) and self._kind(text) == self._kind(t[-1])
        return off + 1 == o or off == o                      # backspace / delete key

    def record(self, kind, off, text, before, after):
        if self.busy or not text:
            return
        self.redo.clear()
        if self.depth > 0:
            if self._grp is None:
                self._grp = self._push(self._cursor0)
            self._grp["ops"].append((kind, off, text)); self._grp["after"] = after
            return
        top = self.undo[-1] if self.undo else None
        if top is not None and self._can_merge(top, kind, off, text):
            k, o, t = top["ops"][0]
            if kind == "i":
                top["ops"][0] = (k, o, t + text)
            elif off + 1 == o:
                top["ops"][0] = (k, off, text + t)
            else:
                top["ops"][0] = (k, o, t + text)
            top["after"], top["t"] = after, time.monotonic()
            return
        e = self._push(before)
        e["ops"].append((kind, off, text)); e["after"] = after

    def undo_step(self, apply):
        """Undo one step; apply(kind, offset, text) must perform the operation on the buffer. Returns the cursor offset, or None."""
        if not self.undo:
            return None
        e = self.undo.pop(); self.redo.append(e)
        self.busy = True
        try:
            for kind, off, text in reversed(e["ops"]):
                apply("d" if kind == "i" else "i", off, text)
        finally:
            self.busy = False
        return e["before"]

    def redo_step(self, apply):
        if not self.redo:
            return None
        e = self.redo.pop(); self.undo.append(e)
        self.busy = True
        try:
            for kind, off, text in e["ops"]:
                apply(kind, off, text)
        finally:
            self.busy = False
        return e["after"]


# ------------------------------------------------------------------------------------------------------------------------ find
def compile_pattern(pat, case=False, regex=False, word=False):
    """Compiled regex for the find bar, or None for an empty / invalid pattern (the second value is the error text)."""
    if not pat:
        return None, ""
    try:
        p = pat if regex else re.escape(pat)
        if word:
            p = r"\b(?:%s)\b" % p
        return re.compile(p, re.MULTILINE | (0 if case else re.IGNORECASE)), ""
    except re.error as e:
        return None, str(e)


def find_all(rx, text, limit=20000):
    out = []
    for m in rx.finditer(text):
        if m.end() == m.start():
            continue
        out.append((m.start(), m.end()))
        if len(out) >= limit:
            break
    return out


def expand(rx, text, span, repl, regex):
    """The replacement text for one match (\\1 / \\g<name> back-references only in regex mode)."""
    if not regex:
        return repl
    m = rx.match(text, span[0], span[1])
    if m is None:
        return repl
    try:
        return m.expand(repl)
    except (re.error, IndexError):
        return repl


# ------------------------------------------------------------------------------------------------------------------------ indentation
def detect_indent(text, default=4):
    """('tabs', 0) or ('spaces', width) from the way the first 600 indented lines are indented."""
    tabs = spaces = 0
    deltas = {}
    prev = 0
    for ln in text.split("\n", 2000)[:2000]:
        if not ln.strip():
            continue
        if ln[0] == "\t":
            tabs += 1
            continue
        n = len(ln) - len(ln.lstrip(" "))
        if n:
            spaces += 1
            d = abs(n - prev)
            if d in (2, 3, 4, 8):
                deltas[d] = deltas.get(d, 0) + 1
        prev = n
        if spaces > 600:
            break
    if tabs > spaces and tabs > 2:
        return "tabs", 0
    if deltas:
        return "spaces", max(deltas.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return "spaces", default


def indent_lines(lines, unit):
    return [(unit + l) if l.strip() else l for l in lines]


def outdent_lines(lines, unit, width):
    out = []
    for l in lines:
        if l.startswith("\t"):
            out.append(l[1:])
        elif l.startswith(unit) and unit.strip() == "":
            out.append(l[len(unit):])
        else:
            n = min(width, len(l) - len(l.lstrip(" ")))
            out.append(l[n:])
    return out


def toggle_comment(lines, line_prefix=None, block=None):
    """Comment or uncomment the lines: with `line_prefix` ('#', '//'), else wrapping each line in `block` ('<!--', '-->')."""
    body = [l for l in lines if l.strip()]
    if not body:
        return list(lines)
    if line_prefix:
        if all(l.lstrip().startswith(line_prefix) for l in body):
            out = []
            for l in lines:
                i = len(l) - len(l.lstrip())
                if l.strip() and l[i:].startswith(line_prefix):
                    rest = l[i + len(line_prefix):]
                    out.append(l[:i] + (rest[1:] if rest.startswith(" ") else rest))
                else:
                    out.append(l)
            return out
        col = min(len(l) - len(l.lstrip(" \t")) for l in body)
        return [l[:col] + line_prefix + " " + l[col:] if l.strip() else l for l in lines]
    if block:
        a, b = block
        if all(l.strip().startswith(a) and l.strip().endswith(b) and len(l.strip()) >= len(a) + len(b) for l in body):
            out = []
            for l in lines:
                s = l.strip()
                if s and s.startswith(a) and s.endswith(b):
                    i = len(l) - len(l.lstrip())
                    inner = s[len(a):len(s) - len(b)]
                    inner = inner[1:] if inner.startswith(" ") else inner
                    inner = inner[:-1] if inner.endswith(" ") else inner
                    out.append(l[:i] + inner)
                else:
                    out.append(l)
            return out
        return [(l[:len(l) - len(l.lstrip())] + a + " " + l.strip() + " " + b) if l.strip() else l for l in lines]
    return list(lines)


# ------------------------------------------------------------------------------------------------------------------------ files
SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".cache", ".venv",
             "venv", ".tox", ".idea", ".gradle", "target", "dist", "build", ".eggs"}


def list_files(root, limit=20000):
    """Relative paths of the files below root (for quick open); skips VCS / cache / build directories and dot-directories."""
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(files):
            if f.endswith((".pyc", ".o", ".so", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".gz", ".xz", ".ico", ".cur", ".ani", ".pdf", ".woff", ".woff2", ".ttf")):
                continue
            out.append(os.path.relpath(os.path.join(dirpath, f), root))
            if len(out) >= limit:
                return out
    return out


def fuzzy_score(query, path):
    """Score for a sub-sequence match of `query` in `path` (higher is better), None when it does not match."""
    q = query.lower().replace(" ", "")
    p = path.lower()
    if not q:
        return 0
    base = p.rfind("/") + 1
    score, pos, prev = 0, 0, -2
    for ch in q:
        i = p.find(ch, pos)
        if i < 0:
            return None
        s = 1
        if i == prev + 1:
            s += 4                                           # consecutive
        if i == 0 or p[i - 1] in "/._- ":
            s += 3                                           # start of a word
        if i >= base:
            s += 2                                           # in the file name rather than the directory
        score += s
        prev, pos = i, i + 1
    if q in p[base:]:
        score += 12                                          # the whole query inside the file name
    return score - len(p) * 0.02


def fuzzy_filter(query, paths, limit=60):
    scored = []
    for p in paths:
        s = fuzzy_score(query, p)
        if s is not None:
            scored.append((-s, len(p), p))
    scored.sort()
    return [p for _, _, p in scored[:limit]]


# ------------------------------------------------------------------------------------------------------------------------ decoding
def decode(data):
    """(text, encoding, bom, eol) from raw bytes; text always uses '\\n'. Raises ValueError for binary data."""
    if b"\x00" in data[:8192] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ValueError("binary")
    bom = False
    if data.startswith(b"\xef\xbb\xbf"):
        data, bom = data[3:], True
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        enc, text = "utf-16", data.decode("utf-16", "replace")
    else:
        try:
            enc, text = "utf-8", data.decode("utf-8")
        except UnicodeDecodeError:
            enc, text = "latin-1", data.decode("latin-1")
    eol = "\r\n" if "\r\n" in text and text.count("\r\n") >= text.count("\n") / 2 else ("\r" if "\r" in text and "\n" not in text else "\n")
    if eol != "\n":
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, enc, bom, eol


def encode(text, enc="utf-8", bom=False, eol="\n"):
    if eol != "\n":
        text = text.replace("\n", eol)
    data = text.encode("utf-16" if enc == "utf-16" else enc, "replace" if enc == "latin-1" else "strict")
    return (b"\xef\xbb\xbf" + data) if bom and enc == "utf-8" else data

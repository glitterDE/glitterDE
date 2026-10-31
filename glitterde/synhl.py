"""Syntax highlighting engine for SparkCode (no GTK, no third-party dependencies).

A language is a list of rules; all rules of a language are compiled into ONE master regular expression, so a document is tokenised in a
single left-to-right pass (which is what makes multi-line strings and block comments work). tokenize() yields (start, end, kind) with
character offsets into the text; the editor maps each kind to a theme colour.

Kinds: comment string number keyword builtin type function constant decorator operator tag attr escape heading link
       added removed meta variable
"""
import os
import re

KINDS = ("comment", "string", "number", "keyword", "builtin", "type", "function", "constant", "decorator", "operator",
         "tag", "attr", "escape", "heading", "link", "added", "removed", "meta", "variable")


def words(s):
    """r'\\b(?:a|b|c)\\b' from 'a b c' (longest first, so 'elif' wins over 'el')."""
    return r"\b(?:" + "|".join(sorted(s.split(), key=lambda w: (-len(w), w))) + r")\b"


class Lang:
    def __init__(self, name, exts=(), files=(), shebang=None, rules=(), line_comment=None, block_comment=None,
                 indent=4, tabs=False, flags=0, pairs=True):
        self.name, self.exts, self.files = name, tuple(exts), tuple(files)
        self.shebang = re.compile(shebang) if shebang else None
        self.line_comment, self.block_comment = line_comment, block_comment
        self.indent, self.tabs, self.pairs = indent, tabs, pairs
        self._rules = [(k, p, subs) for k, p, subs in ((r + (None,))[:3] for r in rules)]
        self._flags = flags
        self._rx = None
        self._kind = {}

    def compile(self):
        if self._rx is not None:
            return self._rx
        parts = []
        for i, (kind, pat, subs) in enumerate(self._rules):
            pat = pat.replace("@@", "r%d_" % i)                      # inner groups are written (?P<@@name>...) and made unique here
            parts.append("(?P<r%d>%s)" % (i, pat))
            self._kind["r%d" % i] = (kind, {("r%d_%s" % (i, g)): k for g, k in (subs or {}).items()})
        self._rx = re.compile("|".join(parts), self._flags | re.MULTILINE)
        return self._rx

    def tokenize(self, text):
        rx = self.compile()
        kinds = self._kind
        for m in rx.finditer(text):
            kind, subs = kinds[m.lastgroup]
            if subs:
                pos, end = m.start(), m.end()
                for g, k in subs.items():
                    s, e = m.span(g)
                    if s >= 0 and e > s:
                        if kind and s > pos:
                            yield pos, s, kind
                        yield s, e, k
                        pos = e
                if kind and pos < end:
                    yield pos, end, kind
            elif kind:
                yield m.start(), m.end(), kind


# ---------------------------------------------------------------------------------------------------------------- shared pieces
NUM_C = r"\b(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d+)?)[uUlLfFjJ]*\b"
OPS = r"[-+*/%=<>!&|^~?:]+"
DQ = r'"(?:\\.|[^"\\\n])*"?'
SQ = r"'(?:\\.|[^'\\\n])*'?"
SLASH_COMMENT = ("comment", r"//[^\n]*")
BLOCK_COMMENT = ("comment", r"/\*[\s\S]*?(?:\*/|\Z)")
HASH_COMMENT = ("comment", r"#[^\n]*")

PY_KW = ("False None True and as assert async await break class continue def del elif else except finally for from global if import "
         "in is lambda nonlocal not or pass raise return try while with yield match case")
PY_BUILTIN = ("abs all any ascii bin bool breakpoint bytearray bytes callable chr classmethod compile complex delattr dict dir divmod "
              "enumerate eval exec filter float format frozenset getattr globals hasattr hash help hex id input int isinstance "
              "issubclass iter len list locals map max memoryview min next object oct open ord pow print property range repr reversed "
              "round set setattr slice sorted staticmethod str sum super tuple type vars zip self cls "
              "Exception ValueError TypeError KeyError IndexError OSError RuntimeError AttributeError ImportError StopIteration "
              "NotImplementedError FileNotFoundError PermissionError KeyboardInterrupt SystemExit")

C_KW = ("auto break case const continue default do else enum extern for goto if inline register restrict return sizeof static struct "
        "switch typedef union volatile while _Bool _Complex")
C_TYPES = ("void char short int long float double signed unsigned size_t ssize_t uint8_t uint16_t uint32_t uint64_t int8_t int16_t "
           "int32_t int64_t uintptr_t intptr_t ptrdiff_t bool FILE wchar_t")
CPP_KW = ("alignas alignof and and_eq asm bitand bitor catch class compl concept consteval constexpr constinit const_cast co_await "
          "co_return co_yield decltype delete dynamic_cast explicit export final friend mutable namespace new noexcept not not_eq "
          "operator or or_eq override private protected public reinterpret_cast requires static_assert static_cast template this "
          "thread_local throw try typeid typename using virtual xor xor_eq")

JS_KW = ("as async await break case catch class const continue debugger default delete do else export extends finally for from function "
         "get if import in instanceof let new of return set static super switch this throw try typeof var void while with yield "
         "enum implements interface package private protected public readonly abstract declare namespace type keyof infer is satisfies")
JS_CONST = "true false null undefined NaN Infinity"
JS_BUILTIN = ("Array Boolean Date Error JSON Map Math Number Object Promise Proxy RegExp Set String Symbol WeakMap WeakSet console "
              "document window globalThis process require module exports parseInt parseFloat isNaN fetch setTimeout setInterval "
              "string number boolean any unknown never object bigint")

RUST_KW = ("as async await break const continue crate dyn else enum extern fn for if impl in let loop match mod move mut pub ref return "
           "self Self static struct super trait type unsafe use where while union macro_rules")
RUST_TYPES = "i8 i16 i32 i64 i128 isize u8 u16 u32 u64 u128 usize f32 f64 bool char str String Vec Option Result Box Rc Arc HashMap"

GO_KW = ("break case chan const continue default defer else fallthrough for func go goto if import interface map package range return "
         "select struct switch type var")
GO_TYPES = ("bool byte complex64 complex128 error float32 float64 int int8 int16 int32 int64 rune string uint uint8 uint16 uint32 "
            "uint64 uintptr any comparable")

JAVA_KW = ("abstract assert break case catch class continue default do else enum extends final finally for if implements import "
           "instanceof interface native new package private protected public return static strictfp super switch synchronized this "
           "throw throws transient try var void volatile while record sealed permits yield")
JAVA_TYPES = "boolean byte char double float int long short String Integer Long Double Boolean Object List Map Set Optional"

SH_KW = ("if then else elif fi for while until do done case esac in function select time coproc return break continue exit local "
         "export readonly declare typeset unset shift source alias")
SH_BUILTIN = ("echo printf read cd pwd test eval exec trap set ls cat grep sed awk find sort uniq head tail cut tr xargs mkdir rm cp mv "
               "chmod chown ln tar curl wget git make sudo apt dnf pacman pip python python3 true false")

SQL_KW = ("select from where and or not null is in as join inner outer left right full cross on group by order having limit offset "
          "insert into values update set delete create alter drop table index view database schema primary key foreign references "
          "unique default check constraint distinct union all case when then else end exists between like ilike asc desc begin "
          "commit rollback transaction with returning if cascade")
SQL_TYPES = ("int integer bigint smallint tinyint serial text varchar char boolean bool date time timestamp timestamptz datetime "
             "float double real decimal numeric blob json jsonb uuid")

LUA_KW = "and break do else elseif end false for function goto if in local nil not or repeat return then true until while"
LUA_BUILTIN = ("assert collectgarbage dofile error getmetatable ipairs load loadfile next pairs pcall print rawequal rawget rawlen "
               "rawset require select setmetatable tonumber tostring type xpcall string table math io os coroutine debug utf8 self")

# a regex literal may only start where an expression may start (after an operator / opening bracket / return ...), otherwise '/' divides
JS_REGEX = (None, r"(?:^|(?<=[=(:,\[!&|?{};+*%<>~^-])|(?<=return)|(?<=typeof))[ \t]*(?P<@@r>/(?![/*])(?:\\.|\[(?:\\.|[^\]\\\n])*\]|[^/\\\[\n])+/[dgimsuvy]*)",
            {"r": "string"})
CSS_UNITS = r"(?:px|em|rem|%|vh|vw|vmin|vmax|pt|pc|cm|mm|in|ch|ex|s|ms|deg|rad|turn|fr|dpi|dppx)?"

LANGS = [
    Lang("Python", exts=("py", "pyw", "pyi", "pyx", "gyp"), files=("SConstruct", "SConscript", "wscript"), shebang=r"^#!.*\bpython",
         line_comment="#", indent=4, rules=[
             ("comment", r"#[^\n]*"),
             ("string", r"(?i:[rbuf]{0,2})(?:\"\"\"[\s\S]*?(?:\"\"\"|\Z)|'''[\s\S]*?(?:'''|\Z))"),
             ("string", r"(?i:[rbuf]{0,2})(?:" + DQ + "|" + SQ + ")"),
             ("decorator", r"^[ \t]*@[\w.]+"),
             ("keyword", r"\b(?:def|class)\b[ \t]+(?P<@@n>\w+)", {"n": "function"}),
             ("constant", r"\b(?:True|False|None|Ellipsis|NotImplemented|__\w+__)\b"),
             ("keyword", words(PY_KW)),
             ("builtin", words(PY_BUILTIN)),
             ("function", r"\b[A-Za-z_]\w*(?=\()"),
             ("type", r"\b[A-Z][A-Za-z0-9]*[a-z]\w*\b"),
             ("number", NUM_C),
             ("operator", r"[-+*/%=<>!&|^~@]+"),
         ]),
    Lang("C", exts=("c", "h"), line_comment="//", block_comment=("/*", "*/"), indent=4, rules=[
        BLOCK_COMMENT, SLASH_COMMENT,
        ("meta", r"^[ \t]*#[ \t]*\w+"),
        ("string", r"<[\w./+-]+\.h>"),
        ("string", r"[LuU]?" + DQ), ("string", r"[LuU]?" + SQ),
        ("constant", r"\b(?:NULL|true|false|EOF|stdin|stdout|stderr)\b|\b[A-Z][A-Z0-9_]{2,}\b"),
        ("keyword", words(C_KW)), ("type", words(C_TYPES)),
        ("function", r"\b[A-Za-z_]\w*(?=\s*\()"),
        ("type", r"\b\w+_t\b"),
        ("number", NUM_C), ("operator", OPS),
    ]),
    Lang("C++", exts=("cpp", "cc", "cxx", "c++", "hpp", "hh", "hxx", "h++", "ipp", "tpp", "ino"), line_comment="//",
         block_comment=("/*", "*/"), indent=4, rules=[
             BLOCK_COMMENT, SLASH_COMMENT,
             ("meta", r"^[ \t]*#[ \t]*\w+"),
             ("string", r"<[\w./+-]+>(?=[ \t]*$)"),
             ("string", r"(?:u8|[LuU])?R\"(?P<@@d>[^()\s]{0,16})\([\s\S]*?\)(?P=@@d)\""),
             ("string", r"[LuU]?" + DQ), ("string", r"[LuU]?" + SQ),
             ("constant", r"\b(?:NULL|nullptr|true|false)\b|\b[A-Z][A-Z0-9_]{2,}\b"),
             ("keyword", words(C_KW + " " + CPP_KW)), ("type", words(C_TYPES + " string vector map set unique_ptr shared_ptr auto")),
             ("function", r"\b[A-Za-z_]\w*(?=\s*[(<])"),
             ("type", r"\b[A-Z][A-Za-z0-9]*[a-z]\w*\b|\b\w+_t\b"),
             ("number", NUM_C), ("operator", OPS),
         ]),
    Lang("JavaScript", exts=("js", "mjs", "cjs", "jsx"), shebang=r"^#!.*\bnode", line_comment="//", block_comment=("/*", "*/"),
         indent=2, rules=[
             BLOCK_COMMENT, SLASH_COMMENT,
             ("string", r"`(?:\\[\s\S]|[^`\\])*`?"),
             ("string", DQ), ("string", SQ),
             JS_REGEX,
             ("keyword", r"\b(?:function)\b[ \t]*\*?[ \t]*(?P<@@n>[A-Za-z_$][\w$]*)", {"n": "function"}),
             ("keyword", r"\b(?:class)\b[ \t]+(?P<@@n>[A-Za-z_$][\w$]*)", {"n": "type"}),
             ("constant", words(JS_CONST)), ("keyword", words(JS_KW)), ("builtin", words(JS_BUILTIN)),
             ("function", r"(?<![\w$])[A-Za-z_$][\w$]*(?=\s*\()"),
             ("type", r"\b[A-Z][A-Za-z0-9]*[a-z]\w*\b"),
             ("number", NUM_C + r"|\b\d[\d_]*n\b"), ("operator", r"=>|[-+*/%=<>!&|^~?:]+"),
         ]),
    Lang("TypeScript", exts=("ts", "tsx", "mts", "cts"), line_comment="//", block_comment=("/*", "*/"), indent=2, rules=[
        BLOCK_COMMENT, SLASH_COMMENT,
        ("string", r"`(?:\\[\s\S]|[^`\\])*`?"), ("string", DQ), ("string", SQ),
        ("decorator", r"@[A-Za-z_$][\w$.]*"),
        JS_REGEX,
        ("keyword", r"\b(?:function)\b[ \t]*\*?[ \t]*(?P<@@n>[A-Za-z_$][\w$]*)", {"n": "function"}),
        ("keyword", r"\b(?:class|interface|type|enum)\b[ \t]+(?P<@@n>[A-Za-z_$][\w$]*)", {"n": "type"}),
        ("constant", words(JS_CONST)), ("keyword", words(JS_KW)), ("builtin", words(JS_BUILTIN)),
        ("function", r"(?<![\w$])[A-Za-z_$][\w$]*(?=\s*[(<])"),
        ("type", r"\b[A-Z][A-Za-z0-9]*[a-z]\w*\b"),
        ("number", NUM_C + r"|\b\d[\d_]*n\b"), ("operator", r"=>|[-+*/%=<>!&|^~?:]+"),
    ]),
    Lang("JSON", exts=("json", "jsonc", "json5", "webmanifest", "geojson", "ipynb", "code-workspace"), files=(".eslintrc", ".babelrc"),
         indent=2, pairs=True, rules=[
             SLASH_COMMENT, BLOCK_COMMENT,
             ("attr", r"\"(?:\\.|[^\"\\\n])*\"(?=\s*:)"),
             ("string", DQ),
             ("constant", r"\b(?:true|false|null)\b"),
             ("number", r"-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"),
         ]),
    Lang("HTML", exts=("html", "htm", "xhtml", "vue", "svelte", "njk", "jinja", "j2", "erb", "ejs", "hbs"), indent=2,
         block_comment=("<!--", "-->"), rules=[
             ("comment", r"<!--[\s\S]*?(?:-->|\Z)"),
             ("meta", r"<![A-Za-z][^>]*>|<\?[\s\S]*?(?:\?>|\Z)"),
             ("tag", r"</?(?P<@@n>[A-Za-z][\w:.-]*)", {"n": "tag"}),
             ("tag", r"/?>"),
             ("attr", r"(?<=[\s\"'])[A-Za-z_:@#.][\w:.@#-]*(?=\s*=)"),
             ("string", r"\"[^\"]*\"?|'[^']*'?"),
             ("escape", r"&(?:#\d+|#x[0-9a-fA-F]+|\w+);"),
             ("keyword", r"\{\{[\s\S]*?(?:\}\}|\Z)|\{%[\s\S]*?(?:%\}|\Z)"),
         ]),
    Lang("XML", exts=("xml", "svg", "xsl", "xslt", "xsd", "plist", "rss", "atom", "glade", "ui", "kml", "gir", "csproj", "fxml", "desktop.in"),
         indent=2, block_comment=("<!--", "-->"), rules=[
             ("comment", r"<!--[\s\S]*?(?:-->|\Z)"),
             ("string", r"<!\[CDATA\[[\s\S]*?(?:\]\]>|\Z)"),
             ("meta", r"<![A-Za-z][^>]*>|<\?[\s\S]*?(?:\?>|\Z)"),
             ("tag", r"</?(?P<@@n>[A-Za-z_][\w:.-]*)", {"n": "tag"}),
             ("tag", r"/?>"),
             ("attr", r"(?<=[\s\"'])[A-Za-z_:][\w:.-]*(?=\s*=)"),
             ("string", r"\"[^\"]*\"?|'[^']*'?"),
             ("escape", r"&(?:#\d+|#x[0-9a-fA-F]+|\w+);"),
         ]),
    Lang("CSS", exts=("css", "scss", "sass", "less", "pcss"), indent=2, block_comment=("/*", "*/"), rules=[
        BLOCK_COMMENT,
        ("comment", r"(?<![:\w])//[^\n]*(?=\n|\Z)"),
        ("string", DQ), ("string", SQ),
        ("meta", r"@[\w-]+"),
        ("constant", r"#[0-9a-fA-F]{3,8}\b"),
        ("number", r"-?(?:\d+\.?\d*|\.\d+)" + CSS_UNITS + r"(?![\w])"),
        ("function", r"(?<![\w-])[\w-]+(?=\()"),
        ("variable", r"--[\w-]+|\$[\w-]+"),
        ("attr", r"(?<![\w-])[a-z][\w-]*(?=\s*:(?!:))(?=[^{};]*[;}\n])"),
        ("tag", r"(?<![\w-])[.#][A-Za-z_][\w-]*|::?(?:hover|focus|focus-within|focus-visible|active|visited|link|checked|disabled|enabled|"
                r"first-child|last-child|first-of-type|last-of-type|only-child|nth-child|nth-of-type|nth-last-child|not|is|where|has|"
                r"root|empty|target|before|after|first-line|first-letter|placeholder|selection|backdrop|marker)\b(?:\([^)]*\))?"),
        ("keyword", r"!important\b"),
    ]),
    Lang("Shell", exts=("sh", "bash", "zsh", "ksh", "fish", "profile", "bashrc", "zshrc", "env", "install"),
         files=(".bashrc", ".bash_profile", ".zshrc", ".profile", "PKGBUILD", ".xinitrc", ".xprofile", "APKBUILD"),
         shebang=r"^#!.*\b(?:ba|z|k|da|a)?sh\b|^#!/usr/bin/env\s+(?:ba|z)?sh", line_comment="#", indent=4, rules=[
             ("comment", r"(?:(?<=\s)|^)#[^\n]*"),
             ("string", r"\$'(?:\\.|[^'\\])*'?"),
             ("string", r"<<-?\s*(?P<@@q>['\"]?)(?P<@@d>\w+)(?P=@@q)[^\n]*\n[\s\S]*?^\s*(?P=@@d)$"),
             ("string", DQ.replace("\\n", "")), ("string", r"'[^']*'?"),
             ("variable", r"\$(?:\{[^}\n]*\}?|\(\(|\(|[A-Za-z_]\w*|[0-9@#?$!*-])"),
             ("keyword", words(SH_KW)), ("builtin", words(SH_BUILTIN)),
             ("function", r"^[ \t]*(?:function[ \t]+)?(?P<@@n>[A-Za-z_][\w-]*)(?=[ \t]*\(\))", {"n": "function"}),
             ("attr", r"(?<=\s)--?[A-Za-z][\w-]*"),
             ("number", r"\b\d+\b"),
             ("operator", r"[|&;<>(){}\[\]=!]+"),
         ]),
    Lang("TOML / INI", exts=("toml", "ini", "cfg", "conf", "config", "properties", "theme", "service", "socket", "timer", "mount", "desktop",
                             "editorconfig", "gitconfig", "repo", "directory", "lock"),
         files=(".editorconfig", ".gitconfig", "Cargo.lock", "theme.toml", "palette.toml", "settings.toml"),
         line_comment="#", indent=4, rules=[
             ("comment", r"[#;][^\n]*"),
             ("heading", r"^[ \t]*\[\[?[^\]\n]*\]\]?"),
             ("attr", r"^[ \t]*[\w.\-@/ ]+?(?=[ \t]*[=:])"),
             ("string", r"\"\"\"[\s\S]*?(?:\"\"\"|\Z)|'''[\s\S]*?(?:'''|\Z)"),
             ("string", DQ), ("string", r"'[^'\n]*'?"),
             ("constant", r"\b(?:true|false|yes|no|on|off)\b"),
             ("number", r"(?<![\w#])[-+]?\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b|#[0-9a-fA-F]{6,8}\b"),
         ]),
    Lang("YAML", exts=("yaml", "yml"), files=(".clang-format", ".gitlab-ci.yml"), line_comment="#", indent=2, rules=[
        ("comment", r"(?:(?<=\s)|^)#[^\n]*"),
        ("meta", r"^(?:---|\.\.\.)[ \t]*$|^%\w+[^\n]*"),
        ("string", DQ), ("string", r"'(?:''|[^'\n])*'?"),
        (None, r"^[ \t]*(?:-[ \t]+)*(?P<@@k>[\w./@$-][\w./@$ -]*?)(?=[ \t]*:(?:\s|$))", {"k": "attr"}),
        ("variable", r"[&*][\w-]+|!{1,2}[\w!./-]*"),
        ("constant", r"\b(?:true|false|null|yes|no|on|off|~)\b"),
        ("number", r"(?<![\w.])[-+]?\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.])"),
        ("operator", r"^[ \t]*-(?=\s)|[|>][-+]?(?=[ \t]*$)"),
    ]),
    Lang("Markdown", exts=("md", "markdown", "mdown", "mkd", "rst", "txt.md"), files=("README", "CHANGELOG", "NEWS", "TODO"), indent=2,
         pairs=False, rules=[
             ("comment", r"<!--[\s\S]*?(?:-->|\Z)"),
             ("string", r"^(?P<@@f>`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:^(?P=@@f)[`~]*[ \t]*$|\Z)"),
             ("heading", r"^#{1,6}[ \t][^\n]*|^[^\n]+\n(?:=+|-{2,})[ \t]*$"),
             ("constant", r"`[^`\n]+`"),
             ("link", r"!?\[[^\]\n]*\]\([^)\n]*\)|<https?://[^>\s]+>|https?://[^\s<>)\]]+"),
             ("keyword", r"\*\*[^*\n]+\*\*|__[^_\n]+__"),
             ("type", r"(?<![\w*])\*[^*\s][^*\n]*\*(?![\w*])|(?<![\w_])_[^_\s][^_\n]*_(?![\w_])"),
             ("operator", r"^[ \t]*(?:[-*+]|\d+[.)])(?=[ \t])|^>+|^(?:-{3,}|\*{3,}|_{3,})[ \t]*$"),
         ]),
    Lang("Rust", exts=("rs",), line_comment="//", block_comment=("/*", "*/"), indent=4, rules=[
        SLASH_COMMENT, BLOCK_COMMENT,
        ("string", r"b?r(?P<@@h>#*)\"[\s\S]*?\"(?P=@@h)"),
        ("string", r"b?\"(?:\\[\s\S]|[^\"\\])*\"?"),
        ("string", r"b?'(?:\\.[^']*|[^'\\])'"),
        ("decorator", r"#!?\[[^\]\n]*\]"),
        ("variable", r"'[A-Za-z_]\w*(?!')"),
        ("keyword", r"\bfn\b[ \t]+(?P<@@n>\w+)", {"n": "function"}),
        ("keyword", r"\b(?:struct|enum|trait|type|union|mod)\b[ \t]+(?P<@@n>\w+)", {"n": "type"}),
        ("constant", r"\b(?:true|false|None|Some|Ok|Err)\b"),
        ("keyword", words(RUST_KW)), ("type", words(RUST_TYPES)),
        ("meta", r"\b\w+!(?=[(\[{])"),
        ("function", r"\b[a-z_]\w*(?=\s*(?:::<[^>]*>)?\()"),
        ("type", r"\b[A-Z][A-Za-z0-9]*[a-z]\w*\b"),
        ("number", NUM_C), ("operator", r"->|=>|::|[-+*/%=<>!&|^~?]+"),
    ]),
    Lang("Go", exts=("go",), files=("go.mod", "go.sum"), line_comment="//", block_comment=("/*", "*/"), indent=4, tabs=True, rules=[
        SLASH_COMMENT, BLOCK_COMMENT,
        ("string", r"`[^`]*`?"), ("string", DQ), ("string", r"'(?:\\.|[^'\\\n])*'?"),
        ("keyword", r"\bfunc\b(?:[ \t]*\([^)]*\))?[ \t]*(?P<@@n>\w+)", {"n": "function"}),
        ("keyword", r"\btype\b[ \t]+(?P<@@n>\w+)", {"n": "type"}),
        ("constant", r"\b(?:true|false|nil|iota)\b"),
        ("keyword", words(GO_KW)), ("type", words(GO_TYPES)),
        ("builtin", words("append cap close complex copy delete imag len make new panic print println real recover")),
        ("function", r"\b[A-Za-z_]\w*(?=\()"),
        ("type", r"\b[A-Z][A-Za-z0-9]*[a-z]\w*\b"),
        ("number", NUM_C), ("operator", r":=|<-|[-+*/%=<>!&|^~]+"),
    ]),
    Lang("Java", exts=("java", "kt", "kts", "cs", "scala", "groovy", "gradle", "dart", "swift"), line_comment="//",
         block_comment=("/*", "*/"), indent=4, rules=[
             SLASH_COMMENT, BLOCK_COMMENT,
             ("string", r"\"\"\"[\s\S]*?(?:\"\"\"|\Z)"), ("string", DQ), ("string", SQ),
             ("decorator", r"@[A-Za-z_]\w*(?:\.\w+)*"),
             ("keyword", r"\b(?:class|interface|enum|record)\b[ \t]+(?P<@@n>\w+)", {"n": "type"}),
             ("constant", r"\b(?:true|false|null)\b|\b[A-Z][A-Z0-9_]{2,}\b"),
             ("keyword", words(JAVA_KW + " fun val object when is internal data lazy override open using namespace get set")),
             ("type", words(JAVA_TYPES)),
             ("function", r"\b[A-Za-z_]\w*(?=\s*\()"),
             ("type", r"\b[A-Z][A-Za-z0-9]*[a-z]\w*\b"),
             ("number", NUM_C), ("operator", OPS),
         ]),
    Lang("PHP", exts=("php", "phtml", "php5"), shebang=r"^#!.*\bphp", line_comment="//", block_comment=("/*", "*/"), indent=4, rules=[
        SLASH_COMMENT, HASH_COMMENT, BLOCK_COMMENT,
        ("meta", r"<\?(?:php|=)?|\?>"),
        ("string", DQ), ("string", SQ),
        ("variable", r"\$[A-Za-z_]\w*"),
        ("keyword", r"\bfunction\b[ \t]+&?(?P<@@n>\w+)", {"n": "function"}),
        ("constant", r"\b(?:true|false|null|TRUE|FALSE|NULL)\b"),
        ("keyword", words("abstract and array as break case catch class clone const continue declare default do echo else elseif empty "
                          "enddeclare endfor endforeach endif endswitch endwhile extends final finally fn for foreach function global "
                          "if implements include include_once instanceof insteadof interface isset list match namespace new or "
                          "print private protected public readonly require require_once return static switch throw trait try unset "
                          "use var while xor yield")),
        ("function", r"\b[A-Za-z_]\w*(?=\()"),
        ("type", r"\b[A-Z][A-Za-z0-9]*[a-z]\w*\b"),
        ("number", NUM_C), ("operator", OPS),
    ]),
    Lang("Lua", exts=("lua",), shebang=r"^#!.*\blua", line_comment="--", block_comment=("--[[", "]]"), indent=2, rules=[
        ("comment", r"--\[(?P<@@e>=*)\[[\s\S]*?(?:\](?P=@@e)\]|\Z)"), ("comment", r"--[^\n]*"),
        ("string", r"\[(?P<@@e>=*)\[[\s\S]*?(?:\](?P=@@e)\]|\Z)"), ("string", DQ), ("string", SQ),
        ("keyword", r"\bfunction\b[ \t]+(?:[\w.]+[.:])?(?P<@@n>\w+)", {"n": "function"}),
        ("constant", r"\b(?:true|false|nil)\b"),
        ("keyword", words(LUA_KW)), ("builtin", words(LUA_BUILTIN)),
        ("function", r"\b[A-Za-z_]\w*(?=\s*[(\"'{])"),
        ("number", NUM_C), ("operator", r"\.\.\.?|[-+*/%^#=<>~]+"),
    ]),
    Lang("SQL", exts=("sql", "psql", "mysql", "pgsql"), line_comment="--", block_comment=("/*", "*/"), indent=2,
         flags=re.IGNORECASE, rules=[
             ("comment", r"--[^\n]*"), BLOCK_COMMENT,
             ("string", r"'(?:''|[^'])*'?"), ("attr", r"\"[^\"\n]*\"?|`[^`\n]*`?"),
             ("keyword", words(SQL_KW)), ("type", words(SQL_TYPES)),
             ("constant", r"\b(?:true|false|null)\b"),
             ("function", r"\b[A-Za-z_]\w*(?=\()"),
             ("number", NUM_C), ("operator", r"[-+*/%=<>!|]+"),
         ]),
    Lang("Makefile", exts=("mk", "mak", "make"), files=("Makefile", "makefile", "GNUmakefile"), line_comment="#", indent=8, tabs=True,
         rules=[
             ("comment", r"(?:(?<=\s)|^)#[^\n]*"),
             ("function", r"^[ \t]*[A-Za-z0-9_.%/$()@*+ -]+?(?=[ \t]*:(?!=)(?:[^=\n]|$))"),
             ("meta", r"^[ \t]*(?:ifeq|ifneq|ifdef|ifndef|else|endif|include|-include|sinclude|define|endef|export|unexport|override|vpath)\b"),
             ("variable", r"\$[({][^)}\n]*[)}]|\$[@<^?*%+|]|\$\w"),
             ("attr", r"^[ \t]*[A-Za-z_][\w.-]*(?=[ \t]*(?:[:+?!]?=))"),
             ("string", DQ), ("string", r"'[^'\n]*'?"),
             ("operator", r"[:+?!]?=|::|\|"),
         ]),
    Lang("Diff", exts=("diff", "patch", "rej"), pairs=False, rules=[
        ("meta", r"^(?:diff |index |--- |\+\+\+ |new file|deleted file|similarity|rename |old mode|new mode)[^\n]*"),
        ("heading", r"^@@[^\n]*"),
        ("added", r"^\+[^\n]*"), ("removed", r"^-[^\n]*"),
        ("comment", r"^(?:\\ No newline)[^\n]*"),
    ]),
    Lang("Dockerfile", files=("Dockerfile", "Containerfile"), exts=("dockerfile",), line_comment="#", indent=4, rules=[
        ("comment", r"^[ \t]*#[^\n]*"),
        ("keyword", r"^[ \t]*(?i:FROM|RUN|CMD|LABEL|MAINTAINER|EXPOSE|ENV|ADD|COPY|ENTRYPOINT|VOLUME|USER|WORKDIR|ARG|ONBUILD|STOPSIGNAL|HEALTHCHECK|SHELL)\b"),
        ("string", DQ), ("string", SQ), ("variable", r"\$(?:\{[^}\n]*\}|\w+)"),
        ("keyword", r"\b(?:AS)\b"), ("attr", r"(?<=\s)--[\w-]+"), ("number", r"\b\d+\b"),
    ]),
    Lang("Plain text", exts=("txt", "text", "log", "csv", "tsv", "rtf"), pairs=False, rules=[
        ("link", r"https?://[^\s<>)\]\"']+"),
    ]),
]

PLAIN = LANGS[-1]
_BY_EXT, _BY_FILE = {}, {}
for _l in LANGS:
    for _e in _l.exts:
        _BY_EXT.setdefault(_e.lower(), _l)
    for _f in _l.files:
        _BY_FILE.setdefault(_f, _l)


def detect(path=None, first_line=""):
    """The Lang for a file name (by exact name, then extension), else by a '#!' line, else plain text."""
    if path:
        base = os.path.basename(path)
        if base in _BY_FILE:
            return _BY_FILE[base]
        low = base.lower()
        if low.endswith(".in") and low[:-3].rsplit(".", 1)[-1] in _BY_EXT:        # foo.desktop.in, foo.service.in ...
            return _BY_EXT[low[:-3].rsplit(".", 1)[-1]]
        if "." in low:
            ext = low.rsplit(".", 1)[-1]
            if ext in _BY_EXT:
                return _BY_EXT[ext]
        if low.startswith("dockerfile"):
            return _BY_FILE["Dockerfile"]
    if first_line.startswith("#!"):
        for l in LANGS:
            if l.shebang and l.shebang.search(first_line):
                return l
    return PLAIN


def by_name(name):
    for l in LANGS:
        if l.name == name:
            return l
    return PLAIN


# ---------------------------------------------------------------------------------------------------------------- editing helpers
OPEN_CLOSE = {"(": ")", "[": "]", "{": "}"}
CLOSE_OPEN = {v: k for k, v in OPEN_CLOSE.items()}


def find_match(text, pos, skip=None):
    """Offset of the bracket matching the one at text[pos] (None when absent). `skip` is a set of (start, end) spans (strings, comments)
    whose brackets are ignored."""
    ch = text[pos]
    if ch in OPEN_CLOSE:
        want, step, rng = OPEN_CLOSE[ch], 1, range(pos + 1, len(text))
    elif ch in CLOSE_OPEN:
        want, step, rng = CLOSE_OPEN[ch], -1, range(pos - 1, -1, -1)
    else:
        return None
    depth = 0
    for i in rng:
        c = text[i]
        if skip and _in_spans(skip, i):
            continue
        if c == ch:
            depth += 1
        elif c == want:
            if depth == 0:
                return i
            depth -= 1
        if i - pos > 200000 or pos - i > 200000:
            return None
    return None


def _in_spans(spans, i):
    lo, hi = 0, len(spans)
    while lo < hi:
        mid = (lo + hi) // 2
        s, e = spans[mid]
        if i < s:
            hi = mid
        elif i >= e:
            lo = mid + 1
        else:
            return True
    return False


def skip_spans(lang, text):
    """Sorted (start, end) spans of strings and comments, for bracket matching."""
    return [(s, e) for s, e, k in lang.tokenize(text) if k in ("string", "comment")]


def indent_of(line):
    return line[:len(line) - len(line.lstrip(" \t"))]


def next_indent(lang, line, unit):
    """Indentation for the line after `line` (keeps the indent, adds one level after an opening bracket / ':' in Python)."""
    base = indent_of(line)
    body = line.rstrip()
    if not body:
        return base
    if lang.name == "Python" and body.endswith(":") and not body.lstrip().startswith("#"):
        return base + unit
    if lang.name in ("Makefile",) and body.endswith(":"):
        return base + "\t"
    if body[-1] in "{[(" and lang.pairs:
        return base + unit
    if lang.name in ("Lua",) and re.search(r"\b(?:then|do|function\b.*\)|repeat|else)$", body):
        return base + unit
    if lang.name == "Shell" and re.search(r"\b(?:then|do|else)$|\{$", body):
        return base + unit
    if lang.name in ("YAML",) and body.endswith(":"):
        return base + unit
    return base

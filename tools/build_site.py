#!/usr/bin/env python3
"""
Build the Dr. Syntax preview site into website/.

Colours are read out of themes/dr-syntax.json rather than restated, so the site
cannot drift from what ships. Pages are emitted self-contained - CSS and JS are
authored once here and inlined at build time - so a single file renders
identically from GitHub Pages, a local checkout and a published artifact, none of
which resolve relative paths the same way.

Usage:
    python3 tools/build_site.py
"""
from __future__ import annotations

import base64
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_theme import (  # noqa: E402
    SYNTAX_HUES, VIM_MODES, Palette, contrast, gamut_fit_chroma, oklch, rgb_to_oklch,
)
from validate_theme import AAA_FLOOR, TOKEN_FLOORS, _contrast, _rgba  # noqa: E402

OUT = ROOT / "website"
THEME = json.loads((ROOT / "themes" / "dr-syntax.json").read_text())
REPO = "https://github.com/ChrisNicholson30/Dr.-Syntax"
KEYS = ("dark", "oled", "light")


# --------------------------------------------------------------------------
# A deliberately small highlighter
# --------------------------------------------------------------------------
# Hand-marking six language samples is error-prone and dull, and a preview that
# highlights its own samples wrongly is worse than one with fewer languages. This
# is a scanner, not a parser: it resolves comments and strings first (so keywords
# inside them stay quiet), then classifies identifiers by context. It is enough
# for a faithful preview and honest about being no more than that.

LANGS: dict[str, dict] = {
    "typescript": dict(
        label="TypeScript", file="oklch.ts",
        line_comment=r"//", block_comment=(r"/\*", r"\*/"),
        strings=[r'"(?:[^"\\\n]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'", r"`(?:[^`\\]|\\.)*`"],
        keywords="import from export const let var function return if else for while new "
                 "class interface type extends implements as await async throw try catch "
                 "of in typeof instanceof readonly public private static null undefined "
                 "true false this void never".split(),
        types="number string boolean Math Array Object Promise RangeError Vec3 Oklch "
              "Record Partial".split(),
    ),
    "python": dict(
        label="Python", file="gamut.py",
        line_comment=r"#", block_comment=None,
        strings=[r'"""(?:.|\n)*?"""', r'"(?:[^"\\\n]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'"],
        keywords="def class return if elif else for while import from as with lambda "
                 "yield raise try except finally in is not and or None True False global "
                 "assert pass break continue async await del".split(),
        types="float int str bool list dict tuple set range enumerate zip len min max abs "
              "round ValueError TypeError".split(),
    ),
    "rust": dict(
        label="Rust", file="palette.rs",
        line_comment=r"//", block_comment=(r"/\*", r"\*/"),
        strings=[r'"(?:[^"\\\n]|\\.)*"'],
        keywords="fn let mut const struct enum impl trait pub use mod match if else for "
                 "while loop return self Self where as in ref move dyn crate super "
                 "true false unsafe async await".split(),
        types="f32 f64 u8 u32 usize i32 bool str String Vec Option Result Some None Ok Err "
              "Hsla Oklch Srgb".split(),
    ),
    "css": dict(
        label="CSS", file="theme.css",
        line_comment=None, block_comment=(r"/\*", r"\*/"),
        strings=[r'"(?:[^"\\\n]|\\.)*"', r"'(?:[^'\\\n]|\\.)*'"],
        keywords="important from to and not or only".split(),
        types=[],
    ),
    "json": dict(
        label="JSON", file="dr-syntax.json",
        line_comment=None, block_comment=None,
        strings=[r'"(?:[^"\\\n]|\\.)*"'],
        keywords="true false null".split(),
        types=[],
    ),
}

IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


def highlight(code: str, lang: str) -> list[str]:
    """Return one span-marked HTML string per line."""
    spec = LANGS[lang]
    parts: list[str] = []
    if spec["block_comment"]:
        o, c = spec["block_comment"]
        parts.append(f"(?P<blockcomment>{o}(?:.|\\n)*?{c})")
    if spec["line_comment"]:
        parts.append(f"(?P<comment>{spec['line_comment']}[^\\n]*)")
    if spec["strings"]:
        parts.append("(?P<string>" + "|".join(spec["strings"]) + ")")
    parts.append(r"(?P<number>\b0[xX][0-9a-fA-F]+\b|\b\d+\.?\d*(?:[eE][-+]?\d+)?\b)")
    if lang == "css":
        parts.append(r"(?P<cssat>@[a-z-]+)")
        parts.append(r"(?P<cssvar>--[A-Za-z0-9-]+)")
        parts.append(r"(?P<cssprop>[a-z-]+(?=\s*:))")
        parts.append(r"(?P<cssselector>[.#][A-Za-z][\w-]*|::?[a-z-]+)")
    parts.append(f"(?P<call>{IDENT}(?=\\s*\\())")
    parts.append(f"(?P<member>(?<=\\.){IDENT})")
    parts.append(f"(?P<word>{IDENT})")
    parts.append(r"(?P<punct>[^\w\s])")
    scanner = re.compile("|".join(parts))

    kw, ty = set(spec["keywords"]), set(spec["types"])
    out: list[str] = []
    pos = 0

    def emit(cls: str, text: str) -> None:
        out.append(f'<span class="t-{cls}">{html.escape(text)}</span>' if cls
                   else html.escape(text))

    while pos < len(code):
        m = scanner.search(code, pos)
        if not m:
            emit("", code[pos:]); break
        if m.start() > pos:
            emit("", code[pos:m.start()])
        kind, text = m.lastgroup, m.group()
        if kind in ("comment", "blockcomment"):
            emit("cmt", text)
        elif kind == "string":
            # JSON object keys are properties, not strings.
            after = code[m.end():m.end() + 8].lstrip()
            emit("prop" if (lang == "json" and after.startswith(":")) else "str", text)
        elif kind == "number":
            emit("num", text)
        elif kind == "cssat":
            emit("kw", text)
        elif kind == "cssvar":
            emit("prop", text)
        elif kind == "cssprop":
            emit("prop", text)
        elif kind == "cssselector":
            emit("tag", text)
        elif kind == "call":
            emit("kw" if text in kw else "fn", text)
        elif kind == "member":
            emit("prop", text)
        elif kind == "word":
            if text in kw:
                emit("kw", text)
            elif text in ty or (lang != "css" and text[:1].isupper()):
                emit("typ", text)
            else:
                emit("var", text)
        else:
            emit("punc", text)
        pos = m.end()

    # Re-split into lines, reopening spans that straddle a newline.
    joined = "".join(out)
    lines: list[str] = []
    for raw in joined.split("\n"):
        lines.append(raw)
    # Balance spans per line (block comments and template strings span lines).
    fixed, carry = [], None
    for line in lines:
        opens = re.findall(r'<span class="(t-[a-z]+)">', line)
        closes = line.count("</span>")
        prefix = f'<span class="{carry}">' if carry else ""
        depth = len(opens) - closes
        suffix = "</span>" * depth if depth > 0 else ""
        carry = opens[-1] if depth > 0 else None
        fixed.append(prefix + line + suffix)
    return fixed


# --------------------------------------------------------------------------
# Samples. Real code, not lorem - a theme is judged on the shapes it makes.
# --------------------------------------------------------------------------

SAMPLES: dict[str, str] = {
    "typescript": '''import { clamp, type Vec3 } from "./math";

/** Convert an OKLCH triplet to linear sRGB. */
export interface Oklch {
  lightness: number;
  chroma: number;
  hue: number;
}

const LMS_TO_RGB = [
  [ 4.0767416621, -3.3077115913,  0.2309699292],
  [-1.2684380046,  2.6097574011, -0.3413193965],
] as const;

export function toLinearSrgb(colour: Oklch): Vec3 {
  const { chroma, hue } = colour;
  const rad = (hue * Math.PI) / 180;

  // Cube each component before the matrix transform.
  const lms = channels.map((v) => v ** 3);

  if (!inGamut(lms)) {
    throw new RangeError(`hue ${hue} is outside sRGB`);
  }
  return LMS_TO_RGB.map((row) => dot(row, lms)) as Vec3;
}

export const inGamut = (v: Vec3): boolean =>
  v.every((c) => c >= -1e-6 && c <= 1 + 1e-6);
''',
    "python": '''from dataclasses import dataclass
from math import cos, radians

TARGET_CONTRAST = 7.0


@dataclass(frozen=True)
class Colour:
    """A colour authored in OKLCH, not in hex."""

    lightness: float
    chroma: float
    hue: float

    def is_legible_on(self, background: "Colour") -> bool:
        return contrast(self, background) >= TARGET_CONTRAST


def gamut_fit_chroma(lightness, chroma, hue):
    # Hold lightness and hue; give up chroma until the colour fits sRGB.
    if in_gamut(lightness, chroma, hue):
        return chroma
    low, high = 0.0, chroma
    for _ in range(40):
        mid = (low + high) / 2
        low, high = (mid, high) if in_gamut(lightness, mid, hue) else (low, mid)
    return low
''',
    "rust": '''use std::sync::Arc;

/// Every colour the editor paints, resolved for one variant.
#[derive(Clone, Debug, PartialEq)]
pub struct ThemeColors {
    pub background: Hsla,
    pub editor_foreground: Hsla,
    pub syntax: Arc<[Hsla]>,
}

impl ThemeColors {
    pub fn contrast_floor(&self) -> f32 {
        self.syntax
            .iter()
            .map(|c| contrast(*c, self.background))
            .fold(f32::INFINITY, f32::min)
    }

    /// Returns None when no lightness satisfies the floor.
    pub fn solve_plane(&self, floor: f32) -> Option<f32> {
        let mut best = None;
        for step in 200..980 {
            let lightness = step as f32 / 1000.0;
            if self.contrast_floor() >= floor {
                best = Some(lightness);
            }
        }
        best
    }
}
''',
    "css": ''':root {
  --plane-lightness: 0.737;
  --syntax-chroma: 0.170;
  --floor: 7.0;
}

.editor__line--active {
  background: oklch(0.245 0.014 265);
  border-left: 2px solid var(--accent);
  transition: background 160ms ease;
}

/* Selection is drawn under the code, so it holds a contrast contract. */
.editor ::selection {
  background: oklch(0.72 0.17 282 / 18.8%);
}

@media (prefers-color-scheme: light) {
  :root {
    --plane-lightness: 0.439;
    --syntax-chroma: 0.190;
  }
}
''',
    "json": '''{
  "$schema": "https://zed.dev/schema/themes/v0.2.0.json",
  "name": "Dr. Syntax",
  "author": "Christopher Nicholson",
  "themes": [
    {
      "name": "Dr. Syntax Dark",
      "appearance": "dark",
      "style": {
        "editor.background": "#13161dff",
        "editor.foreground": "#b4b8c1ff",
        "syntax": {
          "keyword": { "color": "#f678b9ff", "font_style": null },
          "string":  { "color": "#10c97fff", "font_weight": null },
          "comment": { "color": "#8594a4ff", "font_style": "italic" }
        }
      }
    }
  ]
}
''',
}


# --------------------------------------------------------------------------
# Shared styles. Authored once, inlined into every page at build time.
# --------------------------------------------------------------------------

CSS = """
:root{
  --ground:#f4f5f9; --surface:#ffffff; --raised:#eceef5;
  --ink:#191b22; --muted:#5a6072; --faint:#878ca0;
  --rule:#e0e3ec; --rule-strong:#c9cddb;
  --accent:#4538b6; --accent-soft:#ecebfb;
  --shadow:0 1px 2px rgba(20,22,40,.05), 0 14px 34px -20px rgba(20,22,40,.4);
  --nav-bg:rgba(244,245,249,.95);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#0b0c10; --surface:#12141a; --raised:#181b23;
    --ink:#e2e4ec; --muted:#8b90a3; --faint:#666b7d;
    --rule:#22252f; --rule-strong:#333743;
    --accent:#9d9eff; --accent-soft:#1b1c2e;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 14px 36px -20px rgba(0,0,0,.85);
    --nav-bg:rgba(11,12,16,.95);
  }
}
:root[data-theme="dark"]{
  --ground:#0b0c10; --surface:#12141a; --raised:#181b23;
  --ink:#e2e4ec; --muted:#8b90a3; --faint:#666b7d;
  --rule:#22252f; --rule-strong:#333743;
  --accent:#9d9eff; --accent-soft:#1b1c2e;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 14px 36px -20px rgba(0,0,0,.85);
  --nav-bg:rgba(11,12,16,.95);
}

*{box-sizing:border-box;}
html{scroll-behavior:smooth;}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.6; -webkit-font-smoothing:antialiased;
}
a{color:var(--accent);}
.wrap{max-width:1120px; margin:0 auto; padding:0 28px;}
main{display:flex; flex-direction:column; gap:56px; padding:44px 0 96px;}
section{display:flex; flex-direction:column; gap:18px; scroll-margin-top:80px;}

h1{font-size:clamp(32px,5.4vw,50px); line-height:1.02; margin:0; letter-spacing:-.03em;
  font-weight:600; text-wrap:balance;}
h2{font-size:23px; margin:0; font-weight:600; letter-spacing:-.018em; text-wrap:balance;}
h3{font-size:15px; margin:0; font-weight:600;}
.note{margin:0; max-width:70ch; color:var(--muted); font-size:14.5px;}
.lead{margin:0; max-width:62ch; color:var(--muted); font-size:17px; line-height:1.55;}
.eyebrow{margin:0; font-family:"JetBrains Mono",ui-monospace,monospace; font-size:10.5px;
  letter-spacing:.15em; text-transform:uppercase; color:var(--faint);}
code{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:.88em;
  background:var(--raised); padding:1px 5px; border-radius:4px;}

/* ---- nav ---- */
.nav{position:sticky; top:0; z-index:20; background:var(--nav-bg);
  backdrop-filter:saturate(1.6) blur(12px); border-bottom:1px solid var(--rule);}
.nav-in{display:flex; align-items:center; gap:22px; height:60px;}
.brandmark{display:flex; align-items:center; gap:10px; text-decoration:none; color:var(--ink);
  font-weight:600; letter-spacing:-.015em; flex:none;}
.brandmark img{width:30px; height:30px; border-radius:50%;}
.nav-links{display:flex; gap:4px; margin-left:auto; flex-wrap:wrap;}
.nav-links a{padding:6px 12px; border-radius:7px; text-decoration:none; color:var(--muted);
  font-size:14px; font-weight:500;}
.nav-links a:hover{background:var(--raised); color:var(--ink);}
.nav-links a[aria-current="page"]{background:var(--accent-soft); color:var(--accent);}
.nav-links a.ext{color:var(--faint);}

/* ---- hero ---- */
.hero{display:grid; grid-template-columns:auto 1fr; gap:34px; align-items:center;
  padding:18px 0 6px;}
.hero img{width:168px; height:168px; border-radius:50%;
  filter:drop-shadow(0 10px 30px rgba(70,60,190,.30));}
.hero-text{display:flex; flex-direction:column; gap:14px; min-width:0;}
.cta{display:flex; flex-wrap:wrap; gap:10px; margin-top:2px;}
.btn{display:inline-flex; align-items:center; padding:10px 19px; border-radius:8px;
  border:1px solid var(--rule-strong); color:var(--ink); text-decoration:none;
  font-size:14.5px; font-weight:500; transition:background .16s, border-color .16s;}
.btn:hover{background:var(--raised); border-color:var(--accent);}
.btn.primary{background:var(--accent); border-color:var(--accent); color:var(--ground);}
.btn.primary:hover{filter:brightness(1.08);}
.btn:focus-visible,.tab-btn:focus-visible,.nav-links a:focus-visible{
  outline:2px solid var(--accent); outline-offset:2px;}

/* ---- switchers ---- */
.controls{display:flex; flex-wrap:wrap; gap:12px; align-items:center;}
.switch{display:flex; gap:3px; padding:4px; border:1px solid var(--rule);
  border-radius:9px; background:var(--surface);}
.tab-btn{font:inherit; font-size:13px; font-weight:500; cursor:pointer;
  padding:7px 14px; border:0; border-radius:6px; background:transparent;
  color:var(--muted); transition:background .16s, color .16s;}
.tab-btn:hover{color:var(--ink); background:var(--raised);}
.tab-btn[aria-selected="true"]{background:var(--accent); color:var(--ground);}
.switch-label{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:10.5px;
  letter-spacing:.13em; text-transform:uppercase; color:var(--faint);}

/* ---- editor mock: painted entirely by the theme ---- */
.editor{border-radius:11px; overflow:hidden; border:1px solid var(--e-border);
  box-shadow:var(--shadow); background:var(--e-editor);
  font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:13px; line-height:1.62; transition:background .2s, border-color .2s;}
.editor.compact{font-size:11.5px; box-shadow:none;}
.titlebar{display:flex; align-items:center; gap:8px; padding:9px 13px;
  background:var(--e-titlebar); border-bottom:1px solid var(--e-borderv);}
.dot{width:10px; height:10px; border-radius:50%;}
.titlebar .path{margin-left:8px; font-size:11.5px; color:var(--e-muted);}
.tabs{display:flex; background:var(--e-tabbar); border-bottom:1px solid var(--e-borderv);
  overflow-x:auto;}
.tab{padding:8px 15px; font-size:12px; color:var(--e-muted); white-space:nowrap;
  background:var(--e-tabinactive); border-right:1px solid var(--e-borderv);
  display:flex; align-items:center; gap:7px;}
.tab.active{background:var(--e-tabactive); color:var(--e-text);}
.tab .dirty{width:6px; height:6px; border-radius:50%; background:var(--e-modified);}
.code{padding:12px 0; overflow-x:auto;}
.code-line{display:flex; padding-right:14px; white-space:pre;}
.code-line.is-active{background:var(--e-activeline);}
.code-line.is-selected .code-text{background:var(--e-selection);}
.gutter-num{flex:0 0 52px; text-align:right; padding-right:16px; color:var(--e-linenum);
  user-select:none;}
.gutter-num.is-active{color:var(--e-activelinenum);}
.code-text{color:var(--e-fg);}
.statusbar{display:flex; gap:16px; padding:6px 14px; background:var(--e-statusbar);
  border-top:1px solid var(--e-borderv); font-size:11px; color:var(--e-muted);
  align-items:center;}
.statusbar .ok{color:var(--e-success);} .statusbar .warn{color:var(--e-warning);}
.statusbar .spacer{margin-left:auto;}
.mode-chip{padding:1px 8px; border-radius:4px; font-weight:700; letter-spacing:.06em;
  background:var(--e-vimnormal-bg); color:var(--e-vimnormal-fg);}
.t-kw{color:var(--e-kw);} .t-fn{color:var(--e-fn);} .t-str{color:var(--e-str);}
.t-typ{color:var(--e-typ);} .t-num{color:var(--e-num);} .t-prop{color:var(--e-prop);}
.t-cmt{color:var(--e-cmt); font-style:italic;} .t-punc{color:var(--e-punc);}
.t-var{color:var(--e-fg);} .t-tag{color:var(--e-tag);}

/* ---- three-up comparison ---- */
.trio{display:grid; grid-template-columns:repeat(auto-fit,minmax(310px,1fr)); gap:18px;}
.trio figure{margin:0; display:flex; flex-direction:column; gap:9px;}
.trio figcaption{display:flex; align-items:baseline; gap:9px;}
.trio figcaption b{font-size:14px;} .trio figcaption span{font-size:11.5px;
  font-family:"JetBrains Mono",ui-monospace,monospace; color:var(--faint);}

/* ---- readout ---- */
.readout{display:grid; grid-template-columns:repeat(auto-fit,minmax(148px,1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule); border-radius:9px; overflow:hidden;}
.cell{background:var(--surface); padding:13px 16px;}
.cell dt{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:10px;
  letter-spacing:.11em; text-transform:uppercase; color:var(--faint); margin:0 0 5px;}
.cell dd{margin:0; font-size:20px; font-weight:600; letter-spacing:-.02em;
  font-variant-numeric:tabular-nums;}

/* ---- tables ---- */
.table-scroll{overflow-x:auto; border:1px solid var(--rule); border-radius:9px;
  background:var(--surface);}
table{border-collapse:collapse; width:100%; min-width:560px;}
th{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:10px;
  letter-spacing:.11em; text-transform:uppercase; color:var(--faint);
  text-align:left; padding:11px 14px; border-bottom:1px solid var(--rule); font-weight:500;
  background:var(--surface);}
td{padding:9px 14px; border-bottom:1px solid var(--rule); font-size:13.5px;}
tr:last-child td{border-bottom:0;}
td.mono,.mono{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:12.5px;
  font-variant-numeric:tabular-nums; color:var(--muted);}
th.num,td.num{text-align:right;}
.chip{display:inline-flex; align-items:center; gap:9px;}
.chip i{width:15px; height:15px; border-radius:4px; flex:none;
  box-shadow:inset 0 0 0 1px rgba(128,128,128,.3);}
.role{color:var(--muted); font-size:12.5px;}

/* ---- swatch grid ---- */
.swatches{display:grid; grid-template-columns:repeat(auto-fill,minmax(168px,1fr)); gap:10px;}
.sw{border:1px solid var(--rule); border-radius:8px; overflow:hidden; background:var(--surface);}
.sw .band{height:46px;}
.sw .meta{padding:8px 10px; display:flex; flex-direction:column; gap:2px;}
.sw .meta b{font-size:12px; font-weight:600; overflow-wrap:anywhere;}
.sw .meta span{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:10.5px;
  color:var(--faint);}

/* ---- terminal ---- */
.term{border-radius:10px; border:1px solid var(--e-border); background:var(--e-terminalbg);
  padding:14px 16px; font-family:"JetBrains Mono",ui-monospace,monospace; font-size:12.5px;
  line-height:1.7; overflow-x:auto; box-shadow:var(--shadow);}
.term .row{white-space:pre; color:var(--e-terminalfg);}
.ansi-grid{display:grid; grid-template-columns:repeat(8,1fr); gap:5px; margin-top:10px;}
.ansi-grid i{height:26px; border-radius:4px; display:block;}

/* ---- steps / code blocks ---- */
.steps{display:grid; grid-template-columns:repeat(auto-fit,minmax(232px,1fr)); gap:16px;}
.step{border:1px solid var(--rule); border-radius:9px; background:var(--surface);
  padding:15px 17px; display:flex; flex-direction:column; gap:8px;}
pre{margin:0; overflow-x:auto; background:var(--surface); border:1px solid var(--rule);
  border-radius:8px; padding:13px 15px;}
pre code{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:12.5px;
  color:var(--ink); background:none; padding:0;}
pre code .c{color:var(--faint);}
.step pre{overflow-x:visible;}
.step pre code{white-space:pre-wrap; overflow-wrap:anywhere;}
kbd{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:11.5px;
  border:1px solid var(--rule-strong); border-bottom-width:2px; border-radius:5px;
  padding:1px 5px; background:var(--raised);}

/* ---- chart ---- */
.chart{width:100%; height:auto; display:block;}
.chart-wrap{border:1px solid var(--rule); border-radius:9px; background:var(--surface);
  padding:16px 12px 8px;}
.deadzone{fill:var(--accent); opacity:.07;}
.grid{stroke:var(--rule-strong); stroke-width:1; stroke-dasharray:2 4;}
.chart-tick,.chart-zone{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:9.5px;
  fill:var(--faint); letter-spacing:.08em;}
.chart-zone{text-transform:uppercase;}
.curve{fill:none; stroke-width:2; stroke-linejoin:round;}
.curve-dark{stroke:var(--accent);}
.curve-light{stroke:var(--ink); stroke-dasharray:5 4; opacity:.55;}
.mark{fill:var(--ink);}
.legend{display:flex; flex-wrap:wrap; gap:18px; padding:0 4px 6px;}
.legend span{display:inline-flex; align-items:center; gap:7px; font-size:12px;
  color:var(--muted);}
.legend i{width:16px; height:2px; background:var(--accent);}
.legend i.dash{background:repeating-linear-gradient(90deg,var(--ink) 0 5px,transparent 5px 9px);
  opacity:.55;}
.legend i.zone{width:14px; height:11px; background:var(--accent); opacity:.14; border-radius:2px;}

footer{border-top:1px solid var(--rule); padding:24px 0 0; color:var(--faint); font-size:13px;}
footer .wrap{display:flex; flex-wrap:wrap; gap:8px 24px; justify-content:space-between;}

@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto;}
  *{animation-duration:.001ms !important; transition-duration:.001ms !important;}
}
@media (max-width:760px){
  .wrap{padding:0 16px;} main{gap:40px; padding:28px 0 64px;}
  .hero{grid-template-columns:1fr; gap:18px;}
  .hero img{width:110px; height:110px;}
  .gutter-num{flex-basis:40px; padding-right:11px;}
  .editor{font-size:12px;}
  .ansi-grid{grid-template-columns:repeat(4,1fr);}
}
"""


# --------------------------------------------------------------------------
# Per-variant data
# --------------------------------------------------------------------------

UI_VARS = {
    "background": "bg", "editor.background": "editor",
    "elevated_surface.background": "elevated", "title_bar.background": "titlebar",
    "tab_bar.background": "tabbar", "tab.active_background": "tabactive",
    "tab.inactive_background": "tabinactive", "status_bar.background": "statusbar",
    "border": "border", "border.variant": "borderv", "text": "text",
    "text.muted": "muted", "editor.foreground": "fg", "editor.line_number": "linenum",
    "editor.active_line_number": "activelinenum",
    "editor.active_line.background": "activeline", "editor.indent_guide": "indentguide",
    "search.match_background": "match", "text.accent": "accent", "error": "error",
    "warning": "warning", "success": "success", "version_control.added": "added",
    "version_control.modified": "modified", "version_control.deleted": "vcdeleted",
    "terminal.background": "terminalbg", "terminal.foreground": "terminalfg",
    "vim.normal.background": "vimnormal-bg", "vim.normal.foreground": "vimnormal-fg",
}
SYN_VARS = {"keyword": "kw", "function": "fn", "string": "str", "type": "typ",
            "number": "num", "property": "prop", "comment": "cmt",
            "punctuation": "punc", "tag": "tag"}

# The syntax token that carries each hue role, so the site can look the colour up
# in the shipped file rather than asking the generator what it should have been.
HUE_TOKEN = {"rose": "keyword", "orchid": "tag", "violet": "attribute",
             "azure": "property", "cyan": "function", "jade": "string",
             "amber": "type", "tangerine": "number"}


def _hue_token(role: str) -> str:
    return HUE_TOKEN[role]


ROLE_LABEL = {
    "rose": "keyword · control flow", "orchid": "tag · namespace · title",
    "violet": "attribute · preprocessor", "azure": "property · member",
    "cyan": "function · method", "jade": "string · literal text",
    "amber": "type · class · enum", "tangerine": "number · boolean · constant",
}

KEY_GROUPS = [
    ("Surfaces", ("background", "surface.", "elevated_surface.", "drop_target.")),
    ("Borders", ("border",)),
    ("Elements", ("element.", "ghost_element.")),
    ("Text and icons", ("text", "icon", "link_text")),
    ("Window chrome", ("title_bar.", "tab_bar.", "tab.", "status_bar.", "toolbar.",
                       "panel.", "pane.", "pane_group.")),
    ("Editor", ("editor.",)),
    ("Scrollbar and minimap", ("scrollbar.", "minimap.")),
    ("Search", ("search.",)),
    ("Diagnostics and status", ("error", "warning", "info", "success", "hint",
                                "predictive", "conflict", "created", "deleted",
                                "modified", "renamed", "ignored", "hidden",
                                "unreachable", "debugger.")),
    ("Version control", ("version_control.",)),
    ("Terminal", ("terminal.",)),
    ("Vim and Helix modes", ("vim.",)),
]


def variant_data(full: bool) -> dict:
    """Read the shipped theme.

    Every number the site prints is measured from the hex values it is about to
    render. Deriving them from the generator instead would let the page state a
    contrast it is not showing - the statistics and the swatches would come from
    two different sources, and only one of them is what Zed loads.
    """
    out = {}
    for key, theme in zip(KEYS, THEME["themes"]):
        s = theme["style"]
        p = Palette(key)                      # hue roles and angles only
        ed = _rgba(s["editor.background"])[0]

        syn_rgb = {t: _rgba(v["color"])[0] for t, v in s["syntax"].items()}
        aaa = {t: _contrast(c, ed) for t, c in syn_rgb.items()
               if TOKEN_FLOORS.get(t, AAA_FLOOR) >= AAA_FLOOR}
        planes = [rgb_to_oklch(syn_rgb[_hue_token(h)]) for h in SYNTAX_HUES]
        sel_alpha = _rgba(s["players"][0]["selection"])[1]

        entry = {
            "name": theme["name"], "appearance": theme["appearance"],
            "short": theme["name"].replace("Dr. Syntax ", ""),
            "ui": {v: s[k] for k, v in UI_VARS.items()},
            "syn": {v: s["syntax"][k]["color"] for k, v in SYN_VARS.items()},
            "plane": round(sum(L for L, _, _ in planes) / len(planes), 3),
            "chroma": round(sum(C for _, C, _ in planes) / len(planes), 3),
            "minSyntax": round(min(aaa.values()), 2),
            "comment": round(_contrast(syn_rgb["comment"], ed), 2),
            "foreground": round(_contrast(_rgba(s["editor.foreground"])[0], ed), 2),
            "selectionAlpha": round(sel_alpha, 3),
            "editorBg": s["editor.background"][:7],
            "hues": [{"role": h, "label": ROLE_LABEL[h],
                      "hex": s["syntax"][_hue_token(h)]["color"][:7],
                      "angle": round(rgb_to_oklch(syn_rgb[_hue_token(h)])[2]),
                      "chroma": round(rgb_to_oklch(syn_rgb[_hue_token(h)])[1], 3),
                      "ratio": round(aaa[_hue_token(h)], 2)} for h in SYNTAX_HUES],
            "ansi": [s[f"terminal.ansi.{n}"] for n in
                     ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")],
            "ansiBright": [s[f"terminal.ansi.bright_{n}"] for n in
                           ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")],
            "vim": [{"mode": m, "bg": s[f"vim.{m}.background"],
                     "fg": s[f"vim.{m}.foreground"],
                     "ratio": round(_contrast(_rgba(s[f"vim.{m}.foreground"])[0],
                                              _rgba(s[f"vim.{m}.background"])[0]), 2)}
                    for m in VIM_MODES],
        }
        if full:
            entry["style"] = {k: v for k, v in s.items()
                              if k not in ("syntax", "players", "accents")}
            entry["syntaxAll"] = {k: v["color"] for k, v in s["syntax"].items()}
        out[key] = entry
    return out


def chroma_curves() -> dict:
    curves = {}
    for key in ("dark", "light"):
        p = Palette(key)
        curves[key] = {
            "points": [round(gamut_fit_chroma(p.syn_L, 0.40, float(a % 360)), 4)
                       for a in range(0, 361, 5)],
            "marks": [{"role": r, "angle": round(p.hues[r])} for r in SYNTAX_HUES],
        }
    return curves


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------

# A proper multi-page site references its assets rather than inlining them: the
# logo alone appears three times per page (nav, hero, favicon), so inlining it
# cost ~220 KB per page and defeated caching across pages.
LOGO_SRC = "assets/dr-syntax-logo.webp"


def logo_uri() -> str:
    return LOGO_SRC


PAGES = [("index.html", "Overview"), ("preview.html", "Preview"),
         ("palette.html", "Palette"), ("method.html", "Method")]


def nav(active: str) -> str:
    CURRENT = ' aria-current="page"'
    links = "".join(
        f'<a href="{href}"{CURRENT if href == active else ""}>{label}</a>'
        for href, label in PAGES
    )
    return f'''<nav class="nav"><div class="wrap nav-in">
  <a class="brandmark" href="index.html"><img src="{logo_uri()}" alt=""> Dr. Syntax</a>
  <div class="nav-links">{links}<a class="ext" href="{REPO}">GitHub ↗</a></div>
</div></nav>'''


def editor_vars(v: dict) -> str:
    parts = [f"--e-{n}:{c}" for n, c in v["ui"].items()]
    parts += [f"--e-{n}:{c}" for n, c in v["syn"].items()]
    return ";".join(parts)


TRIO_SAMPLE = """export interface Oklch {
  lightness: number;
  hue: number;
}

// Hold lightness, give up chroma.
export function fit(c: Oklch): Vec3 {
  const rad = (c.hue * Math.PI) / 180;
  if (!inGamut(rad)) {
    throw new RangeError(`${c.hue} out of range`);
  }
  return toLinear(rad, 0.737);
}
"""


TRIO_SEL = {6, 7}


def code_block(lang: str, active: int | None = None,
               selected: set[int] | None = None, source: str | None = None) -> str:
    selected = selected or set()
    rows = []
    for i, line in enumerate(highlight(source if source is not None else SAMPLES[lang], lang),
                             start=1):
        cls = ["code-line"]
        if i == active:
            cls.append("is-active")
        if i in selected:
            cls.append("is-selected")
        num = "gutter-num is-active" if i == active else "gutter-num"
        body = line if line.strip() else "&nbsp;"
        rows.append(f'<div class="{" ".join(cls)}"><span class="{num}">{i}</span>'
                    f'<span class="code-text">{body}</span></div>')
    return "\n".join(rows)


def editor(lang: str, *, fixed: dict | None = None, compact: bool = False,
           active: int | None = None, selected: set[int] | None = None,
           chrome: bool = True, panel_id: str = "", source: str | None = None) -> str:
    spec = LANGS[lang]
    style = f' style="{editor_vars(fixed)}"' if fixed else ""
    cls = "editor compact" if compact else "editor"
    idattr = f' id="{panel_id}"' if panel_id else ""
    head = ""
    if chrome:
        DIRTY = '<span class="dirty"></span>'
        tabs = "".join(
            f'<div class="tab{" active" if l == lang else ""}">{LANGS[l]["file"]}'
            f'{DIRTY if l == lang else ""}</div>'
            for l in ("typescript", "python", "rust", "css", "json")
        )
        head = f'''<div class="titlebar">
      <span class="dot" style="background:var(--e-error)"></span>
      <span class="dot" style="background:var(--e-warning)"></span>
      <span class="dot" style="background:var(--e-success)"></span>
      <span class="path">dr-syntax / src / {spec["file"]}</span></div>
    <div class="tabs">{tabs}</div>'''
    foot = ""
    if chrome:
        foot = f'''<div class="statusbar"><span class="mode-chip">NORMAL</span>
      <span>main</span><span class="ok">✓ 0 problems</span><span class="warn">2 hints</span>
      <span class="spacer">{spec["label"]}</span><span>UTF-8</span></div>'''
    return (f'<div class="{cls}"{idattr}{style}>{head}'
            f'<div class="code">{code_block(lang, active, selected, source)}</div>{foot}</div>')


def render_chart(curves: dict) -> str:
    W, H, PAD_L, PAD_B, PAD_T = 720, 210, 40, 26, 14
    CMAX = 0.32
    pw, ph = W - PAD_L - 12, H - PAD_B - PAD_T
    x = lambda a: PAD_L + (a / 360) * pw
    y = lambda c: PAD_T + ph - (min(c, CMAX) / CMAX) * ph
    path = lambda pts: " ".join(
        f"{'M' if i == 0 else 'L'}{x(i * 5):.1f},{y(c):.1f}" for i, c in enumerate(pts))
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" class="chart" aria-label="Maximum reachable '
         f'chroma by hue angle, dark versus light">']
    for lo, hi, label in ((60, 120, "yellow"), (165, 240, "teal")):
        p.append(f'<rect x="{x(lo):.1f}" y="{PAD_T}" width="{x(hi)-x(lo):.1f}" '
                 f'height="{ph}" class="deadzone"/>')
        p.append(f'<text x="{(x(lo)+x(hi))/2:.1f}" y="{PAD_T+12}" class="chart-zone">{label}</text>')
    for c in (0.1, 0.2, 0.3):
        p.append(f'<line x1="{PAD_L}" y1="{y(c):.1f}" x2="{W-12}" y2="{y(c):.1f}" class="grid"/>')
        p.append(f'<text x="{PAD_L-8}" y="{y(c)+3:.1f}" class="chart-tick" text-anchor="end">{c:.1f}</text>')
    for a in (0, 90, 180, 270, 360):
        p.append(f'<text x="{x(a):.1f}" y="{H-8}" class="chart-tick" text-anchor="middle">{a}°</text>')
    p.append(f'<path d="{path(curves["dark"]["points"])}" class="curve curve-dark"/>')
    p.append(f'<path d="{path(curves["light"]["points"])}" class="curve curve-light"/>')
    for m in curves["light"]["marks"]:
        p.append(f'<circle cx="{x(m["angle"]):.1f}" '
                 f'cy="{y(curves["light"]["points"][int(round(m["angle"]/5)) % 72]):.1f}" '
                 f'r="3.2" class="mark"/>')
    p.append("</svg>")
    return "\n".join(p)


JS = """
const UI = __UIVARS__, SYN = __SYNVARS__;
const root = document.documentElement;

function applyVariant(key){
  const v = DATA[key];
  if (!v) return;
  for (const [n, c] of Object.entries(v.ui))  root.style.setProperty("--e-" + n, c);
  for (const [n, c] of Object.entries(v.syn)) root.style.setProperty("--e-" + n, c);

  document.querySelectorAll("[data-stat]").forEach(el => {
    const raw = v[el.dataset.stat];
    const fmt = el.dataset.fmt;
    el.textContent = fmt === "ratio" ? raw.toFixed(2) + ":1"
                   : fmt === "plane" ? "L " + raw.toFixed(3)
                   : String(raw);
  });
  document.querySelectorAll("[data-swatch]").forEach(el => {
    const c = (v.style && v.style[el.dataset.swatch]) || (v.syntaxAll && v.syntaxAll[el.dataset.swatch]);
    if (c) el.style.background = c;
  });
  document.querySelectorAll("[data-hex]").forEach(el => {
    const c = (v.style && v.style[el.dataset.hex]) || (v.syntaxAll && v.syntaxAll[el.dataset.hex]);
    if (c) el.textContent = c;
  });
  const hueBody = document.getElementById("hue-body");
  if (hueBody) hueBody.innerHTML = v.hues.map(h =>
    `<tr><td><span class="chip"><i style="background:${h.hex}"></i>` +
    `<span class="role">${h.label}</span></span></td>` +
    `<td class="mono">${h.role}</td><td class="mono num">${h.angle}\\u00b0</td>` +
    `<td class="mono num">${h.chroma.toFixed(3)}</td>` +
    `<td class="mono num">${h.ratio.toFixed(2)}:1</td></tr>`).join("");
  const vimBody = document.getElementById("vim-body");
  if (vimBody) vimBody.innerHTML = v.vim.map(m =>
    `<tr><td><span class="chip"><i style="background:${m.bg}"></i>` +
    `<code style="background:${m.bg};color:${m.fg}">${m.mode.replace(/_/g," ").toUpperCase()}</code>` +
    `</span></td><td class="mono">${m.bg.slice(0,7)}</td><td class="mono">${m.fg.slice(0,7)}</td>` +
    `<td class="mono num">${m.ratio.toFixed(2)}:1</td></tr>`).join("");
  ["ansi","ansiBright"].forEach(kind => {
    const g = document.getElementById(kind);
    if (g) g.innerHTML = v[kind].map(c => `<i style="background:${c}" title="${c}"></i>`).join("");
  });
  document.querySelectorAll("[data-variant-tabs] .tab-btn").forEach(b =>
    b.setAttribute("aria-selected", String(b.dataset.key === key)));
  try { localStorage.setItem("drsyntax-variant", key); } catch (e) {}
}

document.querySelectorAll("[data-variant-tabs] .tab-btn").forEach(b =>
  b.addEventListener("click", () => applyVariant(b.dataset.key)));

function applyLang(lang){
  document.querySelectorAll("[data-lang-panel]").forEach(el => {
    el.hidden = el.dataset.langPanel !== lang;
  });
  document.querySelectorAll("[data-lang-tabs] .tab-btn").forEach(b =>
    b.setAttribute("aria-selected", String(b.dataset.lang === lang)));
}
document.querySelectorAll("[data-lang-tabs] .tab-btn").forEach(b =>
  b.addEventListener("click", () => applyLang(b.dataset.lang)));

let start = "dark";
try { start = localStorage.getItem("drsyntax-variant") || "dark"; } catch (e) {}
applyVariant(DATA[start] ? start : "dark");
if (document.querySelector("[data-lang-tabs]")) applyLang("typescript");
"""


def site_js() -> str:
    return (JS.replace("__UIVARS__", json.dumps(list(UI_VARS.values())))
              .replace("__SYNVARS__", json.dumps(list(SYN_VARS.values()))))


def page(title: str, active: str, body: str, data: dict, *, desc: str) -> str:
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{html.escape(desc, quote=True)}">
<link rel="icon" href="{LOGO_SRC}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:ital,wght@0,400;0,500;0,700;1,400&display=swap">
<link rel="stylesheet" href="assets/site.css">
</head>
<body>
{nav(active)}
<main class="wrap">
{body}
</main>
<footer><div class="wrap">
  <span>Generated from <code>themes/dr-syntax.json</code>. Contrast measured on final 8-bit
  sRGB values.</span>
  <span><a href="{REPO}">Source</a> · MIT licensed</span>
</div></footer>
<script>const DATA = {json.dumps(data, separators=(",", ":"))};</script>
<script src="assets/site.js"></script>
</body>
</html>
'''


def variant_tabs(d: dict) -> str:
    btns = "".join(
        f'<button class="tab-btn" role="tab" data-key="{k}" '
        f'aria-selected="{"true" if k == "dark" else "false"}">{d[k]["short"]}</button>'
        for k in KEYS)
    return f'<div class="switch" data-variant-tabs role="tablist" aria-label="Variant">{btns}</div>'


def lang_tabs() -> str:
    btns = "".join(
        f'<button class="tab-btn" role="tab" data-lang="{l}" '
        f'aria-selected="{"true" if l == "typescript" else "false"}">{LANGS[l]["label"]}</button>'
        for l in LANGS)
    return f'<div class="switch" data-lang-tabs role="tablist" aria-label="Language">{btns}</div>'


READOUT = '''<dl class="readout">
  <div class="cell"><dt>Lightness plane</dt><dd data-stat="plane" data-fmt="plane">—</dd></div>
  <div class="cell"><dt>Min syntax contrast</dt><dd data-stat="minSyntax" data-fmt="ratio">—</dd></div>
  <div class="cell"><dt>Comments</dt><dd data-stat="comment" data-fmt="ratio">—</dd></div>
  <div class="cell"><dt>Plain code</dt><dd data-stat="foreground" data-fmt="ratio">—</dd></div>
  <div class="cell"><dt>Mean chroma</dt><dd data-stat="chroma">—</dd></div>
</dl>'''


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def page_index(d: dict) -> str:
    langs = "".join(
        f'<div data-lang-panel="{l}"{"" if l == "typescript" else " hidden"}>'
        f'{editor(l, active=19 if l == "typescript" else None, selected={19, 20} if l == "typescript" else None)}</div>'
        for l in LANGS)
    trio = "".join(f'''<figure>
      <figcaption><b>{d[k]["name"]}</b><span>{d[k]["editorBg"]} · {d[k]["minSyntax"]}:1</span></figcaption>
      {editor("typescript", fixed=d[k], compact=True, chrome=False,
              active=6, selected=TRIO_SEL, source=TRIO_SAMPLE)}
    </figure>''' for k in KEYS)
    return f'''<header class="hero">
  <img src="{logo_uri()}" alt="Dr. Syntax logo: a lab-coated doctor in code-lens sunglasses
    holding a syringe full of braces" width="168" height="168">
  <div class="hero-text">
    <p class="eyebrow">Zed theme family · three variants</p>
    <h1>Dr. Syntax</h1>
    <p class="lead">Built in OKLCH, where every syntax token shares one perceptual lightness
      plane and every colour is solved against a contrast floor rather than picked by eye.
      All 185 colour keys the Zed theme schema accepts, in Dark, OLED and Light.</p>
    <div class="cta">
      <a class="btn primary" href="#install">Install</a>
      <a class="btn" href="preview.html">Full preview</a>
      <a class="btn" href="{REPO}">GitHub</a>
    </div>
  </div>
</header>

<section>
  <div class="controls">
    <span class="switch-label">Variant</span>{variant_tabs(d)}
    <span class="switch-label">Language</span>{lang_tabs()}
  </div>
  {langs}
  <p class="note">Lines 19–20 are shown selected, over the active line, with a comment inside the
    selection — the state most themes quietly lose. Push the selection opacity up far enough to
    see it and the comment underneath stops being readable, so here the opacity is solved for the
    strongest overlay that still holds every token at 3.5:1.</p>
  {READOUT}
</section>

<section>
  <h2>The three variants, same code</h2>
  <p class="note">Not one palette inverted three ways. OLED pulls chroma back because
    high-chroma text blooms on emissive panels, and raises its contrast floor to 10.5:1 because
    against <code>#000</code> even murky text clears 7:1. Light rotates its hues out of the two
    regions of sRGB that collapse to mud at the lightness AAA demands.</p>
  <div class="trio">{trio}</div>
</section>

<section id="install">
  <h2>Install</h2>
  <p class="note">Zed loads themes from an extension directory. Until Dr. Syntax is in the
    extension store, install it as a dev extension — same result, one extra step.</p>
  <div class="steps">
    <div class="step"><p class="eyebrow">1 · Clone</p>
      <pre><code>git clone {REPO}</code></pre></div>
    <div class="step"><p class="eyebrow">2 · Load it</p>
      <p class="note"><kbd>cmd</kbd>+<kbd>shift</kbd>+<kbd>P</kbd> →
        <b>zed: install dev extension</b> → choose the cloned folder.</p></div>
    <div class="step"><p class="eyebrow">3 · Pick a variant</p>
      <p class="note"><kbd>cmd</kbd>+<kbd>shift</kbd>+<kbd>P</kbd> →
        <b>theme selector: toggle</b> → <i>Dr. Syntax Dark</i>, <i>OLED</i> or <i>Light</i>.</p></div>
  </div>
  <p class="note">Every claim on this site is reproducible from a checkout. Both scripts are
    standard-library Python and exit non-zero on failure:</p>
  <pre><code>python3 tools/build_theme.py --check   <span class="c"># 44 contrast assertions per variant</span>
python3 tools/validate_theme.py        <span class="c"># key coverage + 4,092 overlay measurements</span></code></pre>
</section>'''


def page_preview(d: dict) -> str:
    blocks = "".join(f'''<section>
  <h2>{LANGS[l]["label"]}</h2>
  {editor(l)}
</section>''' for l in LANGS)
    return f'''<section>
  <p class="eyebrow">Preview</p>
  <h1 style="font-size:34px">Every sample, every variant</h1>
  <p class="lead">Five languages, switchable across all three variants. The samples are real
    code — a theme is judged on the shapes it actually makes, not on a colour swatch.</p>
  <div class="controls"><span class="switch-label">Variant</span>{variant_tabs(d)}</div>
  {READOUT}
</section>
{blocks}

<section>
  <h2>Terminal</h2>
  <p class="note">The full 16-colour ANSI ramp plus dim variants, mapped onto the same eight
    hues so the terminal reads as part of the editor rather than a bolted-on palette.</p>
  <div class="term">
    <div class="row"><span style="color:var(--e-str)">➜</span>
 <span style="color:var(--e-prop)">dr-syntax</span> <span style="color:var(--e-kw)">git:(</span><span style="color:var(--e-num)">main</span><span style="color:var(--e-kw)">)</span> python3 tools/build_theme.py --check</div>
    <div class="row"><span style="color:var(--e-success)">[PASS]</span> Dr. Syntax Dark      44/44 assertions</div>
    <div class="row"><span style="color:var(--e-success)">[PASS]</span> Dr. Syntax OLED      44/44 assertions</div>
    <div class="row"><span style="color:var(--e-success)">[PASS]</span> Dr. Syntax Light     44/44 assertions</div>
    <div class="row"><span style="color:var(--e-warning)">warning</span>: 2 hints in oklch.ts</div>
    <div class="row"><span style="color:var(--e-error)">error</span>: nothing to fix</div>
    <div class="ansi-grid" id="ansi"></div>
    <div class="ansi-grid" id="ansiBright"></div>
  </div>
</section>

<section>
  <h2>Version control</h2>
  <p class="note">Diff hunk fills sit behind code, so they carry the same readability contract as
    a selection: Zed's own 0.16 fill opacity is used as the cap, with the solver free to pull it
    back if a token would drop below 3.5:1.</p>
  <div class="editor">
    <div class="code">
      <div class="code-line"><span class="gutter-num">41</span><span class="code-text">  <span class="t-kw">const</span> <span class="t-var">plane</span> <span class="t-punc">=</span> <span class="t-num">0.82</span><span class="t-punc">;</span></span></div>
      <div class="code-line" style="background:var(--e-vcdeleted);opacity:.999"><span class="gutter-num">42</span><span class="code-text" style="background:color-mix(in srgb, var(--e-vcdeleted) 16%, transparent)">- <span class="t-cmt">// picked by eye</span></span></div>
      <div class="code-line"><span class="gutter-num">43</span><span class="code-text" style="background:color-mix(in srgb, var(--e-added) 16%, transparent)">+ <span class="t-cmt">// solved against the contrast floor</span></span></div>
      <div class="code-line"><span class="gutter-num">44</span><span class="code-text">  <span class="t-kw">return</span> <span class="t-fn">solvePlane</span><span class="t-punc">(</span><span class="t-var">floor</span><span class="t-punc">);</span></span></div>
    </div>
  </div>
</section>

<section>
  <h2>Vim and Helix modes</h2>
  <p class="note">A mode chip carries its own label, so the contract is the label against the
    chip rather than against the editor. Each of the eight modes gets a neutral solved to 7:1 on
    its own background — which flips direction on the light variant.</p>
  <div class="table-scroll"><table>
    <thead><tr><th>Mode</th><th>Background</th><th>Label</th><th class="num">Contrast</th></tr></thead>
    <tbody id="vim-body"></tbody>
  </table></div>
</section>'''


def page_palette(d: dict) -> str:
    groups = []
    all_keys = list(d["dark"]["style"].keys())
    claimed: set[str] = set()
    for title, prefixes in KEY_GROUPS:
        keys = sorted(k for k in all_keys
                      if k not in claimed and any(k == p or k.startswith(p) for p in prefixes))
        claimed |= set(keys)
        if not keys:
            continue
        rows = "".join(
            f'<tr><td class="mono">{k}</td>'
            f'<td><span class="chip"><i data-swatch="{k}"></i>'
            f'<span class="mono" data-hex="{k}">—</span></span></td></tr>' for k in keys)
        groups.append(f'''<section>
  <h3>{title} <span class="mono">· {len(keys)} keys</span></h3>
  <div class="table-scroll"><table>
    <thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table></div>
</section>''')
    leftover = sorted(set(all_keys) - claimed)
    if leftover:
        rows = "".join(f'<tr><td class="mono">{k}</td><td><span class="chip">'
                       f'<i data-swatch="{k}"></i><span class="mono" data-hex="{k}">—</span>'
                       f'</span></td></tr>' for k in leftover)
        groups.append(f'''<section><h3>Other <span class="mono">· {len(leftover)} keys</span></h3>
  <div class="table-scroll"><table><thead><tr><th>Key</th><th>Value</th></tr></thead>
  <tbody>{rows}</tbody></table></div></section>''')

    syn_keys = sorted(d["dark"]["syntaxAll"].keys())
    syn_rows = "".join(
        f'<tr><td class="mono">{k}</td><td><span class="chip"><i data-swatch="{k}"></i>'
        f'<span class="mono" data-hex="{k}">—</span></span></td></tr>' for k in syn_keys)

    return f'''<section>
  <p class="eyebrow">Palette</p>
  <h1 style="font-size:34px">Every key, measured</h1>
  <p class="lead">All {len(all_keys)} colour keys the Zed theme schema accepts, plus
    {len(syn_keys)} syntax tokens. Switch variant and the whole reference re-reads from that
    variant's values.</p>
  <div class="controls"><span class="switch-label">Variant</span>{variant_tabs(d)}</div>
</section>

<section>
  <h2>The syntax plane</h2>
  <p class="note">One lightness for all eight hues, so nothing glows brighter than its
    neighbours. Chroma varies by hue because sRGB holds more of some hues than others; lightness
    is what must stay constant.</p>
  <div class="table-scroll"><table>
    <thead><tr><th>Token class</th><th>Hue</th><th class="num">Angle</th>
      <th class="num">Chroma</th><th class="num">Contrast</th></tr></thead>
    <tbody id="hue-body"></tbody>
  </table></div>
</section>

<section>
  <h2>Syntax tokens <span class="mono">· {len(syn_keys)} keys</span></h2>
  <div class="table-scroll"><table>
    <thead><tr><th>Token</th><th>Value</th></tr></thead><tbody>{syn_rows}</tbody></table></div>
</section>

<section>
  <h2>Interface keys <span class="mono">· {len(all_keys)} keys</span></h2>
</section>
{"".join(groups)}'''


def page_method(d: dict) -> str:
    return f'''<section>
  <p class="eyebrow">Method</p>
  <h1 style="font-size:34px">Derived, not picked</h1>
  <p class="lead">Most themes are a list of hex codes chosen by eye. That produces two problems
    you feel rather than see — and both are measurable, so both are solved rather than guessed.</p>
</section>

<section>
  <h2>Colours that look equal are not equal</h2>
  <p class="note">Two hex values with the same apparent brightness can differ by 30–40% in
    perceived lightness depending on hue, because human vision is far more sensitive to green
    than to blue. A “green” and a “blue” picked to match will not match, and your eye re-adapts
    every time it crosses one. Over a working day that is fatigue you cannot point at.</p>
  <p class="note">Dr. Syntax is authored in OKLCH, a perceptually uniform space, and every syntax
    token in a variant sits on one shared lightness plane.</p>
</section>

<section>
  <h2>The plane is solved, not chosen</h2>
  <p class="note">sRGB chroma varies sharply and non-obviously with lightness, so the plane that
    yields the most vivid palette is rarely where intuition puts it. The build searches for the
    lightness that maximises mean achievable chroma across all eight hues, subject to every hue
    clearing its contrast floor.</p>
  <p class="note">For the dark variant that returned L=0.737. The value picked by eye first was
    0.82 — which cost about 15% chroma for contrast headroom nothing needed.</p>
  {READOUT}
  <div class="controls"><span class="switch-label">Variant</span>{variant_tabs(d)}</div>
</section>

<section>
  <h2>Why Light is not Dark inverted</h2>
  <p class="note">Maximum chroma reachable at each variant's own lightness plane. At the
    lightness AAA demands on a light background, two regions of sRGB collapse: around 60–120°
    and 165–240°, colour can only reach roughly 0.08 chroma, which renders as mud. A naive
    inversion drops tokens straight into them. The dots mark where the Light variant actually
    sites its eight hues.</p>
  <div class="chart-wrap">
    <div class="legend">
      <span><i></i> Dark plane</span><span><i class="dash"></i> Light plane</span>
      <span><i class="zone"></i> Light dead zones</span><span>● Light hue positions</span>
    </div>
    {render_chart(chroma_curves())}
  </div>
  <p class="note">Siting the light hues outside those zones recovered 13% mean chroma and 47%
    hue separation. One honest limit remains: <code>function</code> on Light is a deep teal at
    chroma 0.075, the strongest that hue region holds at 7:1. Reaching a vivid cyan there would
    mean dropping to roughly 4.5:1. The floor was kept and the chroma given up.</p>
</section>

<section>
  <h2>The contracts</h2>
  <p class="note">The design states an intent and the lightness is solved by binary search to
    land on it. The build fails if any of these is missed.</p>
  <div class="table-scroll"><table>
    <thead><tr><th>State</th><th>Floor</th><th>Why</th></tr></thead>
    <tbody>
      <tr><td>Syntax, plain background</td><td class="mono">7:1</td><td class="role">WCAG AAA body text</td></tr>
      <tr><td>Comments</td><td class="mono">5.8:1</td><td class="role">Present, but recessive</td></tr>
      <tr><td>Inlay hints</td><td class="mono">6:1</td><td class="role">Read, not decoration — and must survive a selection</td></tr>
      <tr><td>Any token under a selection or search match</td><td class="mono">3.5:1</td><td class="role">Transient state; above WCAG's 3:1 non-text threshold</td></tr>
      <tr><td>Vim mode label on its chip</td><td class="mono">7:1</td><td class="role">The chip carries its own label</td></tr>
      <tr><td>Perceptual gap between any two token hues</td><td class="mono">0.050</td><td class="role">Oklab distance; below this two colours start to blur</td></tr>
    </tbody>
  </table></div>
</section>

<section>
  <h2>Verify it yourself</h2>
  <p class="note"><code>build_theme.py</code> runs 44 contrast assertions per variant and refuses
    to write the theme if any fail. <code>validate_theme.py</code> checks the shipped JSON
    independently of the generator — structure, colour format, key coverage against the schema's
    own key set, and 4,092 token-on-overlay contrast measurements re-derived from the JSON
    alone — so a bug in the generator cannot vouch for its own output.</p>
  <pre><code>python3 tools/build_theme.py --check
python3 tools/validate_theme.py</code></pre>
</section>'''


def main() -> int:
    assets = OUT / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (OUT / ".nojekyll").write_text("")
    (assets / "site.css").write_text(CSS.strip() + "\n", encoding="utf-8")
    (assets / "site.js").write_text(site_js().strip() + "\n", encoding="utf-8")
    # The logo is a static asset of the site, committed under website/assets/,
    # not a build product - so it is checked for, never regenerated.
    for required in ("dr-syntax-logo.webp", "dr-syntax-logo.png"):
        if not (assets / required).exists():
            raise SystemExit(f"missing site asset: website/assets/{required}")
    slim, full = variant_data(False), variant_data(True)
    built = [
        ("index.html", "Dr. Syntax", page_index(slim), slim,
         "A Zed theme family in Dark, OLED and Light. Built in OKLCH, verified against WCAG "
         "contrast floors, covering all 185 colour keys the Zed theme schema accepts."),
        ("preview.html", "Preview · Dr. Syntax", page_preview(slim), slim,
         "Five languages across all three Dr. Syntax variants, plus terminal, diff and Vim mode "
         "colours."),
        ("palette.html", "Palette · Dr. Syntax", page_palette(full), full,
         "Every one of the 185 Zed theme colour keys and 62 syntax tokens in Dr. Syntax, with "
         "measured contrast."),
        ("method.html", "Method · Dr. Syntax", page_method(slim), slim,
         "How Dr. Syntax is built: OKLCH lightness planes, solved contrast floors, and the sRGB "
         "gamut limits that shape the light variant."),
    ]
    for filename, title, body, data, desc in built:
        html_text = page(title, filename, body, data, desc=desc)
        (OUT / filename).write_text(html_text, encoding="utf-8")
        print(f"  {filename:<16} {len(html_text):>8,} bytes")
    for a in sorted(assets.iterdir()):
        print(f"  assets/{a.name:<24} {a.stat().st_size:>8,} bytes")
    print(f"Wrote {len(built)} pages to {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

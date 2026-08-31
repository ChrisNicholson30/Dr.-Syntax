#!/usr/bin/env python3
"""
Generate docs/preview.html - a calibration sheet for the Dr. Syntax family.

Colours are read out of themes/dr-syntax.json rather than restated here, so the
preview cannot drift from what actually ships. Run after build_theme.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_theme import (  # noqa: E402
    HUE, HUE_OVERRIDES, SYNTAX_HUES, Palette, contrast, gamut_fit_chroma, oklch,
)

THEME = json.loads((ROOT / "themes" / "dr-syntax.json").read_text())
OUT = ROOT / "docs" / "preview.html"

KEYS = ("dark", "oled", "light")
ROLE_LABEL = {
    "rose": "keyword · control flow",
    "orchid": "tag · namespace · title",
    "violet": "attribute · preprocessor",
    "azure": "property · member",
    "cyan": "function · method",
    "jade": "string · literal text",
    "amber": "type · class · enum",
    "tangerine": "number · boolean · constant",
}

# --------------------------------------------------------------------------
# Data pulled from the shipped theme
# --------------------------------------------------------------------------

def variant_data() -> dict:
    out = {}
    for key, theme in zip(KEYS, THEME["themes"]):
        s = theme["style"]
        p = Palette(key)
        ed = p.editor_rgb
        out[key] = {
            "name": theme["name"],
            "appearance": theme["appearance"],
            "ui": {
                "bg": s["background"], "editor": s["editor.background"],
                "elevated": s["elevated_surface.background"],
                "titlebar": s["title_bar.background"], "tabbar": s["tab_bar.background"],
                "tabActive": s["tab.active_background"],
                "tabInactive": s["tab.inactive_background"],
                "statusbar": s["status_bar.background"],
                "border": s["border"], "borderVariant": s["border.variant"],
                "text": s["text"], "textMuted": s["text.muted"],
                "fg": s["editor.foreground"],
                "lineNumber": s["editor.line_number"],
                "activeLineNumber": s["editor.active_line_number"],
                "activeLine": s["editor.active_line.background"],
                "indentGuide": s["editor.indent_guide"],
                "selection": s["players"][0]["selection"],
                "cursor": s["players"][0]["cursor"],
                "match": s["search.match_background"],
                "accent": s["text.accent"],
                "error": s["error"], "warning": s["warning"], "success": s["success"],
                "added": s["version_control.added"],
                "modified": s["version_control.modified"],
            },
            "syntax": {t: s["syntax"][t]["color"] for t in s["syntax"]},
            "plane": round(p.syn_L, 3),
            "selectionAlpha": round(p.selection_alpha, 3),
            "minSyntax": round(min(contrast(p.hue[h].rgb, ed) for h in SYNTAX_HUES), 2),
            "comment": round(contrast(p.comment.rgb, ed), 2),
            "foreground": round(contrast(p.editor_fg.rgb, ed), 2),
            "hues": [
                {
                    "role": h, "label": ROLE_LABEL[h], "hex": p.hue[h].hex()[:7],
                    "angle": round(p.hues[h]), "chroma": round(p.hue[h].C, 3),
                    "ratio": round(contrast(p.hue[h].rgb, ed), 2),
                }
                for h in SYNTAX_HUES
            ],
        }
    return out


def chroma_curves() -> dict:
    """Max chroma reachable at the AAA floor, by hue - the light dead-zone evidence."""
    curves = {}
    for key in ("dark", "light"):
        p = Palette(key)
        pts = []
        for angle in range(0, 361, 5):
            a = angle % 360
            L = p.syn_L
            pts.append(round(gamut_fit_chroma(L, 0.40, float(a)), 4))
        curves[key] = {
            "points": pts,
            "plane": round(p.syn_L, 3),
            "marks": [{"role": r, "angle": round(p.hues[r])} for r in SYNTAX_HUES],
        }
    return curves


# --------------------------------------------------------------------------
# The code sample. Written once, coloured by whichever variant is selected.
# --------------------------------------------------------------------------

def T(cls: str, text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<span class="t-{cls}">{text}</span>' if cls else text


SAMPLE = [
    [("kw", "import"), ("", " "), ("punc", "{"), ("", " "), ("var", "clamp"),
     ("punc", ","), ("", " "), ("kw", "type"), ("", " "), ("typ", "Vec3"), ("", " "),
     ("punc", "}"), ("", " "), ("kw", "from"), ("", " "), ("str", '"./math"'), ("punc", ";")],
    [],
    [("cmt", "/** Convert an OKLCH triplet to linear sRGB. */")],
    [("kw", "export"), ("", " "), ("kw", "interface"), ("", " "), ("typ", "Oklch"), ("", " "), ("punc", "{")],
    [("", "  "), ("prop", "lightness"), ("punc", ":"), ("", " "), ("typ", "number"), ("punc", ";")],
    [("", "  "), ("prop", "chroma"), ("punc", ":"), ("", " "), ("typ", "number"), ("punc", ";")],
    [("", "  "), ("prop", "hue"), ("punc", ":"), ("", " "), ("typ", "number"), ("punc", ";")],
    [("punc", "}")],
    [],
    [("kw", "const"), ("", " "), ("var", "LMS_TO_RGB"), ("", " "), ("punc", "="), ("", " "), ("punc", "[")],
    [("", "  "), ("punc", "["), ("num", "4.0767416621"), ("punc", ","), ("", "  "),
     ("num", "-3.3077115913"), ("punc", ","), ("", "  "), ("num", "0.2309699292"), ("punc", "],")],
    [("", "  "), ("punc", "["), ("num", "-1.2684380046"), ("punc", ","), ("", "  "),
     ("num", "2.6097574011"), ("punc", ","), ("", " "), ("num", "-0.3413193965"), ("punc", "],")],
    [("punc", "]"), ("", " "), ("kw", "as"), ("", " "), ("kw", "const"), ("punc", ";")],
    [],
    [("kw", "export"), ("", " "), ("kw", "function"), ("", " "), ("fndef", "toLinearSrgb"),
     ("punc", "("), ("var", "colour"), ("punc", ":"), ("", " "), ("typ", "Oklch"),
     ("punc", ")"), ("punc", ":"), ("", " "), ("typ", "Vec3"), ("", " "), ("punc", "{")],
    [("", "  "), ("kw", "const"), ("", " "), ("punc", "{"), ("", " "), ("var", "chroma"),
     ("punc", ","), ("", " "), ("var", "hue"), ("", " "), ("punc", "}"), ("", " "),
     ("punc", "="), ("", " "), ("var", "colour"), ("punc", ";")],
    [("", "  "), ("kw", "const"), ("", " "), ("var", "rad"), ("", " "), ("punc", "="),
     ("", " "), ("punc", "("), ("var", "hue"), ("", " "), ("punc", "*"), ("", " "),
     ("typ", "Math"), ("punc", "."), ("prop", "PI"), ("punc", ")"), ("", " "),
     ("punc", "/"), ("", " "), ("num", "180"), ("punc", ";")],
    [],
    [("", "  "), ("cmt", "// Cube each component before the matrix transform.")],
    [("", "  "), ("kw", "const"), ("", " "), ("var", "lms"), ("", " "), ("punc", "="),
     ("", " "), ("var", "channels"), ("punc", "."), ("fn", "map"), ("punc", "(("),
     ("var", "v"), ("punc", ")"), ("", " "), ("punc", "=>"), ("", " "), ("var", "v"),
     ("", " "), ("punc", "**"), ("", " "), ("num", "3"), ("punc", ");")],
    [],
    [("", "  "), ("kw", "if"), ("", " "), ("punc", "("), ("punc", "!"), ("fn", "inGamut"),
     ("punc", "("), ("var", "lms"), ("punc", "))"), ("", " "), ("punc", "{")],
    [("", "    "), ("kw", "throw"), ("", " "), ("kw", "new"), ("", " "), ("typ", "RangeError"),
     ("punc", "("), ("str", "`hue "), ("esc", "${"), ("var", "hue"), ("esc", "}"),
     ("str", " is outside sRGB`"), ("punc", ");")],
    [("", "  "), ("punc", "}")],
    [],
    [("", "  "), ("kw", "return"), ("", " "), ("var", "LMS_TO_RGB"), ("punc", "."),
     ("fn", "map"), ("punc", "(("), ("var", "row"), ("punc", ")"), ("", " "),
     ("punc", "=>"), ("", " "), ("fn", "dot"), ("punc", "("), ("var", "row"),
     ("punc", ","), ("", " "), ("var", "lms"), ("punc", "));")],
    [("punc", "}")],
    [],
    [("kw", "export"), ("", " "), ("kw", "const"), ("", " "), ("fndef", "inGamut"),
     ("", " "), ("punc", "="), ("", " "), ("punc", "("), ("var", "v"), ("punc", ":"),
     ("", " "), ("typ", "Vec3"), ("punc", ")"), ("punc", ":"), ("", " "),
     ("typ", "boolean"), ("", " "), ("punc", "=>")],
    # Written as literal characters - T() does the escaping; pre-escaping here
    # would be escaped a second time and render as "&gt;" on the page.
    [("", "  "), ("var", "v"), ("punc", "."), ("fn", "every"), ("punc", "(("),
     ("var", "c"), ("punc", ")"), ("", " "), ("punc", "=>"), ("", " "), ("var", "c"),
     ("", " "), ("punc", ">="), ("", " "), ("num", "-1e-6"), ("", " "),
     ("punc", "&&"), ("", " "), ("var", "c"), ("", " "), ("punc", "<="),
     ("", " "), ("num", "1"), ("punc", ");")],
]

ACTIVE_LINE = 19          # 1-indexed: the comment line, so the active line is visible under it
SELECTED_LINES = {19, 20}  # a selection spanning a comment - the state most themes lose


def render_code() -> str:
    rows = []
    for i, line in enumerate(SAMPLE, start=1):
        body = "".join(T(cls, txt) for cls, txt in line) if line else "&nbsp;"
        classes = ["code-line"]
        if i == ACTIVE_LINE:
            classes.append("is-active")
        if i in SELECTED_LINES:
            classes.append("is-selected")
        num_cls = "gutter-num is-active" if i == ACTIVE_LINE else "gutter-num"
        rows.append(
            f'<div class="{" ".join(classes)}">'
            f'<span class="{num_cls}">{i}</span>'
            f'<span class="code-text">{body}</span></div>'
        )
    return "\n".join(rows)


def render_chart(curves: dict) -> str:
    """Max chroma reachable by hue, dark vs light - the evidence for the hue rotation."""
    W, H, PAD_L, PAD_B, PAD_T = 720, 210, 40, 26, 14
    CMAX = 0.32
    plot_w, plot_h = W - PAD_L - 12, H - PAD_B - PAD_T

    def x(angle: float) -> float:
        return PAD_L + (angle / 360) * plot_w

    def y(c: float) -> float:
        return PAD_T + plot_h - (min(c, CMAX) / CMAX) * plot_h

    def path(points: list[float]) -> str:
        return " ".join(
            f"{'M' if i == 0 else 'L'}{x(i * 5):.1f},{y(c):.1f}"
            for i, c in enumerate(points)
        )

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Maximum reachable '
             f'chroma by hue angle, dark versus light" class="chart">']
    # dead zones for the light gamut
    for lo, hi, label in ((60, 120, "yellow"), (165, 240, "teal")):
        parts.append(f'<rect x="{x(lo):.1f}" y="{PAD_T}" width="{x(hi)-x(lo):.1f}" '
                     f'height="{plot_h}" class="deadzone"/>')
        parts.append(f'<text x="{(x(lo)+x(hi))/2:.1f}" y="{PAD_T+12}" '
                     f'class="chart-zone">{label}</text>')
    # grid
    for c in (0.1, 0.2, 0.3):
        parts.append(f'<line x1="{PAD_L}" y1="{y(c):.1f}" x2="{W-12}" y2="{y(c):.1f}" class="grid"/>')
        parts.append(f'<text x="{PAD_L-8}" y="{y(c)+3:.1f}" class="chart-tick" '
                     f'text-anchor="end">{c:.1f}</text>')
    for a in (0, 90, 180, 270, 360):
        parts.append(f'<text x="{x(a):.1f}" y="{H-8}" class="chart-tick" '
                     f'text-anchor="middle">{a}°</text>')
    parts.append(f'<path d="{path(curves["dark"]["points"])}" class="curve curve-dark"/>')
    parts.append(f'<path d="{path(curves["light"]["points"])}" class="curve curve-light"/>')
    # where the light variant actually sites its hues
    for m in curves["light"]["marks"]:
        cx = x(m["angle"])
        cy = y(curves["light"]["points"][int(round(m["angle"] / 5)) % 72])
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.2" class="mark"/>')
    parts.append("</svg>")
    return "\n".join(parts)


CSS = """
:root{
  --ground:#f4f5f9; --surface:#ffffff; --raised:#eceef5;
  --ink:#191b22; --muted:#5a6072; --faint:#878ca0;
  --rule:#e0e3ec; --rule-strong:#c9cddb;
  --accent:#4538b6; --accent-soft:#eceafb;
  --shadow:0 1px 2px rgba(20,22,40,.05), 0 12px 32px -18px rgba(20,22,40,.35);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#0b0c10; --surface:#12141a; --raised:#181b23;
    --ink:#e2e4ec; --muted:#8b90a3; --faint:#666b7d;
    --rule:#22252f; --rule-strong:#333743;
    --accent:#9d9eff; --accent-soft:#1b1c2e;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 12px 34px -18px rgba(0,0,0,.8);
  }
}
:root[data-theme="dark"]{
  --ground:#0b0c10; --surface:#12141a; --raised:#181b23;
  --ink:#e2e4ec; --muted:#8b90a3; --faint:#666b7d;
  --rule:#22252f; --rule-strong:#333743;
  --accent:#9d9eff; --accent-soft:#1b1c2e;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 12px 34px -18px rgba(0,0,0,.8);
}

*{box-sizing:border-box;}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.6; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1080px; margin:0 auto; padding:40px 28px 96px;
  display:flex; flex-direction:column; gap:44px;}

.eyebrow{
  font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:11px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--faint); margin:0;
}

/* ---- masthead ---- */
.masthead{display:flex; flex-direction:column; gap:18px;
  border-bottom:1px solid var(--rule); padding-bottom:26px;}
.title-row{display:flex; flex-wrap:wrap; align-items:baseline; gap:16px;}
h1{font-size:clamp(30px,5vw,44px); line-height:1.05; margin:0; letter-spacing:-.025em;
  font-weight:600; text-wrap:balance;}
.standfirst{margin:0; max-width:60ch; color:var(--muted); font-size:16px;}
.spec-line{display:flex; flex-wrap:wrap; gap:8px 22px;}
.spec-line span{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:11.5px;
  letter-spacing:.06em; color:var(--faint);}
.spec-line b{color:var(--ink); font-weight:500;}

/* ---- variant switcher ---- */
.switch{display:flex; gap:4px; padding:4px; border:1px solid var(--rule);
  border-radius:9px; background:var(--surface); width:fit-content;}
.switch button{
  font:inherit; font-size:13px; font-weight:500; cursor:pointer;
  padding:7px 15px; border:0; border-radius:6px; background:transparent;
  color:var(--muted); transition:background .16s ease, color .16s ease;
}
.switch button:hover{color:var(--ink); background:var(--raised);}
.switch button[aria-selected="true"]{background:var(--accent); color:var(--ground);}
.switch button:focus-visible{outline:2px solid var(--accent); outline-offset:2px;}

/* ---- editor mock: a fixed island, painted entirely by the theme ---- */
.editor{
  border-radius:11px; overflow:hidden; border:1px solid var(--e-border);
  box-shadow:var(--shadow); background:var(--e-editor);
  font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:13px; line-height:1.62;
  transition:background .22s ease, border-color .22s ease;
}
.titlebar{display:flex; align-items:center; gap:8px; padding:9px 13px;
  background:var(--e-titlebar); border-bottom:1px solid var(--e-borderv);}
.dot{width:10px; height:10px; border-radius:50%;}
.titlebar .path{margin-left:8px; font-size:11.5px; color:var(--e-muted);}
.tabs{display:flex; background:var(--e-tabbar); border-bottom:1px solid var(--e-borderv);}
.tab{padding:8px 16px; font-size:12px; color:var(--e-muted);
  background:var(--e-tabinactive); border-right:1px solid var(--e-borderv);
  display:flex; align-items:center; gap:7px;}
.tab.active{background:var(--e-tabactive); color:var(--e-text);}
.tab .dirty{width:6px; height:6px; border-radius:50%; background:var(--e-modified);}
.code{padding:12px 0; overflow-x:auto;}
.code-line{display:flex; padding:0 14px 0 0; position:relative; white-space:pre;}
.code-line.is-active{background:var(--e-activeline);}
.code-line.is-selected .code-text{
  background:var(--e-selection); box-shadow:0 0 0 0 var(--e-selection);
}
.gutter-num{flex:0 0 52px; text-align:right; padding-right:16px;
  color:var(--e-linenum); user-select:none;}
.gutter-num.is-active{color:var(--e-activelinenum);}
.code-text{color:var(--e-fg);}
.code-line.is-active .code-text::after{
  content:""; position:absolute; width:2px; height:1.62em; top:0;
  background:var(--e-cursor); animation:blink 1.1s step-end infinite;
}
@keyframes blink{50%{opacity:0;}}
.statusbar{display:flex; gap:18px; padding:6px 14px; background:var(--e-statusbar);
  border-top:1px solid var(--e-borderv); font-size:11px; color:var(--e-muted);}
.statusbar .ok{color:var(--e-success);} .statusbar .warn{color:var(--e-warning);}
.statusbar .spacer{margin-left:auto;}
.t-kw{color:var(--e-kw);} .t-fn{color:var(--e-fn);}
.t-fndef{color:var(--e-fn); font-weight:700;}
.t-str{color:var(--e-str);} .t-typ{color:var(--e-typ);}
.t-num{color:var(--e-num);} .t-prop{color:var(--e-prop);}
.t-cmt{color:var(--e-cmt); font-style:italic;}
.t-punc{color:var(--e-punc);} .t-var{color:var(--e-fg);}
.t-esc{color:var(--e-esc);}

/* ---- readout ---- */
.readout{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule); border-radius:9px; overflow:hidden;}
.cell{background:var(--surface); padding:13px 16px;}
.cell dt{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:10.5px;
  letter-spacing:.1em; text-transform:uppercase; color:var(--faint); margin:0 0 5px;}
.cell dd{margin:0; font-size:20px; font-weight:600; letter-spacing:-.02em;
  font-variant-numeric:tabular-nums;}
.cell .unit{font-size:12px; font-weight:400; color:var(--muted);}

section{display:flex; flex-direction:column; gap:16px;}
h2{font-size:20px; margin:0; font-weight:600; letter-spacing:-.015em;}
.note{margin:0; max-width:68ch; color:var(--muted); font-size:14.5px;}
.note code{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:12.5px;
  background:var(--raised); padding:1px 5px; border-radius:4px; color:var(--ink);}

/* ---- hue table ---- */
.table-scroll{overflow-x:auto; border:1px solid var(--rule); border-radius:9px;
  background:var(--surface);}
table{border-collapse:collapse; width:100%; min-width:600px;}
th{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:10.5px;
  letter-spacing:.1em; text-transform:uppercase; color:var(--faint);
  text-align:left; padding:11px 14px; border-bottom:1px solid var(--rule); font-weight:500;}
td{padding:10px 14px; border-bottom:1px solid var(--rule); font-size:13.5px;}
tr:last-child td{border-bottom:0;}
td.mono{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:12.5px;
  font-variant-numeric:tabular-nums; color:var(--muted);}
th.num,td.num{text-align:right;}
.chip{display:inline-flex; align-items:center; gap:9px;}
.chip i{width:15px; height:15px; border-radius:4px; flex:none;
  box-shadow:inset 0 0 0 1px rgba(128,128,128,.28);}
.role{color:var(--muted); font-size:12.5px;}

/* ---- chart ---- */
.chart{width:100%; height:auto; display:block;}
.chart-wrap{border:1px solid var(--rule); border-radius:9px; background:var(--surface);
  padding:16px 12px 8px;}
.deadzone{fill:var(--accent); opacity:.07;}
.grid{stroke:var(--rule-strong); stroke-width:1; stroke-dasharray:2 4;}
.chart-tick,.chart-zone{font-family:"JetBrains Mono",ui-monospace,monospace;
  font-size:9.5px; fill:var(--faint); letter-spacing:.08em;}
.chart-zone{text-transform:uppercase;}
.curve{fill:none; stroke-width:2; stroke-linejoin:round;}
.curve-dark{stroke:var(--accent);}
.curve-light{stroke:var(--ink); stroke-dasharray:5 4; opacity:.55;}
.mark{fill:var(--ink);}
.legend{display:flex; flex-wrap:wrap; gap:18px; padding:0 4px 6px;}
.legend span{display:inline-flex; align-items:center; gap:7px; font-size:12px; color:var(--muted);}
.legend i{width:16px; height:2px; background:var(--accent);}
.legend i.dash{background:repeating-linear-gradient(90deg,var(--ink) 0 5px,transparent 5px 9px);
  opacity:.55;}
.legend i.zone{width:14px; height:11px; background:var(--accent); opacity:.14; border-radius:2px;}

footer{border-top:1px solid var(--rule); padding-top:22px; color:var(--faint); font-size:13px;}
footer a{color:var(--accent);}

@media (prefers-reduced-motion:reduce){
  *{animation-duration:.001ms !important; transition-duration:.001ms !important;}
}
@media (max-width:640px){
  .wrap{padding:28px 16px 64px; gap:34px;}
  .gutter-num{flex-basis:40px; padding-right:11px;}
  .editor{font-size:12px;}
}
"""


TEMPLATE = """<title>Dr. Syntax</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:ital,wght@0,400;0,500;0,700;1,400&display=swap">
<style>__CSS__</style>

<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">Zed theme family · calibration sheet</p>
    <div class="title-row">
      <h1>Dr. Syntax</h1>
    </div>
    <p class="standfirst">Three variants built in OKLCH, where every syntax token shares one
      perceptual lightness plane and every colour is solved against a contrast floor rather than
      picked by eye.</p>
    <div class="spec-line">
      <span>plane <b id="s-plane">—</b></span>
      <span>min syntax contrast <b id="s-min">—</b></span>
      <span>comments <b id="s-cmt">—</b></span>
      <span>plain code <b id="s-fg">—</b></span>
      <span>selection α <b id="s-alpha">—</b></span>
    </div>
    <div class="switch" role="tablist" aria-label="Theme variant">__TABS__</div>
  </header>

  <section>
    <div class="editor" id="editor" style="__EDITORVARS__">
      <div class="titlebar">
        <span class="dot" style="background:var(--e-error)"></span>
        <span class="dot" style="background:var(--e-warning)"></span>
        <span class="dot" style="background:var(--e-success)"></span>
        <span class="path">dr-syntax / src / colour / oklch.ts</span>
      </div>
      <div class="tabs">
        <div class="tab active">oklch.ts<span class="dirty"></span></div>
        <div class="tab">gamut.ts</div>
        <div class="tab">palette.json</div>
      </div>
      <div class="code">__CODE__</div>
      <div class="statusbar">
        <span>main</span><span class="ok">✓ 0 problems</span>
        <span class="warn">2 hints</span>
        <span class="spacer">TypeScript</span><span>Ln 19, Col 3</span><span>UTF-8</span>
      </div>
    </div>
    <p class="note">Lines 19–20 are shown selected, over the active line, with a comment inside
      the selection. That is the state most themes quietly lose — push the selection opacity up
      far enough to see it and the comment underneath stops being readable. Here the opacity is
      solved for the strongest overlay that still holds every token at 3.5:1.</p>
  </section>

  <section>
    <h2>The syntax plane</h2>
    <p class="note">One lightness for all eight hues, so nothing glows brighter than its
      neighbours. The plane itself is solved — the lightness that maximises mean reachable chroma
      subject to the contrast floor — not chosen. Chroma varies by hue because sRGB simply holds
      more of some hues than others; lightness is what must stay constant.</p>
    <div class="table-scroll">
      <table>
        <thead><tr>
          <th>Token class</th><th>Hue</th><th class="num">Angle</th>
          <th class="num">Chroma</th><th class="num">Contrast</th>
        </tr></thead>
        <tbody id="hue-body"></tbody>
      </table>
    </div>
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
        <span><i></i> Dark plane</span>
        <span><i class="dash"></i> Light plane</span>
        <span><i class="zone"></i> Light dead zones</span>
        <span>● Light hue positions</span>
      </div>
      __CHART__
    </div>
  </section>

  <footer>
    <p>Generated from <code>themes/dr-syntax.json</code>. Contrast measured on final 8-bit sRGB
    values, against each variant's own editor background.</p>
  </footer>
</div>

<script>
const DATA = __DATA__;
const UI_VARS = {bg:"bg",editor:"editor",elevated:"elevated",titlebar:"titlebar",tabbar:"tabbar",
  tabActive:"tabactive",tabInactive:"tabinactive",statusbar:"statusbar",border:"border",
  borderVariant:"borderv",text:"text",textMuted:"muted",fg:"fg",lineNumber:"linenum",
  activeLineNumber:"activelinenum",activeLine:"activeline",indentGuide:"indentguide",
  selection:"selection",cursor:"cursor",match:"match",accent:"accent",error:"error",
  warning:"warning",success:"success",added:"added",modified:"modified"};
const SYN_VARS = {keyword:"kw",function:"fn",string:"str",type:"typ",number:"num",
  property:"prop",comment:"cmt",punctuation:"punc","string.escape":"esc"};

const editor = document.getElementById("editor");
const body = document.getElementById("hue-body");

function apply(key){
  const v = DATA[key];
  for (const [k, name] of Object.entries(UI_VARS)) editor.style.setProperty("--e-"+name, v.ui[k]);
  for (const [tok, name] of Object.entries(SYN_VARS)) editor.style.setProperty("--e-"+name, v.syntax[tok]);
  document.getElementById("s-plane").textContent = "L " + v.plane.toFixed(3);
  document.getElementById("s-min").textContent = v.minSyntax.toFixed(2) + ":1";
  document.getElementById("s-cmt").textContent = v.comment.toFixed(2) + ":1";
  document.getElementById("s-fg").textContent = v.foreground.toFixed(2) + ":1";
  document.getElementById("s-alpha").textContent = v.selectionAlpha.toFixed(3);
  body.innerHTML = v.hues.map(h =>
    `<tr><td><span class="chip"><i style="background:${h.hex}"></i>` +
    `<span class="role">${h.label}</span></span></td>` +
    `<td class="mono">${h.role}</td><td class="mono num">${h.angle}°</td>` +
    `<td class="mono num">${h.chroma.toFixed(3)}</td>` +
    `<td class="mono num">${h.ratio.toFixed(2)}:1</td></tr>`).join("");
  document.querySelectorAll(".switch button").forEach(b =>
    b.setAttribute("aria-selected", String(b.dataset.key === key)));
}
document.querySelectorAll(".switch button").forEach(b =>
  b.addEventListener("click", () => apply(b.dataset.key)));
apply("dark");
</script>
"""


UI_VARS = {"bg": "bg", "editor": "editor", "elevated": "elevated", "titlebar": "titlebar",
           "tabbar": "tabbar", "tabActive": "tabactive", "tabInactive": "tabinactive",
           "statusbar": "statusbar", "border": "border", "borderVariant": "borderv",
           "text": "text", "textMuted": "muted", "fg": "fg", "lineNumber": "linenum",
           "activeLineNumber": "activelinenum", "activeLine": "activeline",
           "indentGuide": "indentguide", "selection": "selection", "cursor": "cursor",
           "match": "match", "accent": "accent", "error": "error", "warning": "warning",
           "success": "success", "added": "added", "modified": "modified"}
SYN_VARS = {"keyword": "kw", "function": "fn", "string": "str", "type": "typ",
            "number": "num", "property": "prop", "comment": "cmt",
            "punctuation": "punc", "string.escape": "esc"}


def editor_vars(v: dict) -> str:
    """Inline the default variant so the editor renders before, and without, JS."""
    parts = [f"--e-{name}:{v['ui'][k]}" for k, name in UI_VARS.items()]
    parts += [f"--e-{name}:{v['syntax'][tok]}" for tok, name in SYN_VARS.items()]
    return ";".join(parts)


def main() -> int:
    data = variant_data()
    tabs = "".join(
        f'<button role="tab" data-key="{k}" aria-selected="{"true" if k == "dark" else "false"}">'
        f'{data[k]["name"].replace("Dr. Syntax ", "")}</button>'
        for k in KEYS
    )
    html = (TEMPLATE
            .replace("__CSS__", CSS)
            .replace("__TABS__", tabs)
            .replace("__CODE__", render_code())
            .replace("__CHART__", render_chart(chroma_curves()))
            .replace("__EDITORVARS__", editor_vars(data["dark"]))
            .replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

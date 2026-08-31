#!/usr/bin/env python3
"""
Dr. Syntax - Zed theme generator.

This file is the single source of truth for the Dr. Syntax palette.

Design method
-------------
Colours are authored in OKLCH rather than hex. Two consequences matter:

1. Perceptual uniformity. Every syntax token in a variant is placed on one
   shared lightness plane (`syn_L`), so no token appears to "glow" brighter
   than its neighbours. Picking hex by eye cannot achieve this - sRGB hex
   values with the same nominal brightness differ by up to ~40% in perceived
   lightness across hues.

2. Derived, not guessed, contrast. Lightness values for text roles are solved
   by binary search against a declared WCAG contrast target. The design states
   an intent ("comments sit at 5:1 - present but recessive") and the maths
   produces the colour.

Chroma is gamut-mapped into sRGB by reducing chroma while holding lightness
and hue, so a requested colour never clips to a different-looking one.

Every generated colour is verified against its contrast floor before the theme
is written. A violation fails the build.

Usage
-----
    python3 tools/build_theme.py            # write themes/ + docs/PALETTE.md
    python3 tools/build_theme.py --check    # verify only; non-zero exit on failure
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME_PATH = ROOT / "themes" / "dr-syntax.json"
PALETTE_DOC = ROOT / "docs" / "PALETTE.md"

SCHEMA = "https://zed.dev/schema/themes/v0.2.0.json"
FAMILY = "Dr. Syntax"
AUTHOR = "Christopher Nicholson"


# --------------------------------------------------------------------------
# Colour science
# --------------------------------------------------------------------------

def _oklab_to_linear_srgb(L: float, a: float, b: float) -> tuple[float, float, float]:
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )


def _linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


_EPS = 1e-6


def _in_gamut(lin: tuple[float, float, float]) -> bool:
    return all(-_EPS <= v <= 1.0 + _EPS for v in lin)


def _lin_for(L: float, C: float, H: float) -> tuple[float, float, float]:
    rad = math.radians(H)
    return _oklab_to_linear_srgb(L, C * math.cos(rad), C * math.sin(rad))


def gamut_fit_chroma(L: float, C: float, H: float) -> float:
    """Largest chroma <= C that keeps (L, ., H) inside sRGB."""
    if _in_gamut(_lin_for(L, C, H)):
        return C
    lo, hi = 0.0, C
    for _ in range(40):
        mid = (lo + hi) / 2
        if _in_gamut(_lin_for(L, mid, H)):
            lo = mid
        else:
            hi = mid
    return lo


@dataclass(frozen=True)
class Color:
    r: int
    g: int
    b: int
    L: float
    C: float          # chroma actually achieved after gamut mapping
    H: float
    C_requested: float

    def hex(self, alpha: float = 1.0) -> str:
        return "#%02x%02x%02x%02x" % (self.r, self.g, self.b, round(alpha * 255))

    @property
    def rgb(self) -> tuple[int, int, int]:
        return (self.r, self.g, self.b)

    @property
    def clipped(self) -> bool:
        return self.C_requested - self.C > 1e-4


def oklch(L: float, C: float, H: float) -> Color:
    L = max(0.0, min(1.0, L))
    fitted = gamut_fit_chroma(L, C, H)
    lin = _lin_for(L, fitted, H)
    rgb = tuple(round(_linear_to_srgb(v) * 255) for v in lin)
    return Color(rgb[0], rgb[1], rgb[2], L, fitted, H % 360.0, C)


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_srgb_to_linear(v / 255) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def solve_L(target: float, bg: tuple[int, int, int], C: float, H: float, *,
            lighter: bool, bound: float | None = None) -> float:
    """Lightness that lands exactly on `target` contrast against `bg`.

    Contrast is V-shaped about the background lightness - it rises in *both*
    directions - so it is monotonic only on one side. `bound` is the background's
    own lightness; pass it whenever the target is low enough that the search
    could otherwise cross over and converge on the wrong side.
    """
    if bound is None:
        lo, hi = (0.0, 1.0)
    else:
        lo, hi = (bound, 1.0) if lighter else (0.0, bound)
    for _ in range(60):
        mid = (lo + hi) / 2
        ratio = contrast(oklch(mid, C, H).rgb, bg)
        if lighter:
            if ratio < target:
                lo = mid
            else:
                hi = mid
        else:
            if ratio < target:
                hi = mid
            else:
                lo = mid
    return hi if lighter else lo


def solve_plane(bg: tuple[int, int, int], hues: dict[str, float], ceiling: float,
                floor: float, *, lighter: bool) -> float:
    """Choose the one lightness every syntax token shares.

    Hand-picking this value trades vibrancy away for nothing: sRGB chroma varies
    sharply with lightness, and the best plane is rarely where intuition puts it.
    So it is solved instead - the lightness maximising mean achievable chroma
    across all eight hues, subject to every hue clearing `floor` contrast.
    """
    best_L, best_mean = None, -1.0
    for i in range(200, 980):
        L = i / 1000
        chromas = [gamut_fit_chroma(L, ceiling, h) for h in hues.values()]
        if min(contrast(oklch(L, c, h).rgb, bg)
               for c, h in zip(chromas, hues.values())) < floor:
            continue
        mean = sum(chromas) / len(chromas)
        if mean > best_mean:
            best_L, best_mean = L, mean
    if best_L is None:
        raise SystemExit(f"no lightness plane satisfies a {floor}:1 floor for this background")
    return best_L


def composite(fg: tuple[int, int, int], alpha: float,
              bg: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(round(alpha * c + (1 - alpha) * d) for c, d in zip(fg, bg))


def solve_overlay_alpha(overlays: list[tuple[int, int, int]], bases: list[tuple[int, int, int]],
                        texts: list[tuple[int, int, int]], target: float,
                        cap: float, floor_alpha: float = 0.06) -> float:
    # Alphas are searched on the 8-bit grid the theme file actually stores.
    # Solving in float and rounding afterwards can round *up*, landing the
    # shipped overlay just below the floor the solver just certified.
    """Strongest overlay that still leaves every token readable on top of it.

    A selection or search highlight is drawn *under* text. Push its alpha up for
    visibility and the text sitting on it loses contrast - the usual result being
    comments that vanish the moment you select a block. So the alpha is solved:
    the largest value (up to `cap`) that keeps every protected token at `target`.

    `overlays` must list every colour this alpha is applied to, not just the
    representative one. Zed draws each collaborator's selection in their own
    player colour, so an alpha solved against the accent alone is wrong for the
    seven brighter hues that share it.
    """
    def viable(a: float) -> bool:
        return all(contrast(t, composite(ov, a, base)) >= target
                   for ov in overlays for base in bases for t in texts)

    lo_n, hi_n = round(floor_alpha * 255), round(cap * 255)
    if not viable(lo_n / 255):
        raise SystemExit(
            f"no overlay alpha >= {floor_alpha} keeps every token at {target}:1; "
            f"raise the token contrast or lower the target"
        )
    best = lo_n
    for n in range(lo_n, hi_n + 1):
        if viable(n / 255):
            best = n
    return best / 255


def oklab_distance(a: Color, b: Color) -> float:
    """Perceptual distance in Oklab - used to prove no two token colours are confusable."""
    def lab(c: Color) -> tuple[float, float, float]:
        rad = math.radians(c.H)
        return (c.L, c.C * math.cos(rad), c.C * math.sin(rad))
    la, aa, ba = lab(a)
    lb, ab, bb = lab(b)
    return math.sqrt((la - lb) ** 2 + (aa - ab) ** 2 + (ba - bb) ** 2)


# --------------------------------------------------------------------------
# Palette definition
# --------------------------------------------------------------------------

# Eight syntax hues, spaced around the wheel so that adjacent token classes are
# never perceptually adjacent. Minimum separation is 32 degrees (rose/orchid).
HUE = {
    "rose":       350.0,   # keywords, control flow, storage
    "orchid":     318.0,   # tags, namespaces, markup titles
    "violet":     282.0,   # UI accent, attributes, decorators
    "azure":      240.0,   # properties, members, labels
    "cyan":       200.0,   # functions, methods
    "jade":       158.0,   # strings
    "amber":       85.0,   # types, classes, enums
    "tangerine":   45.0,   # numbers, booleans, constants
    # Status hues (may coincide with syntax hues by design)
    "red":         25.0,
    "grass":      145.0,
    "gold":        78.0,
}

NEUTRAL_H = 265.0  # a whisper of blue in every grey, so the UI reads as one family

SYNTAX_HUES = ["rose", "orchid", "violet", "azure", "cyan", "jade", "amber", "tangerine"]

# Vim / Helix mode indicators. Each is a chip in the status bar carrying its own
# label, so the pair has to be legible against itself, not against the editor.
# Hues are assigned semantically: green for insert, red for replace, the accent
# family for the visual modes.
VIM_MODES = {
    "normal": "azure",
    "insert": "jade",
    "replace": "rose",
    "visual": "violet",
    "visual_line": "orchid",
    "visual_block": "cyan",
    "helix_normal": "tangerine",
    "helix_select": "amber",
}

# Light backgrounds are not dark backgrounds inverted. At the lightness a light
# theme needs to clear AAA, two regions of the sRGB gamut collapse: 60-120 deg
# (yellow) and 165-240 deg (teal/cyan) can only hold ~0.08-0.10 chroma, which
# renders as mud rather than colour. Measured, not assumed - see docs/PALETTE.md.
# The light variant therefore rotates its hues out of those dead zones. This is
# the same palette, re-sited for a different gamut, not a second palette.
HUE_OVERRIDES: dict[str, dict[str, float]] = {
    "light": {
        "rose": 345.0, "orchid": 312.0, "violet": 280.0, "azure": 252.0,
        "cyan": 198.0, "jade": 146.0, "amber": 52.0, "tangerine": 22.0,
    },
}

# Contrast floors. These are the design contract; the build fails if unmet.
FLOOR_SYNTAX = 7.0      # WCAG AAA body text
FLOOR_COMMENT = 4.5     # WCAG AA - deliberately recessive
FLOOR_UI_TEXT = 4.5
# Sustained reading happens against the plain background, where syntax holds AAA.
# A selection or search highlight is a transient state, and holding 4.5:1 through
# one would force a selection so faint you could not see what you had selected.
# 3.5:1 clears WCAG's 3:1 threshold for large text and non-text contrast, with
# margin, and buys a selection you can actually see.
FLOOR_OVERLAY = 3.5


SPECS: dict[str, dict] = {
    "dark": dict(
        name="Dr. Syntax Dark",
        appearance="dark",
        lighter=True,
        neutral_c=0.014,
        bg_chrome=0.168,      # title bar, tab bar, status bar, panels
        bg_editor=0.200,      # the stage - lifted above the chrome
        bg_elevated=0.243,    # popovers, modals
        elem=(0.060, 0.092, 0.132),   # element background / hover / active offsets
        border=0.315,
        border_variant=0.262,
        syn_C_ceiling=0.170,  # above this, body text starts to feel garish
        plane_floor=7.15,     # optimiser target: AAA plus a little headroom
        fg_offset=0.045,      # plain code sits just above the syntax plane
        accent_L=0.720,
        targets=dict(text=13.0, muted=6.0, placeholder=4.0,
                     disabled=2.9, line_number=3.6, active_line_number=9.5,
                     comment=5.8, punctuation=6.2, invisible=2.0, hint=6.0,
                     active_line=1.16, highlighted_line=1.34, tab_inactive=1.10),
    ),
    "oled": dict(
        name="Dr. Syntax OLED",
        appearance="dark",
        lighter=True,
        neutral_c=0.014,
        bg_chrome=0.0,        # true black - pixels off
        bg_editor=0.0,
        bg_elevated=0.170,
        elem=(0.090, 0.130, 0.175),
        border=0.300,
        border_variant=0.235,
        # Chroma is pulled back on OLED: high-chroma text on true black blooms
        # (chromatic halation) on emissive panels. Lightness is pulled back too -
        # against #000 the contrast headroom is enormous, so full brightness is
        # simply glare.
        syn_C_ceiling=0.150,
        # Against #000 even a dim colour clears 7:1, so the AAA floor stops being
        # the useful constraint - it would happily return murky text. The floor is
        # raised so the plane stays bright enough to read as a lit surface.
        plane_floor=10.5,
        fg_offset=0.050,
        accent_L=0.700,
        targets=dict(text=15.5, muted=6.5, placeholder=4.2,
                     disabled=3.0, line_number=3.8, active_line_number=11.0,
                     # Raised above the other variants: against #000 the active
                     # line sits proportionally further from the background, so a
                     # comment needs more headroom to survive a selection on top
                     # of it. Syntax is at 10.5:1 here, so 6.5 is still the
                     # dimmest text on screen by a clear margin.
                     comment=6.5, punctuation=6.5, invisible=2.0, hint=6.5,
                     active_line=1.16, highlighted_line=1.34, tab_inactive=1.12),
    ),
    "light": dict(
        name="Dr. Syntax Light",
        appearance="light",
        lighter=False,
        neutral_c=0.006,
        bg_chrome=0.962,
        bg_editor=0.988,      # off-white, not #fff - cuts glare over long sessions
        bg_elevated=1.000,
        elem=(0.035, 0.067, 0.102),
        border=0.858,
        border_variant=0.902,
        # Light backgrounds invert the requirement: to look equally vivid, colours
        # need MORE chroma and LESS lightness. A naive inversion of a dark theme
        # produces the washed-out pastels most light themes suffer from.
        syn_C_ceiling=0.190,
        plane_floor=7.05,
        fg_offset=0.060,
        accent_L=0.520,
        targets=dict(text=13.0, muted=5.2, placeholder=3.6,
                     disabled=2.6, line_number=3.4, active_line_number=9.0,
                     comment=5.8, punctuation=6.0, invisible=1.9, hint=6.0,
                     active_line=1.16, highlighted_line=1.34, tab_inactive=1.10),
    ),
}


class Palette:
    """Resolved colours for one variant."""

    def _neutral_at(self, target: float, *, prefer_lighter: bool) -> Color:
        """Neutral surface sitting exactly `target` contrast from the editor background.

        Falls back to the opposite direction when the preferred one has no room -
        on a #000 background there is nothing darker to move towards.
        """
        nc = self.spec["neutral_c"]
        ed = self.editor_rgb
        reachable = contrast((255, 255, 255) if prefer_lighter else (0, 0, 0), ed)
        direction = prefer_lighter if reachable >= target else not prefer_lighter
        bg_L = self.spec["bg_editor"]
        return oklch(solve_L(target, ed, nc, NEUTRAL_H, lighter=direction, bound=bg_L),
                     nc, NEUTRAL_H)

    def _on_chip(self, chip: Color, target: float = 7.0) -> Color:
        """A neutral that reads cleanly *on* `chip`.

        Mode indicators carry their own label, so the pair is judged against
        itself. Whichever direction has more room is used - dark text on the
        bright chips of a dark theme, light text on the deep chips of a light one.
        """
        nc = self.spec["neutral_c"]
        lighter = contrast((255, 255, 255), chip.rgb) > contrast((0, 0, 0), chip.rgb)
        reach = contrast((255, 255, 255) if lighter else (0, 0, 0), chip.rgb)
        if reach < target:                       # target unreachable: take the extreme
            return oklch(1.0 if lighter else 0.0, 0.0, NEUTRAL_H)
        return oklch(solve_L(target, chip.rgb, nc, NEUTRAL_H, lighter=lighter, bound=chip.L),
                     nc, NEUTRAL_H)

    def __init__(self, key: str):
        self.key = key
        s = SPECS[key]
        self.spec = s
        self.name = s["name"]
        self.appearance = s["appearance"]
        self.lighter = s["lighter"]
        nc = s["neutral_c"]
        t = s["targets"]

        def n(L: float, c: float | None = None) -> Color:
            return oklch(L, nc if c is None else c, NEUTRAL_H)

        self.n = n

        # --- surfaces -----------------------------------------------------
        self.bg_chrome = n(s["bg_chrome"])
        self.bg_editor = n(s["bg_editor"])
        self.bg_elevated = n(s["bg_elevated"])
        ed = self.bg_editor.rgb
        self.editor_rgb = ed

        d = 1 if self.lighter else -1
        e0, e1, e2 = s["elem"]
        self.elem = n(s["bg_chrome"] + d * e0)
        self.elem_hover = n(s["bg_chrome"] + d * e1)
        self.elem_active = n(s["bg_chrome"] + d * e2)

        self.border = n(s["border"])
        self.border_variant = n(s["border_variant"])

        # --- text roles: lightness derived from contrast targets -----------
        def solved(target: float, c: float = nc, h: float = NEUTRAL_H) -> Color:
            return oklch(solve_L(target, ed, c, h, lighter=self.lighter), c, h)

        self.text = solved(t["text"])
        self.text_muted = solved(t["muted"])
        self.text_placeholder = solved(t["placeholder"])
        self.text_disabled = solved(t["disabled"])
        self.line_number = solved(t["line_number"])
        self.active_line_number = solved(t["active_line_number"])
        self.invisible = solved(t["invisible"])

        # Comments carry a touch of chroma so they read as "annotation" rather
        # than "disabled text", but sit at ~5:1 so they recede from the code.
        self.comment = oklch(
            solve_L(t["comment"], ed, 0.030, 252.0, lighter=self.lighter), 0.030, 252.0
        )
        self.punctuation = solved(t["punctuation"], c=nc * 1.6)

        # --- syntax plane -------------------------------------------------
        # One shared lightness for all eight hues, so no token appears to glow
        # brighter than its neighbours. The value is solved, not chosen.
        self.hues: dict[str, float] = {
            r: HUE_OVERRIDES.get(key, {}).get(r, HUE[r]) for r in SYNTAX_HUES
        }
        syn_C = s["syn_C_ceiling"]
        self.plane_floor = s["plane_floor"]
        self.syn_L = solve_plane(ed, self.hues, syn_C, self.plane_floor, lighter=self.lighter)
        self.syn_C = syn_C

        self.hue: dict[str, Color] = {
            r: oklch(self.syn_L, syn_C, self.hues[r]) for r in SYNTAX_HUES
        }

        # Plain code joins the same plane. If the foreground sat far brighter than
        # the coloured tokens - the usual arrangement - colour would read as less
        # important than punctuation, and structure would recede instead of pop.
        fo = s["fg_offset"]
        self.editor_fg = n(self.syn_L + (fo if self.lighter else -fo))

        # --- overlay surfaces ------------------------------------------------
        # Defined by how far they sit from the editor background rather than by a
        # lightness offset. An offset silently collapses to nothing when the
        # background is #000 - which is exactly where the OLED variant lives, and
        # is why its active-line and tab indicators were invisible.
        self.active_line = self._neutral_at(t["active_line"], prefer_lighter=self.lighter)
        self.highlighted_line = self._neutral_at(t["highlighted_line"], prefer_lighter=self.lighter)
        self.tab_inactive = self._neutral_at(t["tab_inactive"], prefer_lighter=False)

        # --- accent (UI chrome: cursor, links, focus rings) ----------------
        # Violet, shared with the syntax plane, so UI focus never introduces a
        # ninth hue that competes with code.
        acc_L = s["accent_L"]
        acc_floor = solve_L(FLOOR_UI_TEXT, ed, syn_C, self.hues["violet"], lighter=self.lighter)
        acc_L = max(acc_L, acc_floor) if self.lighter else min(acc_L, acc_floor)
        self.accent = oklch(acc_L, syn_C, self.hues["violet"])
        self.accent_bright = self.hue["violet"]

        # --- status colours ------------------------------------------------
        def status(hue_key: str) -> Color:
            h = self.hues.get(hue_key, HUE[hue_key])
            floor = solve_L(FLOOR_UI_TEXT, ed, syn_C, h, lighter=self.lighter)
            L = max(self.syn_L, floor) if self.lighter else min(self.syn_L, floor)
            return oklch(L, syn_C, h)

        self.error = status("red")
        self.warning = status("gold")
        self.success = status("grass")
        self.info = status("azure")
        # Inlay hints are read, not decoration, so they are held to a contrast that
        # survives a selection. Sitting them just above the 4.5 floor - the usual
        # choice - forces the selection alpha down to the point of invisibility.
        self.hint = oklch(
            solve_L(t["hint"], ed, 0.048, self.hues["cyan"], lighter=self.lighter),
            0.048, self.hues["cyan"],
        )
        self.predictive = oklch(
            solve_L(3.4, ed, 0.040, self.hues["violet"], lighter=self.lighter),
            0.040, self.hues["violet"],
        )

        # --- terminal ramp --------------------------------------------------
        step = 0.13 if self.lighter else -0.11
        # --- overlay alphas, solved against readability ------------------------
        # Every token a reader actually reads. `predictive` is excluded by design:
        # it is ghost text for an unaccepted suggestion, defined as sub-threshold,
        # and is not buffer content you can select.
        protected = ([self.comment.rgb, self.punctuation.rgb, self.editor_fg.rgb,
                      self.hint.rgb] + [self.hue[r].rgb for r in SYNTAX_HUES])
        # An overlay can land on the plain background or on the active line.
        bases = [ed, self.active_line.rgb]
        self.overlay_bases = bases
        self.protected_texts = protected
        self.selection_overlays = [self.accent.rgb] + [self.hue[r].rgb for r in SYNTAX_HUES]
        self.selection_alpha = solve_overlay_alpha(
            self.selection_overlays, bases, protected, FLOOR_OVERLAY, cap=0.30)
        self.match_alpha = solve_overlay_alpha(
            [self.hue["amber"].rgb], bases, protected, FLOOR_OVERLAY, cap=0.34)
        self.active_match_alpha = solve_overlay_alpha(
            [self.hue["tangerine"].rgb], bases, protected, FLOOR_OVERLAY, cap=0.42)

        # Diff hunk fills sit *behind* code, so they take the overlay contract too.
        # Zed's own fallback is 0.16 fill / 0.08 hollow / 0.48 hollow border; the
        # cap honours that and the solver pulls it back only if readability needs it.
        self.hunk_alpha = solve_overlay_alpha(
            [self.success.rgb, self.error.rgb], bases, protected, FLOOR_OVERLAY, cap=0.16)
        self.hunk_hollow_alpha = round(self.hunk_alpha / 2, 3)
        self.hunk_border_alpha = 0.48
        # The yank flash is a highlight over code - same contract as a search match.
        self.yank_alpha = solve_overlay_alpha(
            [self.hue["amber"].rgb], bases, protected, FLOOR_OVERLAY, cap=0.30)

        self.vim = {
            mode: (self.hue[h], self._on_chip(self.hue[h]))
            for mode, h in VIM_MODES.items()
        }
        # Helix jump labels are single characters overlaid on code; they have to be
        # found instantly, so they sit on the syntax plane at full contrast.
        self.helix_jump_label = self.hue["rose"]

        term_keys = ("red", "grass", "gold", "azure", "violet", "cyan")

        def th(k: str) -> float:
            return self.hues.get(k, HUE[k])

        self.term_normal = {k: oklch(self.syn_L, syn_C, th(k)) for k in term_keys}
        self.term_bright = {k: oklch(self.syn_L + (0.075 if self.lighter else -0.075),
                                     syn_C * 0.92, th(k)) for k in term_keys}
        self.term_dim = {k: oklch(self.syn_L - (0.130 if self.lighter else -0.115),
                                  syn_C * 0.85, th(k)) for k in term_keys}
        _ = step


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

@dataclass
class Check:
    label: str
    ratio: float
    floor: float

    @property
    def ok(self) -> bool:
        return self.ratio + 1e-9 >= self.floor


def verify(p: Palette) -> list[Check]:
    bg = p.editor_rgb
    checks: list[Check] = []
    for h in SYNTAX_HUES:
        checks.append(Check(f"syntax/{h}", contrast(p.hue[h].rgb, bg), FLOOR_SYNTAX))
    checks.append(Check("syntax/comment", contrast(p.comment.rgb, bg), FLOOR_COMMENT))
    checks.append(Check("syntax/punctuation", contrast(p.punctuation.rgb, bg), 4.5))
    checks.append(Check("editor/foreground", contrast(p.editor_fg.rgb, bg), 7.0))
    checks.append(Check("ui/text", contrast(p.text.rgb, p.bg_chrome.rgb), 7.0))
    checks.append(Check("ui/text.muted", contrast(p.text_muted.rgb, p.bg_chrome.rgb), FLOOR_UI_TEXT))
    checks.append(Check("ui/accent", contrast(p.accent.rgb, p.bg_chrome.rgb), 4.5))
    for label, col in (("status/error", p.error), ("status/warning", p.warning),
                       ("status/success", p.success), ("status/info", p.info)):
        checks.append(Check(label, contrast(col.rgb, bg), FLOOR_UI_TEXT))
    # Non-text but must remain perceivable
    checks.append(Check("ui/border-vs-chrome", contrast(p.border.rgb, p.bg_chrome.rgb), 1.30))
    checks.append(Check("editor/line_number", contrast(p.line_number.rgb, bg), 3.0))

    # Overlay states. A theme that looks right on a static screenshot can still
    # hide comments the moment you select a block, or lose the active-line and
    # active-tab indicators entirely - so those states are asserted, not eyeballed.
    overlays = (
        ("selection", p.selection_overlays, p.selection_alpha),
        ("search-match", [p.hue["amber"].rgb], p.match_alpha),
        ("active-match", [p.hue["tangerine"].rgb], p.active_match_alpha),
    )
    for label, colours, alpha in overlays:
        for base_name, base in (("bg", bg), ("active-line", p.active_line.rgb)):
            worst = min(contrast(t, composite(c, alpha, base))
                        for c in colours for t in p.protected_texts)
            checks.append(Check(f"overlay/{label}-on-{base_name}", worst, FLOOR_OVERLAY))

    # Indicators that must be visible, or the affordance simply is not there.
    checks.append(Check("overlay/selection-visibility",
                        contrast(composite(p.accent.rgb, p.selection_alpha, bg), bg), 1.25))
    checks.append(Check("editor/active-line-visibility",
                        contrast(p.active_line.rgb, bg), 1.10))
    checks.append(Check("ui/active-tab-distinct",
                        contrast(bg, p.tab_inactive.rgb), 1.08))

    # Mode indicators are judged against their own chip, not the editor.
    for mode, (chip, label) in p.vim.items():
        checks.append(Check(f"vim/{mode}-label-on-chip", contrast(label.rgb, chip.rgb), 7.0))
    checks.append(Check("vim/helix-jump-label",
                        contrast(p.helix_jump_label.rgb, bg), FLOOR_SYNTAX))

    # Diff hunk fills and the yank flash sit behind code.
    for label, colour, alpha in (("hunk-added", p.success.rgb, p.hunk_alpha),
                                 ("hunk-deleted", p.error.rgb, p.hunk_alpha),
                                 ("yank", p.hue["amber"].rgb, p.yank_alpha)):
        for base_name, base in (("bg", bg), ("active-line", p.active_line.rgb)):
            worst = min(contrast(t, composite(colour, alpha, base)) for t in p.protected_texts)
            checks.append(Check(f"overlay/{label}-on-{base_name}", worst, FLOOR_OVERLAY))
    return checks


def separation_report(p: Palette) -> tuple[float, str, str]:
    """Smallest perceptual gap between any two syntax hues."""
    worst, pair = 1e9, ("", "")
    for i, a in enumerate(SYNTAX_HUES):
        for b in SYNTAX_HUES[i + 1:]:
            dist = oklab_distance(p.hue[a], p.hue[b])
            if dist < worst:
                worst, pair = dist, (a, b)
    return worst, pair[0], pair[1]


MIN_SEPARATION = 0.050  # Oklab units; below this two token colours start to blur


# --------------------------------------------------------------------------
# Zed style construction
# --------------------------------------------------------------------------

def syn(color: Color, *, style: str | None = None, weight: int | None = None) -> dict:
    return {"color": color.hex(), "font_style": style, "font_weight": weight}


def build_style(p: Palette) -> dict:
    h = p.hue
    accent = p.accent
    ed = p.bg_editor
    is_dark = p.appearance == "dark"

    # Overlay alphas are solved in Palette against text readability, not chosen.
    sel_a = p.selection_alpha
    tint_a = 0.16 if is_dark else 0.13
    active_line = p.active_line
    highlighted_line = p.highlighted_line

    style: dict = {
        # ---- base surfaces ------------------------------------------------
        "background": p.bg_chrome.hex(),
        "surface.background": p.bg_chrome.hex(),
        "elevated_surface.background": p.bg_elevated.hex(),

        # ---- borders ------------------------------------------------------
        "border": p.border.hex(),
        "border.variant": p.border_variant.hex(),
        "border.focused": accent.hex(0.85),
        "border.selected": accent.hex(0.85),
        "border.transparent": p.border.hex(0.0),
        "border.disabled": p.border_variant.hex(),

        # ---- interactive elements ------------------------------------------
        "element.background": p.elem.hex(),
        "element.hover": p.elem_hover.hex(),
        "element.active": p.elem_active.hex(),
        "element.selected": accent.hex(min(0.22, sel_a)),
        "element.selection_background": accent.hex(sel_a),
        "element.disabled": p.elem.hex(0.55),
        "drop_target.background": accent.hex(0.22),
        "drop_target.border": accent.hex(0.60),

        "ghost_element.background": p.elem.hex(0.0),
        "ghost_element.hover": p.elem_hover.hex(0.70),
        "ghost_element.active": p.elem_active.hex(0.85),
        "ghost_element.selected": accent.hex(0.20),
        "ghost_element.disabled": p.elem.hex(0.35),

        # ---- text ----------------------------------------------------------
        "text": p.text.hex(),
        "text.muted": p.text_muted.hex(),
        "text.placeholder": p.text_placeholder.hex(),
        "text.disabled": p.text_disabled.hex(),
        "text.accent": accent.hex(),
        "link_text.hover": h["cyan"].hex(),

        # ---- icons -----------------------------------------------------------
        "icon": p.text.hex(),
        "icon.muted": p.text_muted.hex(),
        "icon.placeholder": p.text_placeholder.hex(),
        "icon.disabled": p.text_disabled.hex(),
        "icon.accent": accent.hex(),
        "debugger.accent": h["tangerine"].hex(),

        # ---- chrome ----------------------------------------------------------
        "status_bar.background": p.bg_chrome.hex(),
        "title_bar.background": p.bg_chrome.hex(),
        "title_bar.inactive_background": p.bg_chrome.hex(),
        "toolbar.background": ed.hex(),
        "tab_bar.background": p.tab_inactive.hex(),
        "tab.inactive_background": p.tab_inactive.hex(),
        "tab.active_background": ed.hex(),
        "panel.background": p.bg_chrome.hex(),
        "panel.focused_border": accent.hex(0.85),
        "panel.indent_guide": p.border_variant.hex(),
        "panel.indent_guide_hover": accent.hex(0.45),
        "panel.indent_guide_active": accent.hex(0.80),
        "panel.overlay_background": p.bg_chrome.hex(),
        "panel.overlay_hover": p.elem_hover.hex(),
        "pane.focused_border": accent.hex(0.70),
        "pane_group.border": p.border.hex(),

        "search.match_background": h["amber"].hex(p.match_alpha),
        "search.active_match_background": h["tangerine"].hex(p.active_match_alpha),

        # ---- scrollbar / minimap ---------------------------------------------
        "scrollbar.thumb.background": p.text_muted.hex(0.26),
        "scrollbar.thumb.hover_background": p.text_muted.hex(0.42),
        "scrollbar.thumb.active_background": p.text_muted.hex(0.58),
        "scrollbar.thumb.border": p.border.hex(0.0),
        "scrollbar.track.background": ed.hex(0.0),
        "scrollbar.track.border": p.border_variant.hex(0.60),
        "minimap.thumb.background": p.text_muted.hex(0.16),
        "minimap.thumb.hover_background": p.text_muted.hex(0.28),
        "minimap.thumb.active_background": p.text_muted.hex(0.40),
        "minimap.thumb.border": p.border.hex(0.0),

        # ---- editor ------------------------------------------------------------
        "editor.foreground": p.editor_fg.hex(),
        "editor.background": ed.hex(),
        "editor.gutter.background": ed.hex(),
        "editor.subheader.background": p.bg_chrome.hex(),
        "editor.active_line.background": active_line.hex(),
        "editor.highlighted_line.background": highlighted_line.hex(),
        "editor.debugger_active_line.background": h["tangerine"].hex(0.22),
        "editor.line_number": p.line_number.hex(),
        "editor.active_line_number": p.active_line_number.hex(),
        "editor.hover_line_number": p.text_muted.hex(),
        "editor.invisible": p.invisible.hex(),
        "editor.wrap_guide": p.border_variant.hex(0.60),
        "editor.active_wrap_guide": p.border.hex(),
        "editor.indent_guide": p.border_variant.hex(),
        "editor.indent_guide_active": accent.hex(0.55),
        "editor.document_highlight.read_background": accent.hex(0.20),
        "editor.document_highlight.write_background": h["tangerine"].hex(0.24),
        "editor.document_highlight.bracket_background": h["cyan"].hex(0.28),
    }

    # ---- status colours ------------------------------------------------------
    status_map = {
        "error": p.error,
        "warning": p.warning,
        "info": p.info,
        "success": p.success,
        "hint": p.hint,
        "predictive": p.predictive,
        "created": p.success,
        "modified": p.warning,
        "deleted": p.error,
        "renamed": p.info,
        "conflict": h["tangerine"],
        "ignored": p.text_disabled,
        "hidden": p.text_disabled,
        "unreachable": p.text_placeholder,
    }
    for key, col in status_map.items():
        style[key] = col.hex()
        style[f"{key}.background"] = col.hex(tint_a)
        style[f"{key}.border"] = col.hex(0.55)

    # ---- version control ------------------------------------------------------
    style.update({
        "version_control.added": p.success.hex(),
        "version_control.deleted": p.error.hex(),
        "version_control.modified": p.warning.hex(),
        "version_control.renamed": p.info.hex(),
        "version_control.conflict": h["tangerine"].hex(),
        "version_control.ignored": p.text_disabled.hex(),
        "version_control.conflict_marker.ours": p.success.hex(0.20),
        "version_control.conflict_marker.theirs": p.info.hex(0.20),
        "version_control.word_added": p.success.hex(0.28),
        "version_control.word_deleted": p.error.hex(0.28),
    })

    # ---- terminal ---------------------------------------------------------------
    tn, tb, td = p.term_normal, p.term_bright, p.term_dim
    ansi_black = p.n(p.spec["bg_chrome"] + (0.14 if p.lighter else -0.10))
    style.update({
        "terminal.background": ed.hex(),
        "terminal.foreground": p.editor_fg.hex(),
        "terminal.bright_foreground": p.text.hex(),
        "terminal.dim_foreground": p.text_muted.hex(),
        "terminal.ansi.black": ansi_black.hex(),
        "terminal.ansi.red": tn["red"].hex(),
        "terminal.ansi.green": tn["grass"].hex(),
        "terminal.ansi.yellow": tn["gold"].hex(),
        "terminal.ansi.blue": tn["azure"].hex(),
        "terminal.ansi.magenta": tn["violet"].hex(),
        "terminal.ansi.cyan": tn["cyan"].hex(),
        "terminal.ansi.white": p.editor_fg.hex(),
        "terminal.ansi.bright_black": p.text_placeholder.hex(),
        "terminal.ansi.bright_red": tb["red"].hex(),
        "terminal.ansi.bright_green": tb["grass"].hex(),
        "terminal.ansi.bright_yellow": tb["gold"].hex(),
        "terminal.ansi.bright_blue": tb["azure"].hex(),
        "terminal.ansi.bright_magenta": tb["violet"].hex(),
        "terminal.ansi.bright_cyan": tb["cyan"].hex(),
        "terminal.ansi.bright_white": p.text.hex(),
        "terminal.ansi.dim_black": ansi_black.hex(),
        "terminal.ansi.dim_red": td["red"].hex(),
        "terminal.ansi.dim_green": td["grass"].hex(),
        "terminal.ansi.dim_yellow": td["gold"].hex(),
        "terminal.ansi.dim_blue": td["azure"].hex(),
        "terminal.ansi.dim_magenta": td["violet"].hex(),
        "terminal.ansi.dim_cyan": td["cyan"].hex(),
        "terminal.ansi.dim_white": p.text_muted.hex(),
        "terminal.ansi.background": ed.hex(),
    })

    # ---- editor diff hunks -----------------------------------------------------------
    style.update({
        "editor.diff_hunk.added.background": p.success.hex(p.hunk_alpha),
        "editor.diff_hunk.added.hollow_background": p.success.hex(p.hunk_hollow_alpha),
        "editor.diff_hunk.added.hollow_border": p.success.hex(p.hunk_border_alpha),
        "editor.diff_hunk.deleted.background": p.error.hex(p.hunk_alpha),
        "editor.diff_hunk.deleted.hollow_background": p.error.hex(p.hunk_hollow_alpha),
        "editor.diff_hunk.deleted.hollow_border": p.error.hex(p.hunk_border_alpha),
    })

    # ---- vim / helix mode indicators ----------------------------------------------------
    for mode, (chip, label) in p.vim.items():
        style[f"vim.{mode}.background"] = chip.hex()
        style[f"vim.{mode}.foreground"] = label.hex()
    style["vim.yank.background"] = h["amber"].hex(p.yank_alpha)
    style["vim.helix_jump_label.foreground"] = p.helix_jump_label.hex()

    # ---- collaboration cursors ---------------------------------------------------
    player_hues = ["violet", "cyan", "jade", "tangerine", "rose", "azure", "amber", "orchid"]
    style["players"] = [
        {
            "cursor": h[k].hex(),
            "background": h[k].hex(),
            "selection": h[k].hex(sel_a),
        }
        for k in player_hues
    ]

    # ---- indent-aware accent ramp -------------------------------------------------
    style["accents"] = [h[k].hex() for k in
                        ["violet", "cyan", "jade", "tangerine", "rose", "azure", "amber", "orchid"]]

    # ---- syntax --------------------------------------------------------------------
    fg = p.editor_fg
    style["syntax"] = {
        # Structure - rose. The skeleton of the file.
        "keyword":                    syn(h["rose"]),
        "operator":                   syn(p.punctuation),
        "primary":                    syn(fg),

        # Callables - cyan. Definitions are bold so a file can be scanned for
        # where things are declared rather than read line by line.
        "function":                   syn(h["cyan"]),
        "function.builtin":           syn(h["cyan"], style="italic"),
        "function.method":            syn(h["cyan"]),
        "function.definition":        syn(h["cyan"], weight=700),
        "function.method.builtin":    syn(h["cyan"], style="italic"),
        "function.special.definition": syn(h["cyan"], weight=700),
        "constructor":                syn(h["amber"], weight=700),

        # Text - jade. Long runs, so the most restful hue on the wheel.
        "string":                     syn(h["jade"]),
        "string.escape":              syn(h["tangerine"]),
        "string.regex":               syn(h["orchid"]),
        "string.special":             syn(h["tangerine"]),
        "string.special.symbol":      syn(h["tangerine"]),
        "string.special.path":        syn(h["jade"], style="italic"),
        "string.special.url":         syn(h["cyan"], style="italic"),
        "text.literal":               syn(h["jade"]),

        # Types - amber.
        "type":                       syn(h["amber"]),
        "type.builtin":               syn(h["amber"], style="italic"),
        "type.interface":             syn(h["amber"]),
        "type.super":                 syn(h["amber"], style="italic"),
        "enum":                       syn(h["amber"]),
        "variant":                    syn(h["amber"]),

        # Literals - tangerine.
        "number":                     syn(h["tangerine"]),
        "boolean":                    syn(h["tangerine"]),
        "constant":                   syn(h["tangerine"]),
        "constant.builtin":           syn(h["tangerine"]),

        # Data access - azure.
        "property":                   syn(h["azure"]),
        "variable.member":            syn(h["azure"]),
        "label":                      syn(h["azure"]),
        "selector":                   syn(h["azure"]),
        "selector.pseudo":            syn(h["violet"]),

        # Meta - violet.
        "attribute":                  syn(h["violet"]),
        "preproc":                    syn(h["violet"]),
        "embedded":                   syn(h["violet"]),
        "concept":                    syn(h["violet"]),

        # Markup / structure - orchid.
        "tag":                        syn(h["orchid"]),
        "tag.doctype":                syn(h["orchid"], style="italic"),
        "namespace":                  syn(h["orchid"]),
        "module":                     syn(h["orchid"]),
        "title":                      syn(h["orchid"], weight=700),

        # Neutral by design. Most of a file should be near-foreground; colour is
        # spent on structure, not on every identifier.
        "variable":                   syn(fg),
        "variable.builtin":           syn(h["rose"], style="italic"),
        "variable.parameter":         syn(p.editor_fg),
        "variable.special":           syn(h["rose"], style="italic"),

        # Punctuation recedes so that structure, not scaffolding, carries the eye.
        "punctuation":                syn(p.punctuation),
        "punctuation.bracket":        syn(p.punctuation),
        "punctuation.delimiter":      syn(p.punctuation),
        "punctuation.list_marker":    syn(h["rose"]),
        "punctuation.markup":         syn(h["rose"]),
        "punctuation.special":        syn(h["orchid"]),

        # Comments - present, readable, and out of the way.
        "comment":                    syn(p.comment, style="italic"),
        "comment.doc":                syn(p.comment, style="italic"),

        # Markup emphasis
        "emphasis":                   syn(h["rose"], style="italic"),
        "emphasis.strong":            syn(h["rose"], weight=700),
        "link_text":                  syn(h["cyan"], style="italic"),
        "link_uri":                   syn(h["jade"]),

        # Editor affordances
        "hint":                       syn(p.hint, style="italic"),
        "predictive":                 syn(p.predictive, style="italic"),

        # Diffs
        "diff.plus":                  syn(p.success),
        "diff.minus":                 syn(p.error),
    }

    return style


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def build_theme_document() -> tuple[dict, dict[str, Palette]]:
    palettes = {k: Palette(k) for k in ("dark", "oled", "light")}
    doc = {
        "$schema": SCHEMA,
        "name": FAMILY,
        "author": AUTHOR,
        "themes": [
            {
                "name": palettes[k].name,
                "appearance": palettes[k].appearance,
                "style": build_style(palettes[k]),
            }
            for k in ("dark", "oled", "light")
        ],
    }
    return doc, palettes


def render_palette_doc(palettes: dict[str, Palette]) -> str:
    out: list[str] = [
        "# Dr. Syntax - palette reference",
        "",
        "Generated by `tools/build_theme.py`. Do not edit by hand.",
        "",
        "Every value below is produced from OKLCH coordinates and verified against a",
        "WCAG 2.1 contrast floor before the theme is written. `Ratio` is measured against",
        "that variant's `editor.background` using the final 8-bit sRGB values, i.e. the",
        "colours actually rendered - not the pre-quantisation floats.",
        "",
    ]
    for key in ("dark", "oled", "light"):
        p = palettes[key]
        checks = verify(p)
        worst_sep, a, b = separation_report(p)
        out += [
            f"## {p.name}",
            "",
            f"- Appearance: `{p.appearance}`",
            f"- Editor background: `{p.bg_editor.hex()}` (OKLCH L {p.bg_editor.L:.3f})",
            f"- Syntax lightness plane: **L = {p.syn_L:.3f}** "
            f"(solved: maximises mean chroma subject to a {p.plane_floor}:1 floor)",
            f"- Syntax chroma ceiling: {p.syn_C:.3f}",
            f"- Hue map: {'rotated for the light gamut' if p.key in HUE_OVERRIDES else 'canonical'}",
            f"- Tightest perceptual gap between two token hues: **{worst_sep:.4f}** Oklab "
            f"({a} vs {b}; threshold {MIN_SEPARATION})",
            "",
            "### Syntax plane",
            "",
            "| Role | Hue | Angle | Hex | OKLCH | Contrast vs editor bg | Gamut |",
            "|---|---|---|---|---|---|---|",
        ]
        roles = {
            "rose": "keyword, control flow",
            "orchid": "tag, namespace, title",
            "violet": "attribute, preproc, UI accent",
            "azure": "property, member, label",
            "cyan": "function, method",
            "jade": "string, literal text",
            "amber": "type, class, enum",
            "tangerine": "number, boolean, constant",
        }
        for hk in SYNTAX_HUES:
            c = p.hue[hk]
            ratio = contrast(c.rgb, p.editor_rgb)
            gam = "clipped" if c.clipped else "in gamut"
            out.append(
                f"| {roles[hk]} | {hk} | {p.hues[hk]:.0f}\u00b0 | `{c.hex()}` | "
                f"L {c.L:.3f} C {c.C:.3f} | {ratio:.2f}:1 | {gam} |"
            )
        out += [
            "",
            "### Neutrals and status",
            "",
            "| Role | Hex | Contrast vs editor bg |",
            "|---|---|---|",
        ]
        for label, col in (
            ("editor.foreground", p.editor_fg), ("text", p.text), ("text.muted", p.text_muted),
            ("text.placeholder", p.text_placeholder), ("text.disabled", p.text_disabled),
            ("comment", p.comment), ("punctuation", p.punctuation),
            ("line number", p.line_number), ("active line number", p.active_line_number),
            ("accent", p.accent), ("error", p.error), ("warning", p.warning),
            ("success", p.success), ("info", p.info),
        ):
            out.append(f"| {label} | `{col.hex()}` | {contrast(col.rgb, p.editor_rgb):.2f}:1 |")

        failed = [c for c in checks if not c.ok]
        out += [
            "",
            "### Verification",
            "",
            f"- {len(checks)} contrast assertions, {len(checks) - len(failed)} passing.",
            f"- Minimum syntax contrast: "
            f"{min(contrast(p.hue[k].rgb, p.editor_rgb) for k in SYNTAX_HUES):.2f}:1 "
            f"(floor {FLOOR_SYNTAX}:1, WCAG AAA).",
            "",
        ]
        if failed:
            out.append("**FAILING:**")
            out += [f"- {c.label}: {c.ratio:.2f}:1 < {c.floor}:1" for c in failed]
            out.append("")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Build and verify the Dr. Syntax Zed theme.")
    ap.add_argument("--check", action="store_true", help="verify only; do not write files")
    args = ap.parse_args()

    doc, palettes = build_theme_document()

    ok = True
    for key in ("dark", "oled", "light"):
        p = palettes[key]
        checks = verify(p)
        failed = [c for c in checks if not c.ok]
        sep, a, b = separation_report(p)
        status = "PASS" if not failed and sep >= MIN_SEPARATION else "FAIL"
        if status == "FAIL":
            ok = False
        min_syn = min(contrast(p.hue[k].rgb, p.editor_rgb) for k in SYNTAX_HUES)
        print(
            f"[{status}] {p.name:<20} "
            f"syntax L={p.syn_L:.3f}  min-contrast={min_syn:.2f}:1  "
            f"hue-separation={sep:.4f} ({a}/{b})  "
            f"{len(checks) - len(failed)}/{len(checks)} assertions"
        )
        for c in failed:
            print(f"         !! {c.label}: {c.ratio:.2f}:1 < required {c.floor}:1")
        if sep < MIN_SEPARATION:
            print(f"         !! hue separation {sep:.4f} < {MIN_SEPARATION} ({a} vs {b})")

    if not ok:
        print("\nBuild failed: contrast or separation contract violated.", file=sys.stderr)
        return 1

    if args.check:
        print("\nAll contracts satisfied (check mode; nothing written).")
        return 0

    THEME_PATH.parent.mkdir(parents=True, exist_ok=True)
    PALETTE_DOC.parent.mkdir(parents=True, exist_ok=True)
    THEME_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    PALETTE_DOC.write_text(render_palette_doc(palettes), encoding="utf-8")
    print(f"\nWrote {THEME_PATH.relative_to(ROOT)}")
    print(f"Wrote {PALETTE_DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

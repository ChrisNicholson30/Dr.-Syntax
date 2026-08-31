#!/usr/bin/env python3
"""
Tests for the claims this repo makes.

Every assertion here backs a statement made in the README or on the site. A
claim with no runnable check behind it is a claim nobody can audit, including
the person who wrote it - so the colour maths, the highlighter's safety
properties and the validator's ability to reject a bad theme are all pinned
here rather than left to a one-off check that scrolled off someone's terminal.

Standard library only. Exits non-zero on the first failing group.

    python3 tools/test_build.py
"""
from __future__ import annotations

import html
import json
import math
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_theme import (  # noqa: E402
    SYNTAX_HUES, Palette, contrast, oklch, rgb_to_oklch,
)
from build_site import LANGS, SAMPLES, highlight  # noqa: E402
from validate_theme import (  # noqa: E402
    AAA_FLOOR, TOKEN_FLOORS, audit_contracts, audit_overlays, _contrast, _rgba,
)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(f"{name} {detail}".strip())


# --------------------------------------------------------------------------
# Colour maths
# --------------------------------------------------------------------------

def test_oklch_round_trip() -> None:
    """8-bit sRGB -> OKLCH -> 8-bit sRGB must be lossless.

    Backs the claim that colours are authored in OKLCH without drifting: if the
    conversion were even one step off, every published hex would be wrong.
    """
    random.seed(7)
    samples = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0),
               (128, 128, 128), (18, 20, 26), (240, 240, 238)]
    samples += [tuple(random.randrange(256) for _ in range(3)) for _ in range(600)]
    worst, worst_case = 0, None
    for rgb in samples:
        got = oklch(*rgb_to_oklch(rgb)).rgb
        err = max(abs(a - b) for a, b in zip(got, rgb))
        if err > worst:
            worst, worst_case = err, (rgb, got)
    check(f"OKLCH round-trip exact over {len(samples)} colours",
          worst == 0, f"worst error {worst}/255 at {worst_case}")


def test_srgb_primaries() -> None:
    """OKLCH coordinates of the sRGB primaries must land back on the primaries."""
    for name, rgb in (("red", (255, 0, 0)), ("green", (0, 255, 0)),
                      ("blue", (0, 0, 255)), ("white", (255, 255, 255))):
        L, C, H = rgb_to_oklch(rgb)
        check(f"sRGB {name} survives OKLCH", oklch(L, C, H).rgb == rgb,
              f"got {oklch(L, C, H).rgb}, expected {rgb}")


def test_wcag() -> None:
    """WCAG contrast against known reference values."""
    check("black/white contrast is exactly 21:1",
          abs(contrast((0, 0, 0), (255, 255, 255)) - 21.0) < 1e-9)
    ratio = contrast((0x76, 0x76, 0x76), (255, 255, 255))
    check("#767676 on white is the 4.5:1 boundary", abs(ratio - 4.54) < 0.01,
          f"got {ratio:.3f}")


def test_gamut_mapping_holds_hue_and_lightness() -> None:
    """Chroma may be given up to fit sRGB; lightness and hue may not drift."""
    worst_L, worst_H = 0.0, 0.0
    for H in range(0, 360, 7):
        c = oklch(0.75, 0.40, float(H))          # far outside sRGB at this lightness
        L2, _, H2 = rgb_to_oklch(c.rgb)
        worst_L = max(worst_L, abs(L2 - 0.75))
        worst_H = max(worst_H, min(abs(H2 - H), 360 - abs(H2 - H)))
    check("gamut mapping preserves lightness (<=0.01)", worst_L <= 0.01, f"{worst_L:.4f}")
    check("gamut mapping preserves hue (<=1.5 deg)", worst_H <= 1.5, f"{worst_H:.3f}")


# --------------------------------------------------------------------------
# Highlighter safety properties
# --------------------------------------------------------------------------

ADVERSARIAL = {
    "unterminated block comment": "let a = 1;\n/* never closed\nlet b = 2;\n",
    "multiline template string": 'const s = `line1\nline2`;\nconst t = "ok";\n',
    "comment containing a quote": "// don't do this\nlet x = 1;\n",
    "string containing a comment": 'const u = "http://x.test/a";\nlet y = 2;\n',
    "angle brackets and ampersands": "if (a<b && c>d) { e(); }\n",
    "html injection attempt": 'const x = "</span><script>alert(1)</script>";\n',
    "empty input": "",
}


def _strip(lines: list[str]) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", "\n".join(lines)))


def test_highlighter_preserves_text() -> None:
    """The highlighter must never alter the code it is colouring.

    Backs the claim that a preview cannot show code the sample does not contain.
    """
    for lang, src in SAMPLES.items():
        check(f"{LANGS[lang]['label']} sample text preserved",
              _strip(highlight(src, lang)).rstrip("\n") == src.rstrip("\n"))
    for name, src in ADVERSARIAL.items():
        check(f"adversarial: {name} preserved",
              _strip(highlight(src, "typescript")).rstrip("\n") == src.rstrip("\n"))


def test_highlighter_balances_spans() -> None:
    """Unbalanced spans would leak styling into the rest of the page."""
    for lang, src in list(SAMPLES.items()) + [("typescript", s) for s in ADVERSARIAL.values()]:
        bad = [i + 1 for i, line in enumerate(highlight(src, lang))
               if len(re.findall(r"<span", line)) != line.count("</span>")]
        check(f"{LANGS[lang]['label']} spans balanced per line", not bad, f"lines {bad}")


def test_highlighter_escapes_markup() -> None:
    """Any '<' in a sample must reach the page escaped, never as a live tag."""
    out = "\n".join(highlight('const x = "</span><script>alert(1)</script>";\n', "typescript"))
    check("no raw <script> survives highlighting", "<script>" not in out)
    check("markup in a string is escaped", "&lt;script&gt;" in out)


def test_highlighter_classification() -> None:
    """Spot-check that tokens land in the intended class."""
    def classes(lang: str, token: str) -> set[str]:
        found = set()
        for line in highlight(SAMPLES[lang], lang):
            for m in re.finditer(r'<span class="t-([a-z]+)">([^<]*)</span>', line):
                if html.unescape(m.group(2)) == token:
                    found.add(m.group(1))
        return found
    for lang, token, want in (("rust", "self", "kw"), ("rust", "Hsla", "typ"),
                              ("rust", "iter", "fn"), ("typescript", "const", "kw"),
                              ("typescript", "Math", "typ"), ("python", "def", "kw"),
                              ("css", "0.737", "num"), ("json", '"name"', "prop")):
        check(f"{lang}: {token} -> t-{want}", want in classes(lang, token),
              f"got {sorted(classes(lang, token))}")


# --------------------------------------------------------------------------
# The validator must actually reject bad themes
# --------------------------------------------------------------------------

def _style() -> dict:
    return json.loads((ROOT / "themes" / "dr-syntax.json").read_text())["themes"][0]["style"]


def test_validator_rejects_regressions() -> None:
    """A checker that has never failed is not known to work."""
    clean = _style()
    errs, _, _ = audit_contracts("clean", clean)
    check("shipped theme passes its own contract", not errs, "; ".join(errs[:2]))

    faded = _style()
    faded["syntax"]["keyword"]["color"] = "#8a93a8ff"          # 5.88:1 - below AAA
    errs, _, _ = audit_contracts("faded", faded)
    check("rejects a syntax colour below the AAA floor", bool(errs))

    dim = _style()
    dim["syntax"]["comment"]["color"] = "#3f4650ff"            # far below the comment floor
    errs, _, _ = audit_contracts("dim", dim)
    check("rejects a comment below its floor", bool(errs))

    loud = _style()
    loud["players"][0]["selection"] = "#9d9effcc"              # opaque enough to bury text
    errs, _, _ = audit_overlays("loud", loud)
    check("rejects a selection that buries the code under it", bool(errs))

    tabs = _style()
    tabs["tab.inactive_background"] = tabs["tab.active_background"]
    errs, _, _ = audit_overlays("tabs", tabs)
    check("rejects an indistinguishable active tab", bool(errs))


def test_every_variant_meets_its_floors() -> None:
    doc = json.loads((ROOT / "themes" / "dr-syntax.json").read_text())
    for variant in doc["themes"]:
        s = variant["style"]
        bg = _rgba(s["editor.background"])[0]
        worst = min(_contrast(_rgba(sp["color"])[0], bg)
                    for t, sp in s["syntax"].items()
                    if TOKEN_FLOORS.get(t, AAA_FLOOR) >= AAA_FLOOR)
        check(f"{variant['name']}: every AAA token >= {AAA_FLOOR}:1",
              worst >= AAA_FLOOR, f"worst {worst:.2f}:1")


def test_hue_separation() -> None:
    """No two token colours may be close enough to confuse."""
    for key in ("dark", "oled", "light"):
        p = Palette(key)
        worst = min(
            math.dist(
                (p.hue[a].L, p.hue[a].C * math.cos(math.radians(p.hue[a].H)),
                 p.hue[a].C * math.sin(math.radians(p.hue[a].H))),
                (p.hue[b].L, p.hue[b].C * math.cos(math.radians(p.hue[b].H)),
                 p.hue[b].C * math.sin(math.radians(p.hue[b].H))))
            for i, a in enumerate(SYNTAX_HUES) for b in SYNTAX_HUES[i + 1:])
        check(f"{p.name}: token hues stay >= 0.05 apart in Oklab",
              worst >= 0.05, f"worst {worst:.4f}")


def main() -> int:
    groups = [
        ("colour maths", [test_oklch_round_trip, test_srgb_primaries, test_wcag,
                          test_gamut_mapping_holds_hue_and_lightness]),
        ("highlighter", [test_highlighter_preserves_text, test_highlighter_balances_spans,
                         test_highlighter_escapes_markup, test_highlighter_classification]),
        ("theme contract", [test_every_variant_meets_its_floors, test_hue_separation]),
        ("validator", [test_validator_rejects_regressions]),
    ]
    for title, tests in groups:
        print(f"\n{title}")
        for t in tests:
            t()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} failing check(s):", file=sys.stderr)
        for f in FAILURES:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

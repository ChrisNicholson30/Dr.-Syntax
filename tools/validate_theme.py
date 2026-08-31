#!/usr/bin/env python3
"""
Structural validation for themes/dr-syntax.json.

Zed does not hard-fail on a malformed theme; it silently falls back for the keys
it cannot parse, which is exactly the failure mode that ships a broken theme
without anyone noticing. This checks the shape independently of the generator,
so a bug in build_theme.py cannot vouch for its own output.

Checks:
  * document shape ($schema, name, author, themes[])
  * every variant has name / appearance / style, appearance in {dark, light}
  * every colour value is #rrggbbaa (Zed's serialiser emits 8-digit hex)
  * required key coverage against the baseline shipped by Zed's own One theme
  * syntax entries are {color, font_style, font_weight} with legal values
  * players[] is 8 entries of {cursor, background, selection}
  * every syntax token clears its published contrast floor against that
    variant's own editor.background - measured from the shipped colours, not
    recomputed from the generator
  * every syntax token stays readable under every translucent overlay, on both
    the plain background and the active line (the state that hides comments in
    most themes)

Run:  python3 tools/validate_theme.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "themes" / "dr-syntax.json"
BASELINE = ROOT / "tools" / "required_keys.json"

HEX8 = re.compile(r"^#[0-9a-f]{8}$")

# The published contrast contract, asserted against the shipped file.
#
# build_theme.py checks these too, but it checks colours it has just computed in
# memory. That verifies the generator, not the artifact: a themes/dr-syntax.json
# edited by hand, merged badly, or written by an older generator would sail past
# it. These floors are therefore re-derived here from the hex values Zed will
# actually load. Floors sit just under the values the design targets, so this
# asserts the contract rather than pinning today's exact numbers.
AAA_FLOOR = 7.0
TOKEN_FLOORS = {
    "comment": 5.5, "comment.doc": 5.5,   # deliberately recessive
    "hint": 5.5,                          # inlay hints: read, but quiet
    "predictive": 3.0,                    # ghost text for an unaccepted suggestion
    "operator": 4.5, "punctuation": 4.5, "punctuation.bracket": 4.5,
    "punctuation.delimiter": 4.5, "punctuation.list_marker": 4.5,
    "punctuation.markup": 4.5, "punctuation.special": 4.5,
}

# Transient-overlay contrast floor. Sustained reading is asserted in
# build_theme.py against the plain background; this is the selected/highlighted
# state, and clears WCAG's 3:1 threshold for non-text and large text.
FLOOR_OVERLAY = 3.5
# Ghost text for an unaccepted inline suggestion. Deliberately sub-threshold,
# and not buffer content you can select.
OVERLAY_EXEMPT = {"predictive"}
LEGAL_STYLES = {None, "normal", "italic", "oblique"}
LEGAL_WEIGHTS = {None, 100, 200, 300, 400, 500, 600, 700, 800, 900}


def _rgba(value: str) -> tuple[tuple[int, int, int], float]:
    v = value.lstrip("#")
    rgb = tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    return rgb, (int(v[6:8], 16) / 255 if len(v) >= 8 else 1.0)


def _over(value: str, base: tuple[int, int, int]) -> tuple[int, int, int]:
    rgb, a = _rgba(value)
    return tuple(round(a * c + (1 - a) * d) for c, d in zip(rgb, base))


def _luminance(rgb: tuple[int, int, int]) -> float:
    def lin(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def audit_contracts(vname: str, style: dict) -> tuple[list[str], int, float]:
    """Every syntax token against its floor, measured from the shipped hex."""
    errors: list[str] = []
    bg = _rgba(style["editor.background"])[0]
    worst = (99.0, "")
    for token, spec in style["syntax"].items():
        floor = TOKEN_FLOORS.get(token, AAA_FLOOR)
        ratio = _contrast(_rgba(spec["color"])[0], bg)
        if floor >= AAA_FLOOR and ratio < worst[0]:
            worst = (ratio, token)
        if ratio < floor:
            errors.append(f"{vname}: syntax['{token}'] = {ratio:.2f}:1 against "
                          f"editor.background, below its {floor}:1 floor")
    for label, key, floor in (("editor.foreground", "editor.foreground", AAA_FLOOR),
                              ("text", "text", 4.5), ("text.muted", "text.muted", 4.5)):
        ratio = _contrast(_rgba(style[key])[0], bg)
        if ratio < floor:
            errors.append(f"{vname}: {label} = {ratio:.2f}:1, below its {floor}:1 floor")
    return errors, len(style["syntax"]) + 3, worst[0]


def audit_overlays(vname: str, style: dict) -> tuple[list[str], int, float]:
    """Every token, under every overlay, on every surface the overlay lands on."""
    errors: list[str] = []
    ed = _rgba(style["editor.background"])[0]
    active_line = _over(style["editor.active_line.background"], ed)

    texts = {k: _rgba(v["color"])[0] for k, v in style["syntax"].items()
             if k not in OVERLAY_EXEMPT}
    texts["editor.foreground"] = _rgba(style["editor.foreground"])[0]

    overlays = [(f"players[{i}].selection", pl["selection"])
                for i, pl in enumerate(style["players"])]
    overlays += [(k, style[k]) for k in
                 ("element.selection_background", "search.match_background",
                  "search.active_match_background")]

    measured, worst = 0, (99.0, "", "")
    for label, value in overlays:
        for base_name, base in (("editor.background", ed), ("active line", active_line)):
            comp = _over(value, base)
            for token, rgb in texts.items():
                measured += 1
                ratio = _contrast(rgb, comp)
                if ratio < worst[0]:
                    worst = (ratio, f"{label} on {base_name}", token)
                if ratio < FLOOR_OVERLAY:
                    errors.append(f"{vname}: '{token}' on {label} over {base_name} "
                                  f"= {ratio:.2f}:1 < {FLOOR_OVERLAY}:1")

    # Affordances that must be perceivable, or they are simply not there.
    tab_delta = _contrast(_rgba(style["tab.active_background"])[0],
                          _rgba(style["tab.inactive_background"])[0])
    if tab_delta < 1.08:
        errors.append(f"{vname}: active tab is indistinguishable from inactive "
                      f"({tab_delta:.3f}:1)")
    line_delta = _contrast(active_line, ed)
    if not 1.08 <= line_delta <= 1.45:
        errors.append(f"{vname}: active line is {line_delta:.3f}:1 vs background "
                      f"(want 1.08-1.45)")
    sel_vis = _contrast(_over(style["players"][0]["selection"], ed), ed)
    if sel_vis < 1.25:
        errors.append(f"{vname}: selection is barely visible ({sel_vis:.3f}:1)")
    return errors, measured, worst[0]


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    if not THEME.exists():
        print(f"missing {THEME}", file=sys.stderr)
        return 1
    doc = json.loads(THEME.read_text())

    for field in ("$schema", "name", "author", "themes"):
        if field not in doc:
            errors.append(f"document: missing '{field}'")
    if not isinstance(doc.get("themes"), list) or not doc["themes"]:
        errors.append("document: 'themes' must be a non-empty array")
        print("\n".join(errors), file=sys.stderr)
        return 1

    baseline = set(json.loads(BASELINE.read_text())["style"]) if BASELINE.exists() else set()
    baseline_syntax = set(json.loads(BASELINE.read_text())["syntax"]) if BASELINE.exists() else set()

    for variant in doc["themes"]:
        vname = variant.get("name", "<unnamed>")
        if variant.get("appearance") not in ("dark", "light"):
            errors.append(f"{vname}: appearance must be 'dark' or 'light'")
        style = variant.get("style")
        if not isinstance(style, dict):
            errors.append(f"{vname}: missing 'style' object")
            continue

        # -- flat colour keys ------------------------------------------------
        for key, value in style.items():
            if key in ("syntax", "players", "accents"):
                continue
            if not isinstance(value, str) or not HEX8.match(value):
                errors.append(f"{vname}: style['{key}'] = {value!r} is not #rrggbbaa")

        # -- coverage --------------------------------------------------------
        missing = baseline - set(style)
        if missing:
            errors.append(f"{vname}: missing {len(missing)} baseline key(s): "
                          + ", ".join(sorted(missing)[:8]))

        # -- syntax ------------------------------------------------------------
        syntax = style.get("syntax")
        if not isinstance(syntax, dict):
            errors.append(f"{vname}: missing 'syntax' object")
        else:
            for token, spec in syntax.items():
                if not isinstance(spec, dict):
                    errors.append(f"{vname}: syntax['{token}'] must be an object")
                    continue
                extra = set(spec) - {"color", "font_style", "font_weight"}
                if extra:
                    errors.append(f"{vname}: syntax['{token}'] unexpected keys {sorted(extra)}")
                if not HEX8.match(str(spec.get("color", ""))):
                    errors.append(f"{vname}: syntax['{token}'].color is not #rrggbbaa")
                if spec.get("font_style") not in LEGAL_STYLES:
                    errors.append(f"{vname}: syntax['{token}'].font_style "
                                  f"{spec.get('font_style')!r} is not legal")
                if spec.get("font_weight") not in LEGAL_WEIGHTS:
                    errors.append(f"{vname}: syntax['{token}'].font_weight "
                                  f"{spec.get('font_weight')!r} is not legal")
            missing_syn = baseline_syntax - set(syntax)
            if missing_syn:
                errors.append(f"{vname}: missing {len(missing_syn)} baseline syntax key(s): "
                              + ", ".join(sorted(missing_syn)))

        # -- players --------------------------------------------------------------
        players = style.get("players")
        if not isinstance(players, list) or len(players) != 8:
            errors.append(f"{vname}: 'players' must be an array of 8 entries")
        else:
            for i, pl in enumerate(players):
                if set(pl) != {"cursor", "background", "selection"}:
                    errors.append(f"{vname}: players[{i}] must have cursor/background/selection")
                    continue
                for k, v in pl.items():
                    if not HEX8.match(str(v)):
                        errors.append(f"{vname}: players[{i}].{k} is not #rrggbbaa")

        # -- accents ---------------------------------------------------------------
        accents = style.get("accents")
        if accents is not None:
            if not isinstance(accents, list) or not accents:
                errors.append(f"{vname}: 'accents' must be a non-empty array")
            else:
                for i, a in enumerate(accents):
                    if not HEX8.match(str(a)):
                        errors.append(f"{vname}: accents[{i}] is not #rrggbbaa")

        contract_errors, n_contract, worst_aaa = audit_contracts(vname, style)
        errors.extend(contract_errors)
        overlay_errors, measured, worst = audit_overlays(vname, style)
        errors.extend(overlay_errors)

        if not errors:
            n_syn = len(style.get("syntax", {}))
            print(f"  ok  {vname:<20} {len(style) - 3} colour keys, {n_syn} syntax keys, "
                  f"{n_contract} contract checks (worst AAA {worst_aaa:.2f}:1), "
                  f"{measured} overlay measurements (worst {worst:.2f}:1)")

    for w in warnings:
        print(f"  warn  {w}")
    if errors:
        print(f"\n{len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"\nvalid: {len(doc['themes'])} variants, schema {doc['$schema']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

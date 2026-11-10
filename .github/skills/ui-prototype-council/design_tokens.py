#!/usr/bin/env python3
"""Generate web and native tokens from one DESIGN.md, and refuse hand edits to the output.

DESIGN.md (google-labs-code/design.md, schema `version: alpha`) is the only source.
This writes `tokens.css` for the browser and `Tokens.swift` for a SwiftUI client next to
it. Python standard library only; the upstream CLI runs through npx and is not used.

Local extension for themes, which the format lacks: every colour role has four sibling
keys, `<role>`, `<role>-dark`, `<role>-contrast` and `<role>-contrast-dark`. A role that
lacks any of them is refused.

The front matter is parsed as a restricted YAML subset: nested maps with two-space
indentation, `key: value` scalars and inline `{key: value}` maps. Lists, anchors,
multi-line scalars, tabs and comments after a value are refused, not guessed.

  design_tokens.py DESIGN.md           write tokens.css and Tokens.swift
  design_tokens.py --check DESIGN.md   fail if either file differs from a fresh generation
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

THEMES = (("light", ""), ("dark", "-dark"), ("contrast-light", "-contrast"),
          ("contrast-dark", "-contrast-dark"))
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
DIMENSION = re.compile(r"^(-?\d+(?:\.\d+)?)(px|rem|em)?$")
REFERENCE = re.compile(r"^\{([a-z0-9-]+(?:\.[a-z0-9-]+)+)\}$")
FAMILIES = {"system-ui": ("system-ui, -apple-system, sans-serif", ".default"),
            "ui-monospace": ("ui-monospace, SFMono-Regular, Menlo, monospace", ".monospaced")}
WEIGHTS = {100: ".ultraLight", 200: ".thin", 300: ".light", 400: ".regular", 500: ".medium",
           600: ".semibold", 700: ".bold", 800: ".heavy", 900: ".black"}


class TokenError(Exception):
    pass


def scalar(text, where):
    text = text.strip()
    if not text:
        raise TokenError(f"{where}: empty value")
    if text[0] in "\"'":
        if len(text) < 2 or text[-1] != text[0]:
            raise TokenError(f"{where}: unterminated quote")
        return text[1:-1]
    if text[0] in "[&*|>!-" or " #" in text:
        raise TokenError(f"{where}: unsupported YAML construct: {text}")
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def inline_map(text, where):
    body = text.strip()[1:-1].strip()
    result = {}
    for part in filter(None, (p.strip() for p in body.split(","))):
        key, sep, value = part.partition(":")
        if not sep:
            raise TokenError(f"{where}: inline map entry without a colon: {part}")
        result[key.strip()] = scalar(value, where)
    return result


def parse_front_matter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise TokenError("DESIGN.md: front matter must start on the first line")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise TokenError("DESIGN.md: front matter is not closed") from error
    root, stack = {}, [(-1, None)]
    stack[0] = (-1, root)
    for number, raw in enumerate(lines[1:end], start=2):
        where = f"DESIGN.md:{number}"
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw:
            raise TokenError(f"{where}: tabs are not allowed")
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise TokenError(f"{where}: indentation must be a multiple of two spaces")
        key, sep, value = raw.strip().partition(":")
        if not sep or key.startswith("-"):
            raise TokenError(f"{where}: expected 'key: value'")
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if key in parent:
            raise TokenError(f"{where}: duplicate key {key}")
        if not value.strip():
            parent[key] = {}
            stack.append((indent, parent[key]))
        elif value.strip().startswith("{"):
            if not value.strip().endswith("}"):
                raise TokenError(f"{where}: inline map must close on the same line")
            parent[key] = inline_map(value, where)
        else:
            parent[key] = scalar(value, where)
    return root, "\n".join(lines[end + 1:])


def resolve(tokens, value, where, depth=0):
    if not isinstance(value, str):
        return value
    match = REFERENCE.match(value)
    if not match:
        return value
    if depth > 8:
        raise TokenError(f"{where}: reference cycle")
    node = tokens
    for part in match.group(1).split("."):
        if not isinstance(node, dict) or part not in node:
            raise TokenError(f"{where}: broken reference {value}")
        node = node[part]
    return resolve(tokens, node, where, depth + 1)


def camel(name):
    head, *rest = re.split(r"[-_.]", name)
    ident = head + "".join(word[:1].upper() + word[1:] for word in rest)
    return ident if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ident) else "_" + ident


def dimension(value, where):
    match = DIMENSION.match(str(value))
    if not match:
        raise TokenError(f"{where}: not a dimension: {value}")
    number, unit = float(match.group(1)), match.group(2) or "px"
    points = number * 16 if unit in ("rem", "em") else number
    return f"{match.group(1)}{unit}", points


def number_text(value):
    return f"{value:g}"


def build(tokens):
    colors = tokens.get("colors")
    if not isinstance(colors, dict) or not colors:
        raise TokenError("DESIGN.md: colors are required")
    roles = sorted({re.sub(r"(-contrast-dark|-contrast|-dark)$", "", k) for k in colors})
    palettes = {theme: {} for theme, _ in THEMES}
    for role in roles:
        for theme, suffix in THEMES:
            key = role + suffix
            if key not in colors:
                raise TokenError(f"colors.{role}: missing theme variant {key}")
            value = resolve(tokens, colors[key], f"colors.{key}")
            if not isinstance(value, str) or not HEX.match(value):
                raise TokenError(f"colors.{key}: must be #RRGGBB for both outputs, got {value!r}")
            palettes[theme][role] = value.lower()

    spacing = {k: dimension(resolve(tokens, v, f"spacing.{k}"), f"spacing.{k}")
               for k, v in (tokens.get("spacing") or {}).items()}
    rounded = {k: dimension(resolve(tokens, v, f"rounded.{k}"), f"rounded.{k}")
               for k, v in (tokens.get("rounded") or {}).items()}
    typography = {}
    for name, style in (tokens.get("typography") or {}).items():
        where = f"typography.{name}"
        if not isinstance(style, dict):
            raise TokenError(f"{where}: must be a map")
        family = style.get("fontFamily", "system-ui")
        if family not in FAMILIES:
            raise TokenError(f"{where}: fontFamily must be one of {sorted(FAMILIES)}; no web fonts")
        size = dimension(resolve(tokens, style.get("fontSize"), where), where)
        weight = int(style.get("fontWeight", 400))
        if weight not in WEIGHTS:
            raise TokenError(f"{where}: fontWeight must be a multiple of 100 from 100 to 900")
        line = style.get("lineHeight", 1.4)
        if not isinstance(line, (int, float)):
            raise TokenError(f"{where}: lineHeight must be a unitless multiplier")
        typography[name] = {"family": family, "size": size, "weight": weight, "line": line,
                            "tabular": "tnum" in str(style.get("fontFeature", ""))}
    for name, component in (tokens.get("components") or {}).items():
        for prop, value in (component or {}).items():
            resolve(tokens, value, f"components.{name}.{prop}")
    return palettes, spacing, rounded, typography


def css(palettes, spacing, rounded, typography, digest):
    def block(selector, palette):
        body = "".join(f"  --color-{role}: {value};\n" for role, value in palette.items())
        return f"{selector} {{\n{body}}}\n"
    out = [f"/* Generated from DESIGN.md (sha256 {digest}) by design_tokens.py. Do not edit. */\n",
           ":root {\n"]
    out += [f"  --space-{k}: {v[0]};\n" for k, v in spacing.items()]
    out += [f"  --radius-{k}: {v[0]};\n" for k, v in rounded.items()]
    for name, t in typography.items():
        out += [f"  --type-{name}-family: {FAMILIES[t['family']][0]};\n",
                f"  --type-{name}-size: {t['size'][0]};\n",
                f"  --type-{name}-weight: {t['weight']};\n",
                f"  --type-{name}-line-height: {number_text(t['line'])};\n",
                f"  --type-{name}-numeric: {'tabular-nums' if t['tabular'] else 'normal'};\n"]
    out.append("}\n")
    out.append(block(":root", palettes["light"]))
    out.append("@media (prefers-color-scheme: dark) {\n" + block(":root", palettes["dark"]) + "}\n")
    out.append("@media (prefers-contrast: more) {\n" + block(":root", palettes["contrast-light"]) + "}\n")
    out.append("@media (prefers-color-scheme: dark) and (prefers-contrast: more) {\n"
               + block(":root", palettes["contrast-dark"]) + "}\n")
    for theme in palettes:
        out.append(block(f':root[data-theme="{theme}"]', palettes[theme]))
    return "".join(out)


def swift(palettes, spacing, rounded, typography, digest):
    def color(value):
        r, g, b = (int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return f"Color(red: {r:.4f}, green: {g:.4f}, blue: {b:.4f})"
    roles = list(palettes["light"])
    out = [f"// Generated from DESIGN.md (sha256 {digest}) by design_tokens.py. Do not edit.\n",
           "import SwiftUI\n\n",
           "public struct DesignPalette: Sendable {\n"]
    out += [f"    public let {camel(r)}: Color\n" for r in roles]
    out.append("}\n\npublic struct DesignTypeStyle: Sendable {\n"
               "    public let size: CGFloat\n    public let weight: Font.Weight\n"
               "    public let design: Font.Design\n    public let lineHeight: CGFloat\n"
               "    public let tabularDigits: Bool\n"
               "    public var font: Font {\n"
               "        let base = Font.system(size: size, weight: weight, design: design)\n"
               "        return tabularDigits ? base.monospacedDigit() : base\n    }\n}\n\n")
    out.append("public enum DesignTokens {\n")
    for theme in palettes:
        args = ", ".join(f"{camel(r)}: {color(palettes[theme][r])}" for r in roles)
        out.append(f"    public static let {camel(theme)} = DesignPalette({args})\n")
    out.append("\n    public enum Spacing {\n")
    out += [f"        public static let {camel(k)}: CGFloat = {number_text(v[1])}\n" for k, v in spacing.items()]
    out.append("    }\n\n    public enum Radius {\n")
    out += [f"        public static let {camel(k)}: CGFloat = {number_text(v[1])}\n" for k, v in rounded.items()]
    out.append("    }\n\n    public enum Typography {\n")
    for name, t in typography.items():
        out.append(f"        public static let {camel(name)} = DesignTypeStyle(size: {number_text(t['size'][1])}, "
                   f"weight: {WEIGHTS[t['weight']]}, design: {FAMILIES[t['family']][1]}, "
                   f"lineHeight: {number_text(t['line'])}, tabularDigits: {'true' if t['tabular'] else 'false'})\n")
    out.append("    }\n}\n")
    return "".join(out)


def generate(design):
    text = design.read_text(encoding="utf-8")
    tokens, _ = parse_front_matter(text)
    if tokens.get("version") != "alpha":
        raise TokenError("DESIGN.md: version must be 'alpha', the schema this generator was checked against")
    digest = hashlib.sha256(text.encode()).hexdigest()
    parts = build(tokens)
    return {design.parent / "tokens.css": css(*parts, digest),
            design.parent / "Tokens.swift": swift(*parts, digest)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("designs", nargs="+", type=Path)
    args = parser.parse_args(argv)
    failed = False
    for design in args.designs:
        try:
            outputs = generate(design)
        except (OSError, TokenError) as error:
            print(f"design-tokens: {error}", file=sys.stderr)
            return 1
        for path, content in outputs.items():
            if args.check:
                if not path.exists() or path.read_text(encoding="utf-8") != content:
                    print(f"design-tokens: {path} differs from DESIGN.md; regenerate, never hand-edit",
                          file=sys.stderr)
                    failed = True
            else:
                path.write_text(content, encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

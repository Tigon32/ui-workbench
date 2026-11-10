#!/usr/bin/env python3
"""Render a static page in the installed Chrome and check what only a rendered page can show.

Tier 2 of the prototype council: deterministic, no network, no dependency, no model.
It drives Chrome over the DevTools Protocol (CDP) with a minimal WebSocket client written
on the standard library, so nothing is installed and no browser is downloaded.

Checks, per page:
  contrast      computed text colour against its effective background, WCAG 2.2 1.4.3
  target-size   interactive targets at least 24 by 24 CSS pixels or spaced, 2.5.8
  reflow        no horizontal page scrolling at 320 CSS pixels, 1.4.10
  focus         a visible focus indicator (2.4.7) that is not fully obscured (2.4.11)
  literal       a colour literal outside a custom property declaration
  hover-only    a :hover rule with no :focus-visible or :focus-within counterpart
  text          each required string is present as rendered text
  network       a resource or reference outside the local file, which a portable page must not need
  forbid        a forbidden phrase or pattern in rendered text (case-insensitive regular expressions)
  budget        more visible words in the first viewport at 1280 by 900 than the stated budget
  clicks        a scripted task needs more clicks than its budget, or does not reach its goal
  modal         a click opened a modal dialog (dialog:modal or aria-modal="true")

Optional rubric checks cover visible control/name parity between ordinary light and dark
themes, reduced-motion duration limits, named font/spacing scales, and clipping in marked
text-expansion fixtures. They do not prove complete accessibility, motion compliance,
theme equivalence, or interaction completeness.

Limits, stated rather than hidden: contrast is skipped for text over a background image
and under forced colors, where the user agent owns colour. Captures are not
version-pinned; the browser version is printed so a round can record it.
"""

import argparse
import base64
import collections
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PROFILE_SPEC = importlib.util.spec_from_file_location(
    "render_profiles", Path(__file__).with_name("profiles.py"))
PROFILES = importlib.util.module_from_spec(PROFILE_SPEC)
PROFILE_SPEC.loader.exec_module(PROFILES)

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
THEMES = {
    "light": [("prefers-color-scheme", "light"), ("prefers-contrast", "no-preference")],
    "dark": [("prefers-color-scheme", "dark"), ("prefers-contrast", "no-preference")],
    "high-contrast-light": [("prefers-color-scheme", "light"), ("prefers-contrast", "more")],
    "high-contrast-dark": [("prefers-color-scheme", "dark"), ("prefers-contrast", "more")],
}
CHECK_WIDTH, REFLOW_WIDTH, HEIGHT = 1280, 320, 900
CAPTURE_WIDTHS = (1280, 1440, 320)

AUDIT = r"""
(async (opts) => {
  const out = [];
  const add = (check, el, detail) => out.push({check, where: el ? describe(el) : "page", detail});
  function describe(el) {
    const id = el.id ? "#" + el.id : "";
    const text = (el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 40);
    return el.tagName.toLowerCase() + id + (text ? ` "${text}"` : "");
  }
  function rgba(value) {
    const m = value.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  }
  const over = (top, under) => {
    const a = top[3];
    return [0, 1, 2].map(i => top[i] * a + under[i] * (1 - a)).concat(1);
  };
  const lum = (c) => {
    const ch = c.slice(0, 3).map(v => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const visible = (el) => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.visibility !== "hidden" && s.display !== "none" && Number(s.opacity) > 0 && r.width > 1 && r.height > 1;
  };
  function background(el) {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (s.backgroundImage !== "none") return null;
      const c = rgba(s.backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
    }
    let base = [255, 255, 255, 1];
    for (const layer of layers.reverse()) base = over(layer, base);
    return base;
  }

  if (opts.mode === "reflow") {
    if (document.documentElement.scrollWidth > innerWidth + 1)
      add("reflow", null, `page is ${document.documentElement.scrollWidth}px wide at ${innerWidth}px`);
    return out;
  }

  if (!opts.forced) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set();
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      const el = t.parentElement;
      if (!el || seen.has(el) || !t.textContent.trim() || !visible(el)) continue;
      seen.add(el);
      const s = getComputedStyle(el);
      const fg = rgba(s.color), bg = background(el);
      if (!fg || !bg) continue;
      const size = parseFloat(s.fontSize), bold = Number(s.fontWeight) >= 700;
      const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
      const r = ratio(over(fg, bg), bg);
      if (r < need) add("contrast", el, `${r.toFixed(2)}:1 < ${need}:1`);
    }
  }

  const focusable = [...document.querySelectorAll(
    'a[href],button,input,select,textarea,summary,[tabindex]:not([tabindex="-1"]),[role=button],[role=tab],[role=radio],[role=checkbox],[role=switch]'
  )].filter(el => !el.disabled && visible(el));
  const boxes = focusable.map(el => el.getBoundingClientRect());
  // 2.5.8 spacing exception: a 24px circle centred on an undersized target must not
  // intersect another target, nor the circle of another undersized target.
  const small = boxes.map(r => r.width < 24 || r.height < 24);
  const centre = (r) => [r.left + r.width / 2, r.top + r.height / 2];
  const distance = ([x, y], o) => Math.hypot(Math.max(o.left - x, 0, x - o.right), Math.max(o.top - y, 0, y - o.bottom));
  focusable.forEach((el, i) => {
    const r = boxes[i];
    const inline = getComputedStyle(el).display === "inline" && el.closest("p,li,td,dd");
    if (inline || !small[i]) return;
    const c = centre(r);
    const crowded = boxes.some((o, j) => j !== i && !el.contains(focusable[j]) && !focusable[j].contains(el) &&
      (distance(c, o) < 12 || (small[j] && Math.hypot(c[0] - centre(o)[0], c[1] - centre(o)[1]) < 24)));
    if (crowded) add("target-size", el, `${r.width.toFixed(0)}x${r.height.toFixed(0)} without 24px spacing`);
  });

  const keys = ["outlineStyle", "outlineWidth", "outlineColor", "boxShadow", "borderColor", "backgroundColor", "textDecorationLine"];
  for (const el of focusable) {
    document.activeElement && document.activeElement.blur && document.activeElement.blur();
    const before = getComputedStyle(el), was = Object.fromEntries(keys.map(k => [k, before[k]]));
    el.focus();
    if (document.activeElement !== el) continue;
    el.scrollIntoView({block: "nearest", inline: "nearest"});
    const now = getComputedStyle(el);
    const outline = now.outlineStyle !== "none" && parseFloat(now.outlineWidth) > 0;
    const changed = keys.some(k => now[k] !== was[k]);
    if (!outline && !changed) add("focus", el, "no visible change on focus");
    const r = el.getBoundingClientRect();
    const points = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + 2, r.top + 2], [r.right - 2, r.bottom - 2]];
    const shown = points.some(([x, y]) => { const hit = document.elementFromPoint(x, y); return hit && (hit === el || el.contains(hit) || hit.contains(el)); });
    if (!shown) add("focus", el, "focused element is fully obscured");
    el.blur();
  }

  const literal = /#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color(?:-mix)?)\(/i;
  const hover = [], focusSel = new Set();
  const walk = (rules) => { for (const rule of rules) {
    if (rule.cssRules && !rule.selectorText) { walk(rule.cssRules); continue; }
    if (!rule.style) continue;
    for (const prop of rule.style) {
      if (prop.startsWith("--")) continue;
      const v = rule.style.getPropertyValue(prop);
      if (literal.test(v)) add("literal", null, `${rule.selectorText} { ${prop}: ${v} }`);
    }
    for (const sel of (rule.selectorText || "").split(",").map(s => s.trim())) {
      if (sel.includes(":hover")) hover.push(sel);
      if (sel.includes(":focus-visible") || sel.includes(":focus-within")) focusSel.add(sel);
    }
    if (rule.cssRules) walk(rule.cssRules);
  }};
  for (const sheet of document.styleSheets) {
    try { walk(sheet.cssRules); } catch (e) { add("literal", null, `stylesheet not auditable: ${sheet.href}`); }
  }
  for (const entry of performance.getEntriesByType("resource")) {
    if (!entry.name.startsWith("file:") && !entry.name.startsWith("data:")) add("network", null, `external resource: ${entry.name}`);
  }
  for (const el of document.querySelectorAll("link[href],script[src],img[src],iframe[src]")) {
    const url = el.href || el.src;
    if (url && !url.startsWith("file:") && !url.startsWith("data:")) add("network", el, `external reference: ${url}`);
  }
  for (const el of document.querySelectorAll("[style]")) {
    if (literal.test(el.getAttribute("style").replace(/--[\w-]+\s*:[^;]+;?/g, ""))) add("literal", el, "inline style colour");
  }
  for (const sel of hover) {
    if (!opts.ignoreHoverOnly &&
        !focusSel.has(sel.replace(":hover", ":focus-visible")) &&
        !focusSel.has(sel.replace(":hover", ":focus-within")))
      add("hover-only", null, `${sel} has no :focus-visible or :focus-within counterpart`);
  }

  const text = document.body.innerText;
  for (const want of opts.expect) if (!text.includes(want)) add("text", null, `missing rendered text: ${want}`);
  for (const pattern of opts.forbid) {
    const hit = text.match(new RegExp(pattern, "iu"));
    if (hit) add("forbid", null, `forbidden text: "${hit[0]}"`);
  }
  if (opts.budget) {
    let words = 0;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      const el = t.parentElement;
      if (!el || !t.textContent.trim() || !visible(el)) continue;
      const range = document.createRange(); range.selectNodeContents(t);
      const r = range.getBoundingClientRect();
      if (r.bottom <= 0 || r.top >= innerHeight || r.right <= 0 || r.left >= innerWidth) continue;
      words += t.textContent.trim().split(/\s+/).length;
    }
    if (words > opts.budget) add("budget", null, `${words} visible words in the first viewport > ${opts.budget}`);
  }
  return out;
})
"""

QUALITY_AUDIT = r"""
(async (opts) => {
  const found = [], unknown = [];
  const visible = (el) => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== "none" && s.visibility !== "hidden" && Number(s.opacity) > 0 &&
      r.width > 1 && r.height > 1;
  };
  const role = (el) => {
    if (el.getAttribute("role")) return el.getAttribute("role");
    return ({BUTTON: "button", A: "link", SELECT: "combobox", TEXTAREA: "textbox",
      INPUT: ({button:"button",checkbox:"checkbox",radio:"radio",submit:"button",reset:"button"})[
        (el.type || "").toLowerCase()] || "textbox", SUMMARY: "button"})[el.tagName] || "control";
  };
  const name = (el) => {
    const labelledBy = (el.getAttribute("aria-labelledby") || "").split(/\s+/)
      .filter(Boolean).map(id => document.getElementById(id)?.innerText || "")
      .join(" ").replace(/\s+/g, " ").trim();
    const labelled = labelledBy || el.getAttribute("aria-label") ||
      (el.labels && [...el.labels].map(label => label.innerText).join(" ")) ||
      el.innerText || el.value || el.getAttribute("title") || "";
    return labelled.replace(/\s+/g, " ").trim().toLowerCase();
  };
  let controls = null;
  if (opts.semantic_control_parity) {
    controls = [...document.querySelectorAll(
      'a[href],button,input,select,textarea,summary,[tabindex]:not([tabindex="-1"]),'
      + '[role=button],[role=link],[role=tab],[role=radio],[role=checkbox],[role=switch],'
      + '[role=menuitem],[role=option],[role=combobox],[role=textbox]'
    )].filter(visible).map(el =>
      `${role(el)}\u0000${name(el) || "[unnamed]"}\u0000` +
      `${el.disabled ? "disabled" : "enabled"}\u0000` +
      `${el.getAttribute("aria-disabled") === "true" ? "aria-disabled" : "aria-enabled"}`).sort();
    if (!controls.length) unknown.push("no visible controls to compare");
  }
  if (opts.reduced_motion_max_ms != null) {
    const time = (value) => value.endsWith("ms") ? parseFloat(value) :
      value.endsWith("s") ? parseFloat(value) * 1000 : 0;
    let inspected = 0;
    for (const el of document.querySelectorAll("*")) {
      if (el.hasAttribute("data-motion-essential")) continue;
      inspected++;
      const style = getComputedStyle(el);
      for (const [kind, durations, delays] of [
        ["animation", style.animationDuration, style.animationDelay],
        ["transition", style.transitionDuration, style.transitionDelay]
      ]) {
        const ds = durations.split(",").map(time), ls = delays.split(",").map(time);
        const total = Math.max(0, ...ds.map((d, i) => d + (ls[i % ls.length] || 0)));
        if (total > opts.reduced_motion_max_ms)
          found.push({check: "reduced-motion-duration", where: el.tagName.toLowerCase(),
            detail: `${kind} ${total.toFixed(0)}ms > declared ${opts.reduced_motion_max_ms}ms`});
      }
    }
    if (!inspected) unknown.push("page has no elements to inspect for reduced-motion duration");
  }
  const scales = [
    ["typography_scale_px", "--font-size-", "font-size-token-scale"],
    ["spacing_scale_px", "--space-", "spacing-token-scale"]
  ];
  for (const [key, prefix, check] of scales) {
    if (!opts[key]) continue;
    let count = 0;
    for (const sheet of document.styleSheets) {
      try {
        const walk = rules => { for (const rule of rules) {
          if (rule.style) for (const prop of rule.style) {
            if (!prop.startsWith(prefix)) continue;
            count++;
            const value = rule.style.getPropertyValue(prop).trim().match(/^(\d+(?:\.\d+)?)px$/);
            if (!value || !opts[key].some(n => Math.abs(Number(value[1]) - n) < 0.01))
              found.push({check, where: prop, detail:
                `${rule.style.getPropertyValue(prop).trim()} is outside declared scale`});
          }
          if (rule.cssRules) walk(rule.cssRules);
        }};
        walk(sheet.cssRules);
      } catch (_) { unknown.push(`${key}: a stylesheet is not inspectable`); }
    }
    if (!count) unknown.push(`${key}: no ${prefix} custom properties were found`);
  }
  if (opts.spacing_scale_px) {
    const spacingProps = new Map([
      ["margin", ["marginTop", "marginRight", "marginBottom", "marginLeft"]],
      ["margin-top", ["marginTop"]], ["margin-right", ["marginRight"]],
      ["margin-bottom", ["marginBottom"]], ["margin-left", ["marginLeft"]],
      ["margin-block", ["marginBlockStart", "marginBlockEnd"]],
      ["margin-block-start", ["marginBlockStart"]], ["margin-block-end", ["marginBlockEnd"]],
      ["margin-inline", ["marginInlineStart", "marginInlineEnd"]],
      ["margin-inline-start", ["marginInlineStart"]], ["margin-inline-end", ["marginInlineEnd"]],
      ["padding", ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft"]],
      ["padding-top", ["paddingTop"]], ["padding-right", ["paddingRight"]],
      ["padding-bottom", ["paddingBottom"]], ["padding-left", ["paddingLeft"]],
      ["padding-block", ["paddingBlockStart", "paddingBlockEnd"]],
      ["padding-block-start", ["paddingBlockStart"]], ["padding-block-end", ["paddingBlockEnd"]],
      ["padding-inline", ["paddingInlineStart", "paddingInlineEnd"]],
      ["padding-inline-start", ["paddingInlineStart"]], ["padding-inline-end", ["paddingInlineEnd"]],
      ["gap", ["rowGap", "columnGap"]], ["row-gap", ["rowGap"]], ["column-gap", ["columnGap"]]
    ]);
    const candidates = new Map();
    const mark = (el, declaration) => {
      for (const property of spacingProps.get(declaration) || []) {
        if (!candidates.has(el)) candidates.set(el, new Set());
        candidates.get(el).add(property);
      }
    };
    const walkSpacing = rules => { for (const rule of rules) {
      if (rule.conditionText && rule.constructor.name === "CSSMediaRule" &&
          !matchMedia(rule.conditionText).matches) continue;
      if (rule.conditionText && rule.constructor.name === "CSSSupportsRule" &&
          !CSS.supports(rule.conditionText)) continue;
      if (rule.style && rule.selectorText) {
        const declarations = [...rule.style].filter(prop => spacingProps.has(prop));
        if (declarations.length) {
          try {
            for (const el of document.querySelectorAll(rule.selectorText))
              if (visible(el)) for (const prop of declarations) mark(el, prop);
          } catch (_) { unknown.push("spacing scale: a selector could not be inspected"); }
        }
      }
      if (rule.cssRules) walkSpacing(rule.cssRules);
    }};
    for (const sheet of document.styleSheets) {
      try { walkSpacing(sheet.cssRules); }
      catch (_) { unknown.push("spacing scale: a stylesheet is not inspectable"); }
    }
    for (const el of document.querySelectorAll("[style]")) {
      if (!visible(el)) continue;
      for (const declaration of spacingProps.keys())
        if (el.style.getPropertyValue(declaration)) mark(el, declaration);
    }
    let inspectedSpacing = 0;
    for (const [el, properties] of candidates) for (const property of properties) {
      inspectedSpacing++;
      const cssProperty = property.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`);
      const computed = el.computedStyleMap().get(cssProperty)?.toString();
      if (computed === "auto" || computed === "normal") continue;
      const value = getComputedStyle(el)[property].trim().toLowerCase();
      if (value === "auto" || value === "normal" || value === "0" || value === "0px") continue;
      const pixels = value.match(/^(-?\d+(?:\.\d+)?)px$/);
      if (!pixels || !opts.spacing_scale_px.some(n => Math.abs(Number(pixels[1]) - n) < 0.01))
        found.push({check: "spacing-scale", where: el.tagName.toLowerCase(),
          detail: `${property}: ${value} is outside declared spacing scale`});
    }
    if (!inspectedSpacing)
      unknown.push("spacing scale: no visible author-declared margin, padding, or gap properties were found");
  }
  if (opts.typography_scale_px) {
    const seen = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let text = walker.nextNode(); text; text = walker.nextNode()) {
      const el = text.parentElement;
      if (!el || seen.has(el) || !text.textContent.trim() || !visible(el)) continue;
      seen.add(el);
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (!opts.typography_scale_px.some(n => Math.abs(n - size) < 0.1))
        found.push({check: "typography-scale", where: el.tagName.toLowerCase(),
          detail: `${size.toFixed(1)}px is outside declared typography scale`});
    }
    if (!seen.size) unknown.push("typography scale: no visible text was found");
  }
  if (opts.text_expansion_factor != null) {
    const roots = [...document.querySelectorAll("[data-text-expansion]")];
    if (!roots.length) unknown.push("text expansion: no [data-text-expansion] fixture was found");
    else {
      const targets = new Set(roots.flatMap(root => [root, ...root.querySelectorAll("*")]));
      for (const el of targets) {
        if (!el.textContent.trim()) continue;
        const size = parseFloat(getComputedStyle(el).fontSize);
        el.style.setProperty("font-size", `${size * opts.text_expansion_factor}px`, "important");
      }
      for (const el of targets) {
        if (!el.textContent.trim()) continue;
        const style = getComputedStyle(el);
        const clippedX = ["hidden", "clip"].includes(style.overflowX) && el.scrollWidth > el.clientWidth + 1;
        const clippedY = ["hidden", "clip"].includes(style.overflowY) && el.scrollHeight > el.clientHeight + 1;
        if (clippedX || clippedY)
          found.push({check: "text-expansion-clipping", where: el.tagName.toLowerCase(),
            detail: `text clips after ${opts.text_expansion_factor}x expansion`});
      }
    }
  }
  return {findings: found, unknown, controls};
})
"""

TASK_STEP = r"""
(async (label) => {
  const norm = (t) => (t || "").replace(/\s+/g, " ").trim().toLowerCase();
  const want = norm(label);
  const shown = (el) => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.visibility !== "hidden" && s.display !== "none" && r.width > 0 && r.height > 0;
  };
  const candidates = [...document.querySelectorAll(
    'button,a[href],summary,input,select,[role=button],[role=tab],[role=link],[role=checkbox],[role=menuitem],[tabindex="0"]'
  )].filter(el => !el.disabled && shown(el));
  const name = (el) => norm(el.getAttribute("aria-label") || (el.labels && el.labels[0] && el.labels[0].innerText) || el.innerText || el.value);
  const rank = (el) => { const n = name(el); return n === want ? 0 : n.startsWith(want) ? 1 : n.includes(want) ? 2 : 9; };
  const best = candidates.map(el => [rank(el), name(el).length, el]).filter(([r]) => r < 9)
    .sort((a, b) => a[0] - b[0] || a[1] - b[1])[0];
  if (!best) return {ok: false, detail: `no visible control named "${label}"`};
  best[2].click();
  await new Promise(r => setTimeout(r, 60));
  const modal = document.querySelector("dialog:modal") ||
    [...document.querySelectorAll('[aria-modal="true"]')].find(shown);
  return {ok: true, modal: modal ? (modal.getAttribute("aria-label") || modal.tagName.toLowerCase()) : null};
})
"""


def run_tasks(browser, page, tasks, width=CHECK_WIDTH):
    """Run each scripted task from a fresh load and count its clicks against the budget."""
    found, counts = [], []
    url = page.resolve().as_uri()
    for task in tasks:
        browser.call("Page.navigate", wait_event="Page.loadEventFired", url="about:blank")
        browser.load(url + task.get("start", ""), width, "light", False)
        clicks, failed = 0, False
        for label in task["clicks"]:
            result = browser.evaluate(f"{TASK_STEP}({json.dumps(label)})")
            if not result["ok"]:
                found.append({"check": "clicks", "where": task["name"], "detail": result["detail"]})
                failed = True
                break
            clicks += 1
            if result.get("modal"):
                found.append({"check": "modal", "where": task["name"],
                              "detail": f"clicking \"{label}\" opened a modal ({result['modal']})"})
        if not failed:
            text = browser.evaluate("document.body.innerText")
            if task["goal"] not in text:
                found.append({"check": "clicks", "where": task["name"],
                              "detail": f"goal text not visible after {clicks} click(s): {task['goal']}"})
            elif clicks > task["max_clicks"]:
                found.append({"check": "clicks", "where": task["name"],
                              "detail": f"{clicks} clicks > budget {task['max_clicks']}"})
        counts.append((task["name"], clicks, task["max_clicks"]))
    for item in found:
        item["config"] = f"light {width}"
    return found, counts


class CdpError(Exception):
    pass


class WebSocket:
    """A minimal RFC 6455 client: masked text frames out, unfragmented frames in."""

    def __init__(self, url):
        host_port, path = url.removeprefix("ws://").split("/", 1)
        host, port = host_port.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        reply = b""
        while b"\r\n\r\n" not in reply:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CdpError("WebSocket handshake closed")
            reply += chunk
        if b" 101 " not in reply.split(b"\r\n", 1)[0]:
            raise CdpError("WebSocket handshake refused")
        self.buffer = reply.split(b"\r\n\r\n", 1)[1]

    def send(self, text):
        data, mask = text.encode(), os.urandom(4)
        size = len(data)
        head = bytes([0x81])
        if size < 126:
            head += bytes([0x80 | size])
        elif size < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", size)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", size)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, count):
        while len(self.buffer) < count:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise CdpError("WebSocket closed")
            self.buffer += chunk
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def receive(self):
        message = b""
        while True:
            first, second = self._read(2)
            size = second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._read(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._read(8))[0]
            message += self._read(size)
            if first & 0x80:
                return message.decode()


class Browser:
    def __init__(self, chrome):
        self.profile = tempfile.mkdtemp(prefix="render-check-")
        self.process = subprocess.Popen(
            [chrome, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={self.profile}",
             "--allow-file-access-from-files", "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars",
             "--disable-background-networking", "--disable-component-update", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = Path(self.profile) / "DevToolsActivePort"
        deadline = time.monotonic() + 15
        while not (port_file.exists() and len(port_file.read_text().splitlines()) >= 2):
            if time.monotonic() > deadline or self.process.poll() is not None:
                self.close()
                raise CdpError("Chrome did not start")
            time.sleep(0.02)
        self.port = port_file.read_text().splitlines()[0]
        targets = self._http("/json/list")
        self.version = self._http("/json/version")["Browser"]
        page = next(t for t in targets if t["type"] == "page")
        self.ws = WebSocket(page["webSocketDebuggerUrl"])
        self.next_id = 0
        self.call("Page.enable")

    def _http(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as reply:
            return json.load(reply)

    def call(self, method, wait_event=None, **params):
        self.next_id += 1
        ident = self.next_id
        self.ws.send(json.dumps({"id": ident, "method": method, "params": params}))
        result, seen_event = None, wait_event is None
        while result is None or not seen_event:
            message = json.loads(self.ws.receive())
            if message.get("id") == ident:
                if "error" in message:
                    raise CdpError(f"{method}: {message['error'].get('message')}")
                result = message.get("result", {})
            elif message.get("method") == wait_event:
                seen_event = True
        return result

    def load(self, url, width, theme, forced, reduced_motion=False):
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=HEIGHT,
                  deviceScaleFactor=1, mobile=False)
        features = [{"name": n, "value": v} for n, v in THEMES[theme]]
        features.append({"name": "forced-colors", "value": "active" if forced else "none"})
        if reduced_motion:
            features.append({"name": "prefers-reduced-motion", "value": "reduce"})
        self.call("Emulation.setEmulatedMedia", features=features)
        self.call("Page.navigate", wait_event="Page.loadEventFired", url=url)

    def evaluate(self, expression):
        reply = self.call("Runtime.evaluate", expression=expression, awaitPromise=True,
                          returnByValue=True)
        if "exceptionDetails" in reply:
            raise CdpError(f"audit failed: {reply['exceptionDetails'].get('text')}")
        return reply["result"]["value"]

    def screenshot(self, path, full_page=False):
        params = {"format": "png"}
        if full_page:
            size = self.call("Page.getLayoutMetrics")["cssContentSize"]
            params.update(captureBeyondViewport=True, clip={
                "x": 0, "y": 0, "width": size["width"], "height": min(size["height"], 6000), "scale": 1})
        data = self.call("Page.captureScreenshot", **params)["data"]
        Path(path).write_bytes(base64.b64decode(data))

    def close(self):
        if getattr(self, "ws", None):
            self.ws.sock.close()
        if getattr(self, "process", None) and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


def check_page(browser, page, expect, forbid=(), budget=0):
    url = page.resolve().as_uri()
    found = []
    for theme in THEMES:
        for forced in (False, True):
            browser.load(url, CHECK_WIDTH, theme, forced)
            # One Tab press puts the page in keyboard modality, so script focus then
            # matches :focus-visible as it would for a keyboard user.
            browser.call("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab",
                         windowsVirtualKeyCode=9)
            browser.call("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab",
                         windowsVirtualKeyCode=9)
            # The word budget applies to the default view only, measured once in light.
            options = json.dumps({"mode": "full", "forced": forced, "expect": expect,
                                  "forbid": list(forbid),
                                  "budget": budget if (theme, forced) == ("light", False) else 0})
            for item in browser.evaluate(f"{AUDIT}({options})"):
                item["config"] = f"{theme}{' forced' if forced else ''} {CHECK_WIDTH}"
                found.append(item)
    browser.load(url, REFLOW_WIDTH, "light", False)
    for item in browser.evaluate(f"{AUDIT}({json.dumps({'mode': 'reflow'})})"):
        item["config"] = f"light {REFLOW_WIDTH}"
        found.append(item)
    unique, seen = [], set()
    for item in found:
        key = (item["check"], item["where"], item["detail"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def check_page_profiles(browser, page, expect, forbid, budget, profiles):
    """Run bounded viewport checks and declared quality checks for target profiles."""
    url = page.resolve().as_uri()
    found, unknown = [], []
    if CHECK_WIDTH not in profiles["widths"]:
        baseline = check_page(browser, page, expect, forbid, budget)
        found.extend(item for item in baseline if item["check"] not in ("hover-only", "reflow"))
    for width in profiles["widths"]:
        for theme in THEMES:
            for forced in (False, True):
                browser.load(url, width, theme, forced)
                browser.call("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab",
                             windowsVirtualKeyCode=9)
                browser.call("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab",
                             windowsVirtualKeyCode=9)
                options = json.dumps({
                    "mode": "full", "forced": forced, "expect": expect,
                    "forbid": list(forbid),
                    "budget": budget if (theme, forced, width) == ("light", False, CHECK_WIDTH) else 0,
                    "ignoreHoverOnly": True,
                })
                for item in browser.evaluate(f"{AUDIT}({options})"):
                    item["config"] = f"{theme}{' forced' if forced else ''} {width}"
                    found.append(item)

    browser.load(url, REFLOW_WIDTH, "light", False)
    for item in browser.evaluate(f"{AUDIT}({json.dumps({'mode': 'reflow'})})"):
        item["config"] = "zoom/reflow (not phone) 320"
        found.append(item)

    quality = profiles["quality_checks"]
    for width in profiles["widths"]:
        if quality.get("semantic_control_parity"):
            observed = {}
            for theme in ("light", "dark"):
                browser.load(url, width, theme, False)
                result = browser.evaluate(
                    f"{QUALITY_AUDIT}({json.dumps({'semantic_control_parity': True})})")
                observed[theme] = result["controls"] or []
                if result["unknown"]:
                    unknown.append(f"{theme} {width}: {result['unknown'][0]}")
            if observed["light"] != observed["dark"] and (observed["light"] or observed["dark"]):
                missing_dark = list((collections.Counter(observed["light"]) -
                                     collections.Counter(observed["dark"])).elements())
                missing_light = list((collections.Counter(observed["dark"]) -
                                      collections.Counter(observed["light"])).elements())
                found.append({
                    "check": "semantic-control-parity",
                    "where": "page",
                    "detail": f"light-only {missing_dark}; dark-only {missing_light}",
                    "config": f"light/dark {width}",
                })

        for theme in ("light", "dark"):
            browser.load(url, width, theme, False)
            opts = {
                "semantic_control_parity": False,
                "reduced_motion_max_ms": None,
                "typography_scale_px": quality.get("typography_scale_px"),
                "spacing_scale_px": quality.get("spacing_scale_px"),
                "text_expansion_factor": quality.get("text_expansion_factor"),
            }
            if opts["typography_scale_px"] or opts["spacing_scale_px"] or \
                    opts["text_expansion_factor"] is not None:
                result = browser.evaluate(f"{QUALITY_AUDIT}({json.dumps(opts)})")
                for item in result["findings"]:
                    item["config"] = f"{theme} {width}"
                    found.append(item)
                unknown.extend(f"{theme} {width}: {item}" for item in result["unknown"])

        if "reduced_motion_max_ms" in quality:
            browser.load(url, width, "light", False, reduced_motion=True)
            motion_opts = {
                'semantic_control_parity': False,
                'reduced_motion_max_ms': quality['reduced_motion_max_ms'],
                'text_expansion_factor': None,
            }
            result = browser.evaluate(f"{QUALITY_AUDIT}({json.dumps(motion_opts)})")
            for item in result["findings"]:
                item["config"] = f"reduced motion {width}"
                found.append(item)
            unknown.extend(f"reduced motion {width}: {item}" for item in result["unknown"])

    unique, seen = [], set()
    for item in found:
        key = (item["check"], item["where"], item["detail"], item["config"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique, list(dict.fromkeys(unknown))


def capture_page(browser, page, folder):
    folder.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        for forced in (False, True):
            for width in CAPTURE_WIDTHS:
                if forced and width != CHECK_WIDTH:
                    continue
                browser.load(page.resolve().as_uri(), width, theme, forced)
                name = f"{theme}{'-forced' if forced else ''}-{width}.png"
                browser.screenshot(folder / name)


def capture_page_profiles(browser, page, folder, profiles):
    """Capture each unique target width and theme plus a separately labeled reflow view."""
    folder.mkdir(parents=True, exist_ok=True)
    by_width = {}
    for name, width in profiles["profiles"].items():
        by_width.setdefault(width, []).append(name)
    for width, names in by_width.items():
        label = "-".join(names)
        for theme in THEMES:
            browser.load(page.resolve().as_uri(), width, theme, False)
            browser.screenshot(folder / f"profile-{label}-{theme}-{width}.png")
    if CHECK_WIDTH not in by_width:
        browser.load(page.resolve().as_uri(), CHECK_WIDTH, "light", True)
        browser.screenshot(folder / f"high-contrast-forced-{CHECK_WIDTH}.png")
    browser.load(page.resolve().as_uri(), profiles["reflow_width"], "light", False)
    browser.screenshot(folder / f"reflow-zoom-{profiles['reflow_width']}.png")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pages", nargs="+", type=Path)
    parser.add_argument("--expect", type=Path, help="JSON list of strings that must render")
    parser.add_argument("--capture", type=Path, help="write PNG captures per page into this folder")
    parser.add_argument("--forbid", type=Path, help="JSON list of case-insensitive patterns that must not render")
    parser.add_argument("--tasks", type=Path,
                        help="JSON list of {name, clicks: [visible labels], goal, max_clicks, optional start: '#fragment'}")
    parser.add_argument("--rubric", type=Path,
                        help="shared JSON rubric with bounded web target profiles and optional quality checks")
    parser.add_argument("--max-words", type=int, default=0,
                        help="visible-word budget for the first 1280 by 900 viewport; 0 disables it")
    parser.add_argument("--chrome", default=os.environ.get("CHROME", DEFAULT_CHROME))
    args = parser.parse_args(argv)
    try:
        profiles = PROFILES.load_rubric(args.rubric) if args.rubric else None
        expect = json.loads(args.expect.read_text(encoding="utf-8")) if args.expect else []
        forbid = json.loads(args.forbid.read_text(encoding="utf-8")) if args.forbid else []
        tasks = json.loads(args.tasks.read_text(encoding="utf-8")) if args.tasks else []
    except (PROFILES.RubricError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        print(f"render-check: {error}", file=sys.stderr)
        return 2
    for path in args.pages:
        if not path.is_file():
            print(f"render-check: {path}: not a file", file=sys.stderr)
            return 2
    if not Path(args.chrome).exists():
        print(f"render-check: Chrome not found at {args.chrome}; refusing rather than skipping",
              file=sys.stderr)
        return 2
    started = time.monotonic()
    browser = Browser(args.chrome)
    failed = False
    incomplete = False
    try:
        print(f"render-check: {browser.version}")
        if profiles:
            print(f"render-check: rubric sha256 {profiles['digest']}")
            print(f"render-check: target decision: {profiles['decision']}")
            print(f"render-check: target profiles: {profiles['profiles']}")
            print("render-check: 320px is zoom/reflow, not a phone profile")
        for page in args.pages:
            unknown = []
            if profiles:
                problems, unknown = check_page_profiles(
                    browser, page, expect, forbid, args.max_words, profiles)
                for item in unknown:
                    print(f"{page}: quality unknown: {item}")
                incomplete = incomplete or bool(unknown)
            else:
                problems = check_page(browser, page, expect, forbid, args.max_words)
            if tasks:
                task_widths = profiles["widths"] if profiles else [CHECK_WIDTH]
                for width in task_widths:
                    task_problems, counts = run_tasks(browser, page, tasks, width)
                    problems += task_problems
                    for name, clicks, budget in counts:
                        suffix = f" [{width}px]" if profiles else ""
                        print(f"{page}: clicks: {name}: {clicks} (budget {budget}){suffix}")
            for item in problems:
                print(f"{page}: {item['check']}: {item['where']}: {item['detail']} [{item['config']}]")
            status = "FAIL" if problems else "INCOMPLETE" if unknown else "ok"
            print(f"{page}: {status} ({len(problems)} finding(s))")
            failed = failed or bool(problems)
            if args.capture:
                if profiles:
                    capture_page_profiles(browser, page, args.capture / page.parent.name, profiles)
                else:
                    capture_page(browser, page, args.capture / page.parent.name)
    except CdpError as error:
        print(f"render-check: {error}", file=sys.stderr)
        return 2
    finally:
        browser.close()
    print(f"render-check: {time.monotonic() - started:.2f}s")
    return 1 if failed else 3 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main())

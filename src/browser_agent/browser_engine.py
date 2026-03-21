from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Error, Page, TimeoutError, sync_playwright

from browser_agent.dom_snapshot import SnapshotConfig

log = logging.getLogger("browser_agent.browser")


@dataclass(frozen=True)
class BrowserConfig:
    profile_dir: Path
    slowmo_ms: int = 0
    viewport_width: int = 1280
    viewport_height: int = 800


class BrowserEngine:
    def __init__(self, cfg: BrowserConfig):
        self._cfg = cfg
        self._pw = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser page is not initialized yet")
        return self._page

    def start(self) -> None:
        self._cfg.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        chromium = self._pw.chromium
        log.info("Launching persistent Chromium context at %s", self._cfg.profile_dir)
        self._context = chromium.launch_persistent_context(
            user_data_dir=str(self._cfg.profile_dir),
            headless=False,
            slow_mo=self._cfg.slowmo_ms,
            viewport={"width": self._cfg.viewport_width, "height": self._cfg.viewport_height},
        )
        self._context.on("page", self._on_new_page)

        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        self._wire_page(self._page)

    def close(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            self._page = None
            if self._pw is not None:
                self._pw.stop()
                self._pw = None

    def _wire_page(self, page: Page) -> None:
        page.set_default_timeout(10_000)
        page.on("dialog", lambda d: d.dismiss())
        page.on("popup", self._on_popup)

    def _on_new_page(self, page: Page) -> None:
        log.info("New page opened: %s", page.url)
        self._wire_page(page)
        self._page = page

    def _on_popup(self, page: Page) -> None:
        log.info("Popup opened: %s", page.url)
        self._wire_page(page)
        self._page = page

    # ---- Tools ----

    def navigate_to_url(self, url: str) -> dict[str, Any]:
        url = url.strip()
        if not url:
            raise ValueError("url is empty")
        log.info("Navigating to %s", url)
        self.page.goto(url, wait_until="domcontentloaded")
        return {"ok": True, "url": self.page.url, "title": self.page.title()}

    def get_current_page_snapshot(self, cfg: SnapshotConfig) -> dict[str, Any]:
        page = self.page
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except TimeoutError:
            pass

        js = r"""
() => {
  const isVisible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (!style) return false;
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    if (r.bottom < 0 || r.right < 0) return false;
    if (r.top > (window.innerHeight || 0) || r.left > (window.innerWidth || 0)) return false;
    return true;
  };

  const attr = (el, name) => {
    const v = el.getAttribute(name);
    return v == null ? null : String(v);
  };

  const interactiveSelector = [
    'a[href]',
    'button',
    'input',
    'textarea',
    'select',
    '[role="button"]',
    '[role="link"]',
    '[role="textbox"]',
    '[role="searchbox"]',
    '[role="checkbox"]',
    '[role="radio"]',
    '[role="combobox"]',
    '[role="menuitem"]',
    '[contenteditable="true"]',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');

  const els = Array.from(document.querySelectorAll(interactiveSelector))
    .filter(isVisible);

  const normalizedText = (el) => {
    const parts = [];
    const push = (s) => { if (s && String(s).trim()) parts.push(String(s).trim()); };
    push(attr(el, 'aria-label'));
    push(attr(el, 'placeholder'));
    push(attr(el, 'alt'));
    push(el.innerText);
    // Some inputs have value that's meaningful, but never include passwords.
    if (el.tagName === 'INPUT') {
      const t = (attr(el, 'type') || '').toLowerCase();
      if (t !== 'password') push(el.value);
    }
    return parts.join(' | ').replace(/\s+/g, ' ').trim();
  };

  const uniq = new Map();
  for (const el of els) {
    const r = el.getBoundingClientRect();
    const key = [
      el.tagName,
      attr(el, 'role'),
      attr(el, 'name'),
      attr(el, 'id'),
      normalizedText(el).slice(0, 60),
      Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)
    ].join('::');
    if (!uniq.has(key)) uniq.set(key, { el, r });
  }

  const items = [];
  for (const { el, r } of uniq.values()) {
    const tag = el.tagName.toLowerCase();
    const item = {
      tag,
      role: attr(el, 'role'),
      type: tag === 'input' ? attr(el, 'type') : null,
      name: attr(el, 'name'),
      id: attr(el, 'id'),
      href: tag === 'a' ? attr(el, 'href') : null,
      text: normalizedText(el),
      aria_label: attr(el, 'aria-label'),
      placeholder: attr(el, 'placeholder'),
      disabled: !!el.disabled,
      bbox: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
    };
    items.push(item);
  }

  const visibleText = (() => {
    // Keep only a small amount of visible text to help with context.
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const chunks = [];
    let node;
    while ((node = walker.nextNode())) {
      const s = String(node.nodeValue || '').replace(/\s+/g, ' ').trim();
      if (!s) continue;
      const parent = node.parentElement;
      if (!parent || !isVisible(parent)) continue;
      chunks.push(s);
      if (chunks.join('\n').length > 6000) break;
    }
    return chunks.join('\n');
  })();

  return {
    url: String(location.href),
    title: document.title ? String(document.title) : '',
    viewport: { w: window.innerWidth || 0, h: window.innerHeight || 0 },
    interactive: items,
    visible_text: visibleText,
  };
}
"""

        snapshot = page.evaluate(js)
        interactive = snapshot.get("interactive", [])
        # Truncate interactive list deterministically: closest to top-left first.
        interactive.sort(key=lambda it: (it.get("bbox", {}).get("y", 0), it.get("bbox", {}).get("x", 0)))
        snapshot["interactive"] = interactive[: cfg.max_elements]

        if cfg.include_visible_text:
            vt = snapshot.get("visible_text", "")
            snapshot["visible_text"] = vt[: cfg.max_text_chars]
        else:
            snapshot["visible_text"] = ""

        return snapshot

    def _regex(self, description: str) -> re.Pattern[str]:
        # Broad fuzzy matching by case-insensitive regex, escaping user input.
        d = description.strip()
        if not d:
            return re.compile(r"^$")
        return re.compile(re.escape(d), flags=re.IGNORECASE)

    def find_element_and_click(self, description: str) -> dict[str, Any]:
        page = self.page
        rx = self._regex(description)
        candidates = []

        def add(locator, label: str) -> None:
            candidates.append((locator, label))

        add(page.get_by_role("button", name=rx), "role=button")
        add(page.get_by_role("link", name=rx), "role=link")
        add(page.get_by_role("menuitem", name=rx), "role=menuitem")
        add(page.get_by_text(rx, exact=False), "text")
        add(page.get_by_label(rx), "label")

        last_err: str | None = None
        for loc, kind in candidates:
            try:
                loc.first.click(timeout=3_000)
                return {"ok": True, "clicked_via": kind, "url": page.url, "title": page.title()}
            except TimeoutError as e:
                last_err = f"timeout via {kind}: {e}"
            except Error as e:
                last_err = f"error via {kind}: {e}"

        return {"ok": False, "error": last_err or "not_found", "url": page.url}

    def type_text_to_field(self, description: str, text: str) -> dict[str, Any]:
        page = self.page
        rx = self._regex(description)
        candidates = []

        def add(locator, label: str) -> None:
            candidates.append((locator, label))

        add(page.get_by_label(rx), "label")
        add(page.get_by_placeholder(rx), "placeholder")
        add(page.get_by_role("textbox", name=rx), "role=textbox")
        add(page.get_by_role("searchbox", name=rx), "role=searchbox")
        add(page.get_by_text(rx, exact=False), "text-near")

        last_err: str | None = None
        for loc, kind in candidates:
            try:
                target = loc.first
                target.click(timeout=3_000)
                target.fill(text, timeout=3_000)
                return {"ok": True, "typed_via": kind, "url": page.url}
            except TimeoutError as e:
                last_err = f"timeout via {kind}: {e}"
            except Error as e:
                last_err = f"error via {kind}: {e}"

        return {"ok": False, "error": last_err or "not_found", "url": page.url}

    def wait_for_element(self, description: str, timeout_ms: int) -> dict[str, Any]:
        page = self.page
        rx = self._regex(description)
        candidates = [
            (page.get_by_role("button", name=rx), "role=button"),
            (page.get_by_role("link", name=rx), "role=link"),
            (page.get_by_label(rx), "label"),
            (page.get_by_placeholder(rx), "placeholder"),
            (page.get_by_text(rx, exact=False), "text"),
        ]
        last_err: str | None = None
        for loc, kind in candidates:
            try:
                loc.first.wait_for(timeout=timeout_ms)
                return {"ok": True, "found_via": kind, "url": page.url}
            except TimeoutError as e:
                last_err = f"timeout via {kind}: {e}"
        return {"ok": False, "error": last_err or "not_found", "url": page.url}

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
    # If `no_viewport=True`, Playwright won't emulate a fixed viewport and the page layout will
    # match the real window size. This avoids "desktop layout in a tiny window" clipping.
    no_viewport: bool = True
    start_maximized: bool = True
    window_width: int = 1600
    window_height: int = 1000
    # Only used when `no_viewport=False`.
    viewport_width: int = 1280
    viewport_height: int = 800


class BrowserEngine:
    def __init__(self, cfg: BrowserConfig):
        self._cfg = cfg
        self._pw = None
        self._context: BrowserContext | None = None
        self._pages: list[Page] = []
        self._active_index: int = 0

    @property
    def page(self) -> Page:
        if not self._pages:
            raise RuntimeError("Browser page is not initialized yet")
        # Clamp active index
        if self._active_index < 0 or self._active_index >= len(self._pages):
            self._active_index = 0
        return self._pages[self._active_index]

    def list_tabs(self) -> list[dict[str, Any]]:
        tabs: list[dict[str, Any]] = []
        for i, p in enumerate(self._pages):
            try:
                url = p.url
            except Exception:
                url = ""
            try:
                title = p.title()
            except Exception:
                title = ""
            tabs.append({"index": i, "active": i == self._active_index, "url": url, "title": title})
        return tabs

    def switch_to_tab(self, index: int) -> dict[str, Any]:
        if index < 0 or index >= len(self._pages):
            return {"ok": False, "error": f"tab index out of range: {index}", "tabs": self.list_tabs()}
        self._active_index = index
        try:
            self.page.bring_to_front()
        except Exception:
            pass
        return {"ok": True, "active_index": self._active_index, "tabs": self.list_tabs()}

    def open_new_tab(self, url: str | None = None) -> dict[str, Any]:
        if self._context is None:
            raise RuntimeError("Browser context is not initialized")
        p = self._context.new_page()
        self._wire_page(p)
        self._pages.append(p)
        self._active_index = len(self._pages) - 1
        try:
            p.bring_to_front()
        except Exception:
            pass
        if url:
            self.navigate_to_url(url)
        return {"ok": True, "active_index": self._active_index, "tabs": self.list_tabs()}

    def start(self) -> None:
        self._cfg.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        chromium = self._pw.chromium
        log.info("Launching persistent Chromium context at %s", self._cfg.profile_dir)

        launch_args: list[str] = []
        if self._cfg.start_maximized:
            launch_args.append("--start-maximized")
        else:
            launch_args.append(f"--window-size={self._cfg.window_width},{self._cfg.window_height}")

        ctx_kwargs: dict[str, Any] = {
            "user_data_dir": str(self._cfg.profile_dir),
            "headless": False,
            "slow_mo": self._cfg.slowmo_ms,
            "args": launch_args,
            "no_viewport": self._cfg.no_viewport,
        }
        if not self._cfg.no_viewport:
            ctx_kwargs["viewport"] = {
                "width": self._cfg.viewport_width,
                "height": self._cfg.viewport_height,
            }

        self._context = chromium.launch_persistent_context(
            **ctx_kwargs,
        )
        self._context.on("page", self._on_new_page)

        pages = self._context.pages
        if pages:
            for p in pages:
                self._wire_page(p)
            self._pages = list(pages)
        else:
            p = self._context.new_page()
            self._wire_page(p)
            self._pages = [p]
        self._active_index = 0

    def close(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            self._pages = []
            self._active_index = 0
            if self._pw is not None:
                self._pw.stop()
                self._pw = None

    def _wire_page(self, page: Page) -> None:
        page.set_default_timeout(10_000)
        page.on("dialog", lambda d: d.dismiss())
        page.on("popup", self._on_popup)
        page.on("close", lambda: self._on_page_closed(page))

    def _on_page_closed(self, page: Page) -> None:
        try:
            idx = self._pages.index(page)
        except ValueError:
            return
        self._pages.pop(idx)
        if self._active_index >= len(self._pages):
            self._active_index = max(0, len(self._pages) - 1)

    def _on_new_page(self, page: Page) -> None:
        log.info("New page opened: %s", page.url)
        self._wire_page(page)
        # Keep a stable active tab unless user/model explicitly switches.
        if page not in self._pages:
            self._pages.append(page)

    def _on_popup(self, page: Page) -> None:
        log.info("Popup opened: %s", page.url)
        self._wire_page(page)
        if page not in self._pages:
            self._pages.append(page)
        # Popups are usually the user's focus.
        self._active_index = len(self._pages) - 1

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
        snapshot["tabs"] = self.list_tabs()
        snapshot["active_tab_index"] = self._active_index
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

    def _name_regexes(self, description: str) -> list[re.Pattern[str]]:
        """
        Tools receive a free-form `description` from the model. In practice models sometimes
        pass a full sentence instead of a short UI label. We extract a few likely UI strings:
        - quoted segments ("..." / '...' / «...»)
        - id/name/placeholder/aria_label hints embedded in the text
        - keyword fallback (OR of a few meaningful tokens)
        """
        d = (description or "").strip()
        if not d:
            return [re.compile(r"^$")]

        candidates: list[str] = []

        # Quoted segments tend to contain the real button/label text.
        for m in re.finditer(r"['\"“”«»](.{1,80}?)['\"“”«»]", d):
            s = m.group(1).strip()
            if s:
                candidates.append(s)

        # Common hint patterns
        for m in re.finditer(r"\b(id|name|placeholder|aria_label|aria-label)\b[^'\"«»]{0,20}['\"«»](.{1,80}?)['\"»]", d, flags=re.IGNORECASE):
            s = m.group(2).strip()
            if s:
                candidates.append(s)

        # If the description is short already, keep it.
        if len(d) <= 80:
            candidates.append(d)

        # Keyword fallback
        tokens = [t for t in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", d) if len(t) >= 3]
        # drop some stopwords
        stop = {
            "ввожу",
            "ввести",
            "поле",
            "кнопку",
            "нажму",
            "нажать",
            "чтобы",
            "и",
            "или",
            "по",
            "на",
            "в",
            "the",
            "and",
            "click",
            "type",
            "enter",
            "search",
        }
        keywords: list[str] = []
        for t in tokens:
            tl = t.lower()
            if tl in stop:
                continue
            if tl not in (k.lower() for k in keywords):
                keywords.append(t)
            if len(keywords) >= 6:
                break
        if keywords:
            candidates.append("|".join(keywords))

        # Dedup and compile (case-insensitive, search semantics).
        seen: set[str] = set()
        out: list[re.Pattern[str]] = []
        for s in candidates:
            s = s.strip()
            if not s:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            # If it's our keyword OR string, keep it as regex; else escape.
            if "|" in s and " " not in s:
                out.append(re.compile(s, flags=re.IGNORECASE))
            else:
                out.append(re.compile(re.escape(s), flags=re.IGNORECASE))
        return out or [re.compile(re.escape(d), flags=re.IGNORECASE)]

    def find_element_and_click(self, description: str) -> dict[str, Any]:
        page = self.page
        candidates = []

        def add(locator, label: str) -> None:
            candidates.append((locator, label))

        regexes = self._name_regexes(description)
        for rx in regexes:
            add(page.get_by_role("button", name=rx), f"role=button/{rx.pattern}")
            add(page.get_by_role("link", name=rx), f"role=link/{rx.pattern}")
            add(page.get_by_role("menuitem", name=rx), f"role=menuitem/{rx.pattern}")
            add(page.get_by_text(rx, exact=False), f"text/{rx.pattern}")
            add(page.get_by_label(rx), f"label/{rx.pattern}")

        last_err: str | None = None
        for loc, kind in candidates:
            try:
                # Try a few matches and prefer enabled elements (e.g. avoid disabled "Увеличить").
                count = min(loc.count(), 6)
                for i in range(count):
                    el = loc.nth(i)
                    try:
                        if not el.is_visible():
                            continue
                        if not el.is_enabled():
                            continue
                    except Exception:
                        # If we can't query state, still try to click.
                        pass
                    try:
                        el.scroll_into_view_if_needed(timeout=1_500)
                    except Exception:
                        pass
                    el.click(timeout=3_000)
                    return {
                        "ok": True,
                        "clicked_via": kind,
                        "match_index": i,
                        "url": page.url,
                        "title": page.title(),
                    }
            except TimeoutError as e:
                last_err = f"timeout via {kind}: {e}"
            except Error as e:
                last_err = f"error via {kind}: {e}"

        return {"ok": False, "error": last_err or "not_found", "url": page.url}

    def type_text_to_field(self, description: str, text: str, press_enter: bool = False) -> dict[str, Any]:
        page = self.page
        candidates = []

        def add(locator, label: str) -> None:
            candidates.append((locator, label))

        regexes = self._name_regexes(description)
        for rx in regexes:
            add(page.get_by_label(rx), f"label/{rx.pattern}")
            add(page.get_by_placeholder(rx), f"placeholder/{rx.pattern}")
            add(page.get_by_role("searchbox", name=rx), f"role=searchbox/{rx.pattern}")
            add(page.get_by_role("textbox", name=rx), f"role=textbox/{rx.pattern}")
            add(page.get_by_text(rx, exact=False), f"text-near/{rx.pattern}")

        last_err: str | None = None
        for loc, kind in candidates:
            try:
                count = min(loc.count(), 4)
                for i in range(count):
                    target = loc.nth(i)
                    try:
                        if not target.is_visible():
                            continue
                        # is_editable is better than is_enabled for inputs
                        if not target.is_editable():
                            continue
                    except Exception:
                        pass
                    try:
                        target.scroll_into_view_if_needed(timeout=1_500)
                    except Exception:
                        pass
                    # Prefer fill without click; fallback to click then fill.
                    try:
                        target.fill(text, timeout=3_000)
                    except Exception:
                        target.click(timeout=3_000)
                        target.fill(text, timeout=3_000)
                    # Some search boxes only react properly to typing, not fill.
                    if press_enter:
                        try:
                            target.press("Enter", timeout=2_000)
                        except Exception:
                            page.keyboard.press("Enter")
                    return {
                        "ok": True,
                        "typed_via": kind,
                        "match_index": i,
                        "pressed_enter": press_enter,
                        "url": page.url,
                    }
                if press_enter:
                    page.keyboard.press("Enter")
            except TimeoutError as e:
                last_err = f"timeout via {kind}: {e}"
            except Error as e:
                last_err = f"error via {kind}: {e}"

        return {"ok": False, "error": last_err or "not_found", "url": page.url}

    def wait_for_element(self, description: str, timeout_ms: int) -> dict[str, Any]:
        page = self.page
        candidates = []
        regexes = self._name_regexes(description)
        for rx in regexes:
            candidates.extend(
                [
                    (page.get_by_role("button", name=rx), f"role=button/{rx.pattern}"),
                    (page.get_by_role("link", name=rx), f"role=link/{rx.pattern}"),
                    (page.get_by_label(rx), f"label/{rx.pattern}"),
                    (page.get_by_placeholder(rx), f"placeholder/{rx.pattern}"),
                    (page.get_by_text(rx, exact=False), f"text/{rx.pattern}"),
                ]
            )
        last_err: str | None = None
        # Interpret timeout as a total budget across strategies, not per-strategy.
        per_timeout = max(800, int(timeout_ms / max(1, len(candidates))))
        for loc, kind in candidates:
            try:
                loc.first.wait_for(timeout=per_timeout)
                return {"ok": True, "found_via": kind, "url": page.url}
            except TimeoutError as e:
                last_err = f"timeout via {kind}: {e}"
        return {"ok": False, "error": last_err or "not_found", "url": page.url}

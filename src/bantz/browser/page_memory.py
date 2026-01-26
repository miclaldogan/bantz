"""Page Memory: scan DOM and list clickable/interactable elements."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Page, Locator


@dataclass(frozen=True)
class PageElement:
    """A single interactable element."""
    index: int
    tag: str
    role: str  # link, button, input, etc.
    text: str
    selector: str  # unique selector for clicking
    href: Optional[str] = None
    input_type: Optional[str] = None


@dataclass
class PageMemory:
    """Holds the current page's interactable elements."""
    url: str
    title: str
    elements: list[PageElement]

    def summary(self, max_items: int = 25) -> str:
        """Human-readable summary for Bantz to present."""
        lines = [f"Sayfa: {self.title}", f"URL: {self.url}", ""]
        if not self.elements:
            lines.append("Tıklanabilir öğe bulunamadı.")
        else:
            shown = self.elements[:max_items]
            for el in shown:
                text = el.text[:40] + "…" if len(el.text) > 40 else el.text
                if el.role == "input":
                    lines.append(f"  [{el.index}] ({el.input_type or 'input'}) {text or '(boş)'}")
                elif el.role == "link" and el.href:
                    lines.append(f"  [{el.index}] (link) {text} → {el.href[:50]}")
                else:
                    lines.append(f"  [{el.index}] ({el.role}) {text}")
            if len(self.elements) > max_items:
                lines.append(f"  ... ve {len(self.elements) - max_items} öğe daha")
        return "\n".join(lines)

    def find_by_index(self, idx: int) -> Optional[PageElement]:
        for el in self.elements:
            if el.index == idx:
                return el
        return None

    def find_by_text(self, text: str) -> Optional[PageElement]:
        """Fuzzy text match (case-insensitive, contains)."""
        text_lower = text.lower()
        for el in self.elements:
            if text_lower in el.text.lower():
                return el
        return None


def scan_page(page: Page, max_elements: int = 50) -> PageMemory:
    """Extract clickable elements from page DOM."""

    elements: list[PageElement] = []
    idx = 0

    # Helper to add element
    def add(tag: str, role: str, locator: Locator, href: str | None = None, input_type: str | None = None):
        nonlocal idx
        try:
            count = locator.count()
            for i in range(min(count, max_elements - len(elements))):
                if len(elements) >= max_elements:
                    break
                el = locator.nth(i)
                text = ""
                
                # Try multiple sources for text (priority order)
                try:
                    text = (el.inner_text(timeout=300) or "").strip()
                except Exception:
                    pass
                
                # If empty, try aria-label, title, alt, placeholder
                if not text:
                    for attr in ["aria-label", "title", "alt", "placeholder", "value", "name"]:
                        try:
                            val = el.get_attribute(attr)
                            if val and val.strip():
                                text = val.strip()
                                break
                        except Exception:
                            continue
                
                # For images/icons inside, try to get their alt
                if not text:
                    try:
                        img = el.locator("img").first
                        if img.count() > 0:
                            text = img.get_attribute("alt") or ""
                    except Exception:
                        pass
                
                # For SVG icons with sr-only text
                if not text:
                    try:
                        sr = el.locator(".sr-only, .visually-hidden").first
                        if sr.count() > 0:
                            text = sr.inner_text(timeout=200) or ""
                    except Exception:
                        pass

                # Build a unique selector
                try:
                    # Use nth-match for uniqueness
                    selector = f"{tag} >> nth={i}"
                except Exception:
                    selector = f"{tag}:nth-of-type({i+1})"

                # Get href for links
                h = None
                if tag == "a":
                    try:
                        h = el.get_attribute("href")
                    except Exception:
                        pass

                # Get input type
                it = None
                if tag == "input":
                    try:
                        it = el.get_attribute("type") or "text"
                    except Exception:
                        it = "text"

                elements.append(PageElement(
                    index=idx,
                    tag=tag,
                    role=role,
                    text=text[:100],
                    selector=selector,
                    href=h,
                    input_type=it,
                ))
                idx += 1
        except Exception:
            pass

    # Scan different element types
    add("a", "link", page.locator("a[href]"))
    add("button", "button", page.locator("button"))
    add("input", "input", page.locator("input:visible"))
    add("textarea", "input", page.locator("textarea:visible"), input_type="textarea")
    add("[role=button]", "button", page.locator("[role=button]"))
    add("[role=link]", "link", page.locator("[role=link]"))

    return PageMemory(
        url=page.url,
        title=page.title() or "",
        elements=elements,
    )

"""Browser skills for Bantz."""
from __future__ import annotations

from typing import Tuple, Optional

from bantz.browser.controller import get_controller
from bantz.browser.page_memory import scan_page, PageMemory


# Cached page memory
_page_memory: Optional[PageMemory] = None


def browser_navigate(url: str) -> Tuple[bool, str]:
    """Open URL in controlled browser."""
    ctrl = get_controller()
    ok, msg = ctrl.navigate(url)
    if ok:
        global _page_memory
        _page_memory = None  # invalidate cache
    return ok, msg


def browser_scan() -> Tuple[bool, str, Optional[PageMemory]]:
    """Scan current page for interactable elements."""
    global _page_memory
    ctrl = get_controller()
    try:
        _page_memory = scan_page(ctrl.page)
        return True, _page_memory.summary(), _page_memory
    except Exception as e:
        return False, f"Sayfa taranamadı: {e}", None


def browser_click_index(index: int) -> Tuple[bool, str]:
    """Click element by index from last scan."""
    global _page_memory
    if not _page_memory:
        return False, "Tarama yok. Önce 'sayfayı tara' de veya 'tarayayım mı?' diye sor."

    el = _page_memory.find_by_index(index)
    if not el:
        return False, f"[{index}] numaralı öğe bulunamadı. Sayfayı tekrar tara."

    ctrl = get_controller()
    try:
        # Parse selector: "a >> nth=5" -> locator("a").nth(5)
        parts = el.selector.split(" >> ")
        tag_selector = parts[0]
        nth_index = 0
        if len(parts) > 1 and parts[1].startswith("nth="):
            nth_index = int(parts[1].split("=")[1])
        
        locator = ctrl.page.locator(tag_selector).nth(nth_index)
        
        # Scroll into view and click
        locator.scroll_into_view_if_needed(timeout=3000)
        locator.click(timeout=5000)
        _page_memory = None  # page likely changed
        return True, f"[{index}] '{el.text[:30] if el.text else '(ikon)'}' öğesine tıkladım."
    except Exception as e:
        return False, f"Tıklayamadım: {e}"


def browser_click_text(text: str) -> Tuple[bool, str]:
    """Click element by text match."""
    global _page_memory
    if not _page_memory:
        # Auto-scan on text-based click (UX improvement)
        ok, msg, mem = browser_scan()
        if not ok:
            return False, f"Sayfa taranamadı: {msg}"

    el = _page_memory.find_by_text(text)
    if not el:
        # Suggest alternatives
        alternatives = [e.text for e in _page_memory.elements if e.text][:5]
        alt_text = ", ".join(f"'{a[:20]}'" for a in alternatives) if alternatives else "yok"
        return False, f"'{text}' içeren öğe bulunamadı. Benzer öğeler: {alt_text}"

    ctrl = get_controller()
    try:
        # Parse selector: "a >> nth=5" -> locator("a").nth(5)
        parts = el.selector.split(" >> ")
        tag_selector = parts[0]
        nth_index = 0
        if len(parts) > 1 and parts[1].startswith("nth="):
            nth_index = int(parts[1].split("=")[1])
        
        locator = ctrl.page.locator(tag_selector).nth(nth_index)
        locator.scroll_into_view_if_needed(timeout=3000)
        locator.click(timeout=5000)
        _page_memory = None
        return True, f"'{el.text[:30] if el.text else '(öğe)'}' öğesine tıkladım."
    except Exception as e:
        return False, f"Tıklayamadım: {e}"


def browser_type_text(text: str, element_index: Optional[int] = None) -> Tuple[bool, str]:
    """Type text into focused element or specified input."""
    global _page_memory
    ctrl = get_controller()

    if element_index is not None:
        if not _page_memory:
            return False, "Önce 'sayfayı tara' de."
        el = _page_memory.find_by_index(element_index)
        if not el:
            return False, f"[{element_index}] numaralı öğe bulunamadı."
        if el.role != "input":
            return False, f"[{element_index}] bir input değil ({el.role})."
        try:
            locator = ctrl.page.locator(el.selector.split(" >> ")[0]).nth(int(el.selector.split("=")[-1]))
            locator.fill(text, timeout=5000)
            return True, f"[{element_index}] alanına yazdım."
        except Exception as e:
            return False, f"Yazamadım: {e}"

    # Type into currently focused element
    try:
        ctrl.page.keyboard.type(text)
        return True, "Yazdım."
    except Exception as e:
        return False, f"Yazamadım: {e}"


def browser_scroll_down() -> Tuple[bool, str]:
    return get_controller().scroll_down()


def browser_scroll_up() -> Tuple[bool, str]:
    return get_controller().scroll_up()


def browser_go_back() -> Tuple[bool, str]:
    return get_controller().go_back()


def browser_current_info() -> Tuple[bool, str]:
    """Get current page title and URL."""
    ctrl = get_controller()
    try:
        return True, f"Sayfa: {ctrl.current_title()}\nURL: {ctrl.current_url()}"
    except Exception as e:
        return False, f"Bilgi alınamadı: {e}"


def browser_detail(index: int) -> Tuple[bool, str]:
    """Get detailed info about an element from last scan."""
    global _page_memory
    if not _page_memory:
        return False, "Tarama yok. Önce 'sayfayı tara' de."
    
    el = _page_memory.find_by_index(index)
    if not el:
        return False, f"[{index}] numaralı öğe bulunamadı."
    
    lines = [
        f"[{el.index}] Detay:",
        f"  Tip: {el.role} ({el.tag})",
        f"  Metin: {el.text or '(boş)'}",
    ]
    if el.href:
        lines.append(f"  Link: {el.href}")
    if el.input_type:
        lines.append(f"  Input tipi: {el.input_type}")
    lines.append(f"  Selector: {el.selector}")
    
    return True, "\n".join(lines)


def browser_wait(seconds: int) -> Tuple[bool, str]:
    """Wait for specified seconds."""
    import time
    if seconds < 1:
        seconds = 1
    if seconds > 30:
        seconds = 30
    
    ctrl = get_controller()
    try:
        time.sleep(seconds)
        title = ctrl.current_title()
        return True, f"{seconds} saniye bekledim. Sayfa: {title}"
    except Exception as e:
        return False, f"Beklerken hata: {e}"


def get_page_memory() -> Optional[PageMemory]:
    return _page_memory


# ─────────────────────────────────────────────────────────────────
# AI Chat Skills (duck.ai, chatgpt, etc.)
# ─────────────────────────────────────────────────────────────────

# URL mapping for AI services
_AI_SERVICE_URLS = {
    "duck": "https://duck.ai",
    "chatgpt": "https://chat.openai.com",
    "claude": "https://claude.ai",
    "gemini": "https://gemini.google.com",
    "perplexity": "https://perplexity.ai",
}


def browser_ai_chat(service: str, prompt: str) -> Tuple[bool, str]:
    """Navigate to AI chat service and send a prompt.
    
    Uses site profiles for smarter interaction when available.
    
    Args:
        service: AI service name (duck, chatgpt, claude, gemini, perplexity)
        prompt: Text to send to the AI
    
    Returns:
        (success, message)
    """
    global _page_memory
    
    service_lower = service.lower()
    url = _AI_SERVICE_URLS.get(service_lower)
    if not url:
        return False, f"Bilinmeyen AI servisi: {service}. Desteklenen: {', '.join(_AI_SERVICE_URLS.keys())}"
    
    ctrl = get_controller()
    current_url = ctrl.current_url()
    
    # Check if we're already on the target site
    target_domain = url.replace("https://", "").replace("http://", "").split("/")[0]
    already_on_site = target_domain in current_url
    
    try:
        # Try to use site profile for smarter interaction
        from bantz.browser.site_profiles import get_profile_for_url, ProfileActionExecutor
        
        # Navigate if not already on the site
        if not already_on_site:
            ok, msg = ctrl.navigate(url)
            if not ok:
                return False, f"{service} açılamadı: {msg}"
            
            # Wait for page to load
            ctrl.page.wait_for_load_state("domcontentloaded", timeout=15000)
        
        # Try profile-based action first
        profile = get_profile_for_url(url)
        if profile and "send_prompt" in profile.actions:
            executor = ProfileActionExecutor(ctrl.page)
            ok, msg = executor.execute_action(
                profile, 
                "send_prompt", 
                {"prompt": prompt}
            )
            if ok:
                _page_memory = None
                return True, f"✅ {service.capitalize()}'a sordum: \"{prompt[:50]}{'...' if len(prompt) > 50 else ''}\""
            # Fall through to generic method if profile action fails
        
        # Generic fallback: find textarea and type
        input_selectors = ["textarea", "div[contenteditable='true']", "input[type='text']"]
        
        for selector in input_selectors:
            try:
                ctrl.page.wait_for_selector(selector, state="visible", timeout=5000)
                input_el = ctrl.page.locator(selector).first
                input_el.click(timeout=3000)
                
                # Clear existing text
                ctrl.page.keyboard.press("Control+a")
                ctrl.page.keyboard.press("Backspace")
                
                # Type the prompt
                input_el.fill(prompt, timeout=5000)
                
                # Submit
                ctrl.page.keyboard.press("Enter")
                
                _page_memory = None
                return True, f"✅ {service.capitalize()}'a sordum: \"{prompt[:50]}{'...' if len(prompt) > 50 else ''}\""
            except Exception:
                continue
        
        return False, f"{service} sayfası yüklendi ama giriş alanı bulunamadı. Sayfayı kontrol edin."
        
    except Exception as e:
        return False, f"{service} kullanılamadı: {e}"


def browser_profile_action(action_name: str, **variables) -> Tuple[bool, str]:
    """Execute a site profile action on current page.
    
    Args:
        action_name: Name of the action (e.g., "search", "play", "new_chat")
        **variables: Variables to substitute in action (e.g., query="python")
    
    Returns:
        (success, message)
    """
    ctrl = get_controller()
    current_url = ctrl.current_url()
    
    if not current_url:
        return False, "Açık sayfa yok"
    
    from bantz.browser.site_profiles import get_profile_for_url, ProfileActionExecutor
    
    profile = get_profile_for_url(current_url)
    if not profile:
        return False, f"Bu sayfa için profil bulunamadı"
    
    if action_name not in profile.actions:
        available = ", ".join(profile.actions.keys())
        return False, f"'{action_name}' action yok. Mevcut: {available}"
    
    executor = ProfileActionExecutor(ctrl.page)
    return executor.execute_action(profile, action_name, variables)

/**
 * Bantz Browser - Webview Preload Script
 * Runs in the context of web pages loaded in the webview
 * Provides overlay system and page scanning
 */

const { ipcRenderer } = require('electron');

// ============================================
// OVERLAY SYSTEM
// ============================================

window.BantzOverlay = (function() {
  let isActive = false;
  let elementList = [];
  let overlayContainer = null;
  let refreshTimeout = null;
  
  // Risky keywords for visual warning
  const RISKY_KEYWORDS = [
    'gönder', 'paylaş', 'post', 'ödeme', 'öde', 'satın al', 'sil', 'delete',
    'submit', 'pay', 'send', 'share', 'purchase', 'buy', 'remove', 'confirm',
    'onayla', 'kaldır', 'yayınla', 'publish', 'log out', 'sign out', 'çıkış'
  ];
  
  /**
   * Check if element text is risky
   */
  function isRisky(text) {
    if (!text) return false;
    const lower = text.toLowerCase();
    return RISKY_KEYWORDS.some(kw => lower.includes(kw));
  }
  
  /**
   * Create or get overlay container
   */
  function getContainer() {
    if (!overlayContainer || !document.body.contains(overlayContainer)) {
      overlayContainer = document.createElement('div');
      overlayContainer.id = 'bantz-overlay-root';
      overlayContainer.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: 2147483647;
      `;
      document.body.appendChild(overlayContainer);
    }
    return overlayContainer;
  }
  
  /**
   * Scan visible clickable elements
   */
  function scanElements() {
    const selectors = 'a[href], button, input[type="submit"], input[type="button"], input:not([type="hidden"]), textarea, select, [role="button"], [role="link"], [onclick], summary, [tabindex="0"]';
    const elements = document.querySelectorAll(selectors);
    const results = [];
    const viewportHeight = window.innerHeight;
    const viewportWidth = window.innerWidth;
    
    elements.forEach((el) => {
      const rect = el.getBoundingClientRect();
      
      // Skip invisible/hidden elements
      if (rect.width < 5 || rect.height < 5) return;
      const style = window.getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;
      
      // Skip off-screen elements (with some margin)
      if (rect.bottom < -50 || rect.top > viewportHeight + 50) return;
      if (rect.right < -50 || rect.left > viewportWidth + 50) return;
      
      // Get meaningful text
      const text = el.innerText?.trim()?.slice(0, 60) || 
                   el.getAttribute('aria-label') ||
                   el.getAttribute('title') ||
                   el.getAttribute('alt') ||
                   el.getAttribute('placeholder') ||
                   el.value?.slice(0, 60) ||
                   el.tagName.toLowerCase();
      
      results.push({
        id: results.length + 1,
        element: el,
        text: text,
        type: el.tagName.toLowerCase(),
        href: el.href || '',
        rect: {
          top: rect.top,
          left: rect.left,
          bottom: rect.bottom,
          right: rect.right,
          width: rect.width,
          height: rect.height
        },
        isRisky: isRisky(text)
      });
    });
    
    // Limit to first 100 elements for performance
    return results.slice(0, 100);
  }
  
  /**
   * Create label element
   */
  function createLabel(item) {
    const label = document.createElement('div');
    label.className = 'bantz-overlay-label';
    label.dataset.id = item.id;
    
    // Position: top-left of element, slightly offset
    let top = item.rect.top - 2;
    let left = item.rect.left - 2;
    
    // Keep on screen
    if (top < 5) top = item.rect.top + 5;
    if (left < 5) left = item.rect.left + 5;
    
    const bgColor = item.isRisky ? '#ff4757' : '#00d9ff';
    const textColor = item.isRisky ? '#fff' : '#000';
    
    label.style.cssText = `
      position: fixed;
      top: ${top}px;
      left: ${left}px;
      background: ${bgColor};
      color: ${textColor};
      padding: 2px 5px;
      font-size: 11px;
      font-weight: bold;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      border-radius: 4px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.4);
      z-index: 2147483647;
      pointer-events: none;
      line-height: 1.3;
      white-space: nowrap;
      border: 1px solid rgba(0,0,0,0.2);
    `;
    
    label.textContent = item.isRisky ? `⚠${item.id}` : item.id;
    
    return label;
  }
  
  /**
   * Render overlay labels
   */
  function render() {
    const container = getContainer();
    container.innerHTML = '';
    
    elementList.forEach(item => {
      // Only render if in viewport
      if (item.rect.top > -20 && item.rect.top < window.innerHeight + 20) {
        container.appendChild(createLabel(item));
      }
    });
  }
  
  /**
   * Refresh overlay (throttled)
   */
  function refresh() {
    if (refreshTimeout) return;
    
    refreshTimeout = setTimeout(() => {
      elementList = scanElements();
      if (isActive) render();
      refreshTimeout = null;
    }, 100);
  }
  
  /**
   * Force refresh (immediate)
   */
  function forceRefresh() {
    if (refreshTimeout) {
      clearTimeout(refreshTimeout);
      refreshTimeout = null;
    }
    elementList = scanElements();
    if (isActive) render();
    return { active: isActive, count: elementList.length };
  }
  
  /**
   * Toggle overlay on/off
   */
  function toggle(on) {
    if (on === undefined) on = !isActive;
    
    if (on) {
      isActive = true;
      elementList = scanElements();
      render();
      setupListeners();
    } else {
      isActive = false;
      clear();
      removeListeners();
    }
    
    return { active: isActive, count: elementList.length };
  }
  
  /**
   * Clear overlay
   */
  function clear() {
    if (overlayContainer) {
      overlayContainer.innerHTML = '';
    }
  }
  
  /**
   * Get element by overlay ID
   */
  function getElement(id) {
    const item = elementList.find(e => e.id === id);
    return item ? item.element : null;
  }
  
  /**
   * Get element list (for scan results)
   */
  function getElementList() {
    if (elementList.length === 0 || !isActive) {
      elementList = scanElements();
    }
    return elementList.map(e => ({
      id: e.id,
      text: e.text,
      type: e.type,
      href: e.href,
      isRisky: e.isRisky,
      rect: e.rect
    }));
  }
  
  /**
   * Get status
   */
  function getStatus() {
    return {
      active: isActive,
      count: elementList.length
    };
  }
  
  // Event handlers
  let scrollHandler, resizeHandler, mutationObserver;
  
  function setupListeners() {
    scrollHandler = () => refresh();
    resizeHandler = () => refresh();
    
    window.addEventListener('scroll', scrollHandler, { passive: true });
    window.addEventListener('resize', resizeHandler, { passive: true });
    
    // MutationObserver for DOM changes (throttled)
    mutationObserver = new MutationObserver(() => {
      if (isActive) refresh();
    });
    mutationObserver.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: false
    });
  }
  
  function removeListeners() {
    if (scrollHandler) window.removeEventListener('scroll', scrollHandler);
    if (resizeHandler) window.removeEventListener('resize', resizeHandler);
    if (mutationObserver) mutationObserver.disconnect();
    scrollHandler = null;
    resizeHandler = null;
    mutationObserver = null;
  }
  
  // Public API
  return {
    toggle,
    refresh,
    forceRefresh,
    clear,
    getElement,
    getElementList,
    getStatus,
    isActive: () => isActive
  };
})();

// Expose for debugging and direct access
window.__bantz = window.BantzOverlay;

console.log('[Bantz] Overlay system loaded');

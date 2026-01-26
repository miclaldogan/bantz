/**
 * Bantz Firefox Extension - Content Script
 * Handles page scanning, overlay, and element interactions
 */

// State
let overlayEnabled = false;  // Varsayılan gizli - kullanıcı istemediği sürece gösterme
let elements = [];
let overlayContainer = null;
let currentProfile = null;

// Unique ID for this instance
const INSTANCE_ID = Math.random().toString(36).substr(2, 9);

/**
 * Interactable element selectors
 */
const INTERACTABLE_SELECTORS = [
  'a[href]',
  'button',
  'input:not([type="hidden"])',
  'textarea',
  'select',
  '[role="button"]',
  '[role="link"]',
  '[role="menuitem"]',
  '[role="tab"]',
  '[onclick]',
  '[tabindex]:not([tabindex="-1"])',
  'summary',
  'details',
  'video',
  'audio',
].join(', ');

/**
 * Priority selectors for specific sites (videos, main content first)
 */
const SITE_PRIORITY_SELECTORS = {
  'youtube.com': [
    // Video titles in search results and home
    'a#video-title',
    'a#video-title-link', 
    'ytd-rich-item-renderer a#thumbnail',
    'ytd-video-renderer a#thumbnail',
    // Shorts
    'ytd-reel-item-renderer a',
  ],
  'instagram.com': [
    'article a[href*="/p/"]',
    'article a[href*="/reel/"]',
  ],
  'twitter.com': [
    'article a[href*="/status/"]',
  ],
  'x.com': [
    'article a[href*="/status/"]',
  ],
};

/**
 * Get priority elements for current site
 */
function getPriorityElements() {
  const hostname = location.hostname.replace('www.', '');
  const selectors = SITE_PRIORITY_SELECTORS[hostname];
  
  if (!selectors) return [];
  
  const priorityElements = [];
  for (const selector of selectors) {
    try {
      const found = document.querySelectorAll(selector);
      found.forEach(el => {
        if (isVisible(el) && !priorityElements.includes(el)) {
          priorityElements.push(el);
        }
      });
    } catch (e) {
      // Invalid selector, skip
    }
  }
  return priorityElements;
}

/**
 * Scan page for interactable elements
 */
function scanPage() {
  elements = [];
  let index = 1;
  
  // First, add priority elements (videos, main content)
  const priorityEls = getPriorityElements();
  const addedElements = new Set();
  
  priorityEls.forEach((el) => {
    if (!isVisible(el)) return;
    
    const rect = el.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) return;
    
    const info = {
      index: index++,
      tag: el.tagName.toLowerCase(),
      role: getRole(el),
      text: getElementText(el).slice(0, 100),
      href: el.href || null,
      inputType: el.type || null,
      rect: {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
      },
      selector: generateSelector(el),
      element: el,
      priority: true,
    };
    
    elements.push(info);
    addedElements.add(el);
  });
  
  // Then add remaining elements
  const found = document.querySelectorAll(INTERACTABLE_SELECTORS);
  
  found.forEach((el) => {
    // Skip if already added as priority
    if (addedElements.has(el)) return;
    
    // Skip hidden/invisible elements
    if (!isVisible(el)) return;
    
    // Skip tiny elements (icons without text)
    const rect = el.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) return;
    
    // Get element info
    const info = {
      index: index++,
      tag: el.tagName.toLowerCase(),
      role: getRole(el),
      text: getElementText(el).slice(0, 100),
      href: el.href || null,
      inputType: el.type || null,
      rect: {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
      },
      selector: generateSelector(el),
      element: el, // Keep reference for clicking
    };
    
    elements.push(info);
  });
  
  const priorityCount = elements.filter(e => e.priority).length;
  console.log(`[Bantz] Scanned ${elements.length} elements (${priorityCount} priority/videos)`);
  return elements;
}

/**
 * Check if element is visible
 */
function isVisible(el) {
  if (!el) return false;
  
  const style = getComputedStyle(el);
  if (style.display === 'none') return false;
  if (style.visibility === 'hidden') return false;
  if (style.opacity === '0') return false;
  
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return false;
  
  // Check if in viewport (with some margin)
  if (rect.bottom < -100 || rect.top > window.innerHeight + 100) return false;
  if (rect.right < -100 || rect.left > window.innerWidth + 100) return false;
  
  return true;
}

/**
 * Get semantic role of element
 */
function getRole(el) {
  if (el.role) return el.role;
  
  const tag = el.tagName.toLowerCase();
  if (tag === 'a') return 'link';
  if (tag === 'button') return 'button';
  if (tag === 'input') return 'input';
  if (tag === 'textarea') return 'input';
  if (tag === 'select') return 'select';
  if (tag === 'video') return 'video';
  if (tag === 'audio') return 'audio';
  
  return 'element';
}

/**
 * Get readable text from element
 */
function getElementText(el) {
  // Try aria-label first
  if (el.getAttribute('aria-label')) {
    return el.getAttribute('aria-label').trim();
  }
  
  // Try title
  if (el.title) {
    return el.title.trim();
  }
  
  // Try placeholder for inputs
  if (el.placeholder) {
    return el.placeholder.trim();
  }
  
  // Try alt for images
  const img = el.querySelector('img');
  if (img?.alt) {
    return img.alt.trim();
  }
  
  // Try innerText
  const text = el.innerText?.trim();
  if (text) {
    return text.split('\n')[0]; // First line only
  }
  
  // Try value for inputs
  if (el.value) {
    return `(${el.value.slice(0, 20)}...)`;
  }
  
  return '';
}

/**
 * Generate unique selector for element
 */
function generateSelector(el) {
  const tag = el.tagName.toLowerCase();
  
  // Try ID
  if (el.id) {
    return `#${CSS.escape(el.id)}`;
  }
  
  // Try unique class combination
  if (el.className && typeof el.className === 'string') {
    const classes = el.className.split(' ').filter(c => c && !c.includes(':'));
    if (classes.length > 0) {
      const selector = `${tag}.${classes.slice(0, 2).map(CSS.escape).join('.')}`;
      const matches = document.querySelectorAll(selector);
      if (matches.length === 1) {
        return selector;
      }
    }
  }
  
  // Try data attributes
  for (const attr of el.attributes) {
    if (attr.name.startsWith('data-') && attr.value) {
      const selector = `${tag}[${attr.name}="${CSS.escape(attr.value)}"]`;
      const matches = document.querySelectorAll(selector);
      if (matches.length === 1) {
        return selector;
      }
    }
  }
  
  // Fallback: tag + nth-child
  const parent = el.parentElement;
  if (parent) {
    const siblings = Array.from(parent.children).filter(
      (child) => child.tagName === el.tagName
    );
    const index = siblings.indexOf(el);
    if (index >= 0) {
      return `${tag}:nth-of-type(${index + 1})`;
    }
  }
  
  return tag;
}

/**
 * Create overlay with numbered badges
 */
function createOverlay() {
  // Remove existing overlay
  removeOverlay();
  
  if (!overlayEnabled || elements.length === 0) return;
  
  // Create container
  overlayContainer = document.createElement('div');
  overlayContainer.id = 'bantz-overlay-container';
  overlayContainer.setAttribute('data-instance', INSTANCE_ID);
  
  // Create badges for each element
  elements.forEach((info) => {
    if (!info.element || !isVisible(info.element)) return;
    
    const rect = info.element.getBoundingClientRect();
    
    const badge = document.createElement('div');
    badge.className = 'bantz-badge';
    badge.textContent = info.index;
    
    // Position badge at top-left of element
    badge.style.left = `${window.scrollX + rect.left}px`;
    badge.style.top = `${window.scrollY + rect.top - 12}px`;
    
    // Color coding by role
    if (info.role === 'link') {
      badge.classList.add('bantz-badge-link');
    } else if (info.role === 'button') {
      badge.classList.add('bantz-badge-button');
    } else if (info.role === 'input') {
      badge.classList.add('bantz-badge-input');
    }
    
    overlayContainer.appendChild(badge);
  });
  
  document.body.appendChild(overlayContainer);
}

/**
 * Remove overlay
 */
function removeOverlay() {
  if (overlayContainer) {
    overlayContainer.remove();
    overlayContainer = null;
  }
  // Also remove any stale overlays
  document.querySelectorAll('#bantz-overlay-container').forEach(el => el.remove());
}

/**
 * Click element by index
 */
function clickByIndex(index) {
  console.log(`[Bantz] clickByIndex(${index}), elements count: ${elements.length}`);
  
  const info = elements.find(e => e.index === index);
  if (!info || !info.element) {
    console.log(`[Bantz] Element ${index} not found`);
    return { success: false, message: `[${index}] numaralı öğe bulunamadı` };
  }
  
  console.log(`[Bantz] Found element: ${info.text.slice(0, 50)}`);
  
  try {
    // Scroll into view
    info.element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    
    // Wait a bit then click
    setTimeout(() => {
      console.log(`[Bantz] Clicking element ${index}...`);
      info.element.click();
      console.log(`[Bantz] Clicked!`);
    }, 300);
    
    return { 
      success: true, 
      message: `[${index}] '${info.text.slice(0, 30) || '(öğe)'}' tıklandı` 
    };
  } catch (e) {
    console.log(`[Bantz] Click error: ${e.message}`);
    return { success: false, message: `Tıklanamadı: ${e.message}` };
  }
}

/**
 * Click element by text match (fuzzy search)
 * Supports: "lofi girl videosu", "study with me", partial matches
 */
function clickByText(text) {
  console.log(`[Bantz] clickByText("${text}"), elements count: ${elements.length}`);
  
  const textLower = text.toLowerCase()
    .replace(/videosu?n?u?/gi, '')  // "videoyu", "videosunu" kaldır
    .replace(/linkini?/gi, '')       // "linki", "linkini" kaldır
    .replace(/aç$/gi, '')            // sondaki "aç" kaldır
    .replace(/tıkla$/gi, '')         // sondaki "tıkla" kaldır
    .trim();
  
  console.log(`[Bantz] Searching for: "${textLower}"`);
  
  if (!textLower) {
    return { success: false, message: 'Aranacak metin belirtilmedi' };
  }
  
  // Search in elements - try exact match first, then partial
  let info = null;
  
  // 1. Exact match
  info = elements.find(e => 
    e.text.toLowerCase() === textLower
  );
  if (info) console.log(`[Bantz] Found exact match: ${info.text.slice(0, 50)}`);
  
  // 2. Starts with
  if (!info) {
    info = elements.find(e => 
      e.text.toLowerCase().startsWith(textLower)
    );
  }
  
  // 3. Contains (partial match)
  if (!info) {
    const words = textLower.split(/\s+/).filter(w => w.length > 2);
    info = elements.find(e => {
      const elText = e.text.toLowerCase();
      // All significant words must match
      return words.every(word => elText.includes(word));
    });
  }
  
  // 4. Any word match (fallback)
  if (!info) {
    const words = textLower.split(/\s+/).filter(w => w.length > 2);
    info = elements.find(e => {
      const elText = e.text.toLowerCase();
      return words.some(word => elText.includes(word));
    });
  }
  
  if (!info || !info.element) {
    return { success: false, message: `'${text}' içeren öğe bulunamadı` };
  }
  
  return clickByIndex(info.index);
}

/**
 * Type text into element
 */
function typeText(text, index = null) {
  let targetEl = null;
  
  if (index !== null) {
    const info = elements.find(e => e.index === index);
    if (!info || !info.element) {
      return { success: false, message: `[${index}] numaralı öğe bulunamadı` };
    }
    targetEl = info.element;
  } else {
    // Use currently focused element
    targetEl = document.activeElement;
  }
  
  if (!targetEl || !['INPUT', 'TEXTAREA'].includes(targetEl.tagName)) {
    return { success: false, message: 'Yazılabilir alan bulunamadı' };
  }
  
  try {
    targetEl.focus();
    targetEl.value = text;
    targetEl.dispatchEvent(new Event('input', { bubbles: true }));
    return { success: true, message: 'Yazıldı' };
  } catch (e) {
    return { success: false, message: `Yazılamadı: ${e.message}` };
  }
}

/**
 * Scroll page
 */
function scrollPage(direction, amount = 500) {
  const delta = direction === 'down' ? amount : -amount;
  window.scrollBy({ top: delta, behavior: 'smooth' });
  
  const result = { 
    success: true, 
    message: direction === 'down' ? 'Aşağı kaydırıldı' : 'Yukarı kaydırıldı' 
  };
  
  // Send result to background
  browser.runtime.sendMessage({
    type: 'bantz:scroll_result',
    ...result,
  });
  
  return result;
}

/**
 * Apply site profile
 */
function applyProfile(profile) {
  currentProfile = profile;
  console.log('[Bantz] Profile applied:', profile.name);
  
  // Profile-specific initialization
  if (profile.autoScan) {
    setTimeout(() => {
      scanPage();
      createOverlay();
    }, profile.scanDelay || 1000);
  }
}

/**
 * Listen for messages from background script
 */
browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log('[Bantz Content] Received:', message.type);
  
  switch (message.type) {
    case 'bantz:connected':
      console.log('[Bantz] Daemon connected');
      break;
      
    case 'bantz:scan':
      const scanned = scanPage();
      createOverlay();
      
      // Send results back (without DOM references)
      const results = scanned.map(({ element, ...rest }) => rest);
      browser.runtime.sendMessage({
        type: 'bantz:scan_result',
        elements: results,
      });
      
      sendResponse({ success: true, count: results.length });
      break;
      
    case 'bantz:click':
      let result;
      if (message.index !== undefined) {
        result = clickByIndex(message.index);
      } else if (message.text) {
        result = clickByText(message.text);
      } else {
        result = { success: false, message: 'Parametre eksik' };
      }
      
      browser.runtime.sendMessage({
        type: 'bantz:click_result',
        ...result,
      });
      
      sendResponse(result);
      break;
      
    case 'bantz:type':
      const typeResult = typeText(message.text, message.index);
      sendResponse(typeResult);
      break;
      
    case 'bantz:scroll':
      const scrollResult = scrollPage(message.direction, message.amount);
      sendResponse(scrollResult);
      break;
      
    case 'bantz:overlay':
      overlayEnabled = message.enabled;
      if (overlayEnabled) {
        scanPage();
        createOverlay();
      } else {
        removeOverlay();
      }
      sendResponse({ success: true });
      break;
      
    case 'bantz:profile':
      applyProfile(message.profile);
      sendResponse({ success: true });
      break;
  }
  
  return true;
});

/**
 * Update overlay on scroll/resize
 */
let updateTimeout = null;
function scheduleOverlayUpdate() {
  if (updateTimeout) clearTimeout(updateTimeout);
  updateTimeout = setTimeout(() => {
    if (overlayEnabled && elements.length > 0) {
      createOverlay();
    }
  }, 200);
}

window.addEventListener('scroll', scheduleOverlayUpdate, { passive: true });
window.addEventListener('resize', scheduleOverlayUpdate, { passive: true });

/**
 * Watch for SPA navigation (URL changes without page reload)
 */
let lastUrl = location.href;
const urlObserver = new MutationObserver(() => {
  if (location.href !== lastUrl) {
    lastUrl = location.href;
    console.log('[Bantz] SPA navigation detected:', location.href);
    
    // Re-scan after SPA navigation
    setTimeout(() => {
      scanPage();
      createOverlay();
      
      // Send updated scan to background
      const results = elements.map(({ element, ...rest }) => rest);
      browser.runtime.sendMessage({
        type: 'bantz:scan_result',
        elements: results,
        url: location.href,
        title: document.title,
      });
    }, 1500);
  }
});

urlObserver.observe(document, { subtree: true, childList: true });

/**
 * Auto-scan on initial load
 */
if (document.readyState === 'complete') {
  setTimeout(() => {
    scanPage();
    if (overlayEnabled) {
      createOverlay();
    }
    
    // Send initial scan to background
    const results = elements.map(({ element, ...rest }) => rest);
    browser.runtime.sendMessage({
      type: 'bantz:scan_result',
      elements: results,
      url: location.href,
      title: document.title,
    });
  }, 1000);
} else {
  window.addEventListener('load', () => {
    setTimeout(() => {
      scanPage();
      if (overlayEnabled) {
        createOverlay();
      }
      
      // Send initial scan to background
      const results = elements.map(({ element, ...rest }) => rest);
      browser.runtime.sendMessage({
        type: 'bantz:scan_result',
        elements: results,
        url: location.href,
        title: document.title,
      });
    }, 1000);
  });
}

// Initial log
console.log('[Bantz] Content script loaded');

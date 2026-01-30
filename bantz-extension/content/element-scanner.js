/**
 * Bantz Browser Extension v2 - Element Scanner
 * Smart detection of interactable elements with SPA support
 */

class ElementScanner {
  constructor() {
    this.elementCache = new Map();
    this.lastScanTime = 0;
    this.scanDebounceMs = 100;
    this.instanceId = Math.random().toString(36).substr(2, 9);
  }

  // ========================================================================
  // Selector Configuration
  // ========================================================================

  static INTERACTABLE_SELECTORS = [
    'a[href]',
    'button',
    'input:not([type="hidden"])',
    'textarea',
    'select',
    '[role="button"]',
    '[role="link"]',
    '[role="menuitem"]',
    '[role="tab"]',
    '[role="checkbox"]',
    '[role="radio"]',
    '[role="switch"]',
    '[role="slider"]',
    '[role="textbox"]',
    '[onclick]',
    '[tabindex]:not([tabindex="-1"])',
    'summary',
    'details',
    'video',
    'audio',
    '[contenteditable="true"]',
  ].join(', ');

  static SITE_PRIORITY_SELECTORS = {
    'youtube.com': [
      'a#video-title',
      'a#video-title-link',
      'ytd-rich-item-renderer a#thumbnail',
      'ytd-video-renderer a#thumbnail',
      'ytd-reel-item-renderer a',
      'ytd-compact-video-renderer a',
      'button.ytp-play-button',
      'button.ytp-mute-button',
      'button.ytp-fullscreen-button',
    ],
    'instagram.com': [
      'article a[href*="/p/"]',
      'article a[href*="/reel/"]',
      'article button[type="button"]',
    ],
    'twitter.com': [
      'article a[href*="/status/"]',
      'article button[data-testid]',
      'div[data-testid="tweetButtonInline"]',
    ],
    'x.com': [
      'article a[href*="/status/"]',
      'article button[data-testid]',
    ],
    'github.com': [
      'a.Link--primary',
      'button.btn',
      'summary.btn',
      'a[data-hovercard-type]',
    ],
    'reddit.com': [
      'a[data-click-id="body"]',
      'button[aria-label]',
      'shreddit-post a',
    ],
    'linkedin.com': [
      'a.app-aware-link',
      'button.artdeco-button',
      'div.feed-shared-update-v2 a',
    ],
  };

  // ========================================================================
  // Visibility Checks
  // ========================================================================

  /**
   * Check if element is visible in viewport
   */
  isVisible(el) {
    if (!el) return false;

    // Check computed style
    const style = window.getComputedStyle(el);
    if (style.display === 'none' ||
        style.visibility === 'hidden' ||
        style.opacity === '0' ||
        parseFloat(style.opacity) < 0.1) {
      return false;
    }

    // Check dimensions
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) {
      return false;
    }

    // Check if in viewport (with margin)
    const margin = 50;
    const inViewport = (
      rect.top < (window.innerHeight + margin) &&
      rect.bottom > -margin &&
      rect.left < (window.innerWidth + margin) &&
      rect.right > -margin
    );

    return inViewport;
  }

  /**
   * Check if element is likely interactive
   */
  isInteractive(el) {
    // Has click handler
    if (el.onclick) return true;

    // Has href
    if (el.tagName === 'A' && el.href) return true;

    // Is form element
    if (['BUTTON', 'INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) {
      return true;
    }

    // Has interactive role
    const role = el.getAttribute('role');
    if (['button', 'link', 'menuitem', 'tab', 'checkbox', 'radio'].includes(role)) {
      return true;
    }

    // Has tabindex
    const tabindex = el.getAttribute('tabindex');
    if (tabindex && tabindex !== '-1') return true;

    return false;
  }

  // ========================================================================
  // Element Info Extraction
  // ========================================================================

  /**
   * Extract comprehensive info about an element
   */
  extractElementInfo(el, index) {
    const rect = el.getBoundingClientRect();
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role');

    // Build element info
    const info = {
      index: index,
      tag: tag,
      role: role,
      type: this.getElementType(el),
      
      // Position
      rect: {
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        centerX: Math.round(rect.left + rect.width / 2),
        centerY: Math.round(rect.top + rect.height / 2),
      },

      // Text content
      text: this.getElementText(el),
      ariaLabel: el.getAttribute('aria-label'),
      title: el.getAttribute('title'),
      placeholder: el.getAttribute('placeholder'),

      // Attributes
      id: el.id || null,
      className: el.className || null,
      name: el.getAttribute('name'),
      href: el.href || el.getAttribute('href'),
      value: el.value,

      // State
      disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
      checked: el.checked,
      selected: el.selected,

      // Selector for later reference
      selector: this.generateSelector(el),
      
      // XPath as backup
      xpath: this.getXPath(el),
    };

    return info;
  }

  /**
   * Get element type for categorization
   */
  getElementType(el) {
    const tag = el.tagName.toLowerCase();
    const type = el.getAttribute('type');
    const role = el.getAttribute('role');

    if (tag === 'a') return 'link';
    if (tag === 'button' || role === 'button') return 'button';
    if (tag === 'input') {
      if (type === 'submit') return 'submit';
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (type === 'text' || type === 'email' || type === 'password' || type === 'search') {
        return 'input';
      }
      return 'input';
    }
    if (tag === 'textarea') return 'textarea';
    if (tag === 'select') return 'select';
    if (tag === 'video') return 'video';
    if (tag === 'audio') return 'audio';
    if (role === 'menuitem') return 'menuitem';
    if (role === 'tab') return 'tab';

    return 'element';
  }

  /**
   * Get visible text from element
   */
  getElementText(el) {
    // Try aria-label first
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) return ariaLabel.trim().slice(0, 100);

    // Try title
    const title = el.getAttribute('title');
    if (title) return title.trim().slice(0, 100);

    // For inputs, use placeholder or value
    if (['INPUT', 'TEXTAREA'].includes(el.tagName)) {
      return el.placeholder || el.value || '';
    }

    // Get text content
    let text = '';
    if (el.tagName === 'IMG') {
      text = el.alt || '';
    } else {
      // Get direct text, not nested
      text = el.innerText || el.textContent || '';
    }

    return text.trim().slice(0, 100);
  }

  /**
   * Generate a unique CSS selector for element
   */
  generateSelector(el) {
    // Try ID first
    if (el.id) {
      const id = CSS.escape(el.id);
      if (document.querySelectorAll(`#${id}`).length === 1) {
        return `#${id}`;
      }
    }

    // Try unique class combination
    if (el.className && typeof el.className === 'string') {
      const classes = el.className.split(/\s+/).filter(c => c.length > 0).slice(0, 3);
      if (classes.length > 0) {
        const selector = el.tagName.toLowerCase() + '.' + classes.map(c => CSS.escape(c)).join('.');
        const matches = document.querySelectorAll(selector);
        if (matches.length === 1) {
          return selector;
        }
      }
    }

    // Try data attributes
    for (const attr of ['data-testid', 'data-id', 'data-action', 'name']) {
      const value = el.getAttribute(attr);
      if (value) {
        const selector = `${el.tagName.toLowerCase()}[${attr}="${CSS.escape(value)}"]`;
        if (document.querySelectorAll(selector).length === 1) {
          return selector;
        }
      }
    }

    // Fall back to nth-child path
    return this.getNthChildPath(el);
  }

  /**
   * Get nth-child path to element
   */
  getNthChildPath(el) {
    const path = [];
    let current = el;

    while (current && current !== document.body && path.length < 5) {
      const parent = current.parentElement;
      if (!parent) break;

      const siblings = Array.from(parent.children).filter(
        child => child.tagName === current.tagName
      );
      const index = siblings.indexOf(current) + 1;

      if (siblings.length > 1) {
        path.unshift(`${current.tagName.toLowerCase()}:nth-of-type(${index})`);
      } else {
        path.unshift(current.tagName.toLowerCase());
      }

      current = parent;
    }

    return path.join(' > ');
  }

  /**
   * Get XPath for element
   */
  getXPath(el) {
    if (!el) return '';
    if (el === document.body) return '/html/body';

    const parts = [];
    let current = el;

    while (current && current.nodeType === Node.ELEMENT_NODE) {
      let index = 1;
      let sibling = current.previousElementSibling;
      
      while (sibling) {
        if (sibling.tagName === current.tagName) index++;
        sibling = sibling.previousElementSibling;
      }

      const tag = current.tagName.toLowerCase();
      parts.unshift(`${tag}[${index}]`);
      current = current.parentElement;

      if (parts.length > 10) break;
    }

    return '/' + parts.join('/');
  }

  // ========================================================================
  // Scanning
  // ========================================================================

  /**
   * Scan page for all interactable elements
   */
  scan(options = {}) {
    const { maxElements = 100, includeOffscreen = false } = options;

    const startTime = performance.now();
    const elements = [];
    const addedSet = new Set();
    let index = 1;

    // Helper to add element
    const addElement = (el) => {
      if (addedSet.has(el)) return;
      if (!includeOffscreen && !this.isVisible(el)) return;
      if (elements.length >= maxElements) return;

      addedSet.add(el);
      elements.push(this.extractElementInfo(el, index++));
    };

    // First, add priority elements for this site
    const hostname = location.hostname.replace('www.', '');
    const prioritySelectors = ElementScanner.SITE_PRIORITY_SELECTORS[hostname];

    if (prioritySelectors) {
      for (const selector of prioritySelectors) {
        try {
          document.querySelectorAll(selector).forEach(addElement);
        } catch (e) {
          // Invalid selector, skip
        }
      }
    }

    // Then add general interactable elements
    try {
      document.querySelectorAll(ElementScanner.INTERACTABLE_SELECTORS).forEach(addElement);
    } catch (e) {
      console.error('[Bantz] Error scanning elements:', e);
    }

    // Cache results
    this.elementCache.clear();
    elements.forEach(el => {
      this.elementCache.set(el.index, el);
    });
    this.lastScanTime = performance.now() - startTime;

    return {
      elements: elements,
      count: elements.length,
      scanTime: this.lastScanTime,
      url: location.href,
      title: document.title,
    };
  }

  /**
   * Find element by various criteria
   */
  findElement(query) {
    if (!query) return null;

    // By index
    if (typeof query === 'number' || /^\d+$/.test(query)) {
      const cached = this.elementCache.get(parseInt(query));
      if (cached) {
        return document.querySelector(cached.selector) || 
               this.evaluateXPath(cached.xpath);
      }
    }

    // By selector
    if (typeof query === 'string') {
      try {
        return document.querySelector(query);
      } catch (e) {
        // Not a valid selector
      }

      // Try XPath
      if (query.startsWith('/')) {
        return this.evaluateXPath(query);
      }

      // Try text content match
      return this.findByText(query);
    }

    return null;
  }

  /**
   * Find element by text content
   */
  findByText(text, options = {}) {
    const { exact = false, tag = null } = options;
    const searchText = text.toLowerCase();

    const selector = tag || '*';
    const candidates = document.querySelectorAll(selector);

    for (const el of candidates) {
      if (!this.isVisible(el)) continue;
      if (!this.isInteractive(el)) continue;

      const elText = this.getElementText(el).toLowerCase();

      if (exact) {
        if (elText === searchText) return el;
      } else {
        if (elText.includes(searchText)) return el;
      }
    }

    return null;
  }

  /**
   * Evaluate XPath expression
   */
  evaluateXPath(xpath) {
    try {
      const result = document.evaluate(
        xpath,
        document,
        null,
        XPathResult.FIRST_ORDERED_NODE_TYPE,
        null
      );
      return result.singleNodeValue;
    } catch (e) {
      return null;
    }
  }

  // ========================================================================
  // Dynamic Element Detection (SPA Support)
  // ========================================================================

  /**
   * Wait for element to appear
   */
  waitForElement(query, timeout = 5000) {
    return new Promise((resolve) => {
      const startTime = Date.now();

      const check = () => {
        const el = this.findElement(query);
        if (el) {
          resolve(el);
          return;
        }

        if (Date.now() - startTime >= timeout) {
          resolve(null);
          return;
        }

        requestAnimationFrame(check);
      };

      check();
    });
  }

  /**
   * Observe DOM for new elements
   */
  observeDOM(callback, options = {}) {
    const { debounceMs = 100 } = options;
    let timeoutId = null;

    const observer = new MutationObserver((mutations) => {
      if (timeoutId) clearTimeout(timeoutId);
      
      timeoutId = setTimeout(() => {
        // Check if any visible elements were added
        let hasNewElements = false;
        for (const mutation of mutations) {
          if (mutation.addedNodes.length > 0) {
            hasNewElements = true;
            break;
          }
        }

        if (hasNewElements) {
          callback(this.scan());
        }
      }, debounceMs);
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });

    return observer;
  }

  /**
   * Detect React/Vue/Angular components
   */
  detectFramework() {
    const frameworks = [];

    // React
    if (document.querySelector('[data-reactroot]') || 
        document.querySelector('[data-reactid]') ||
        window.__REACT_DEVTOOLS_GLOBAL_HOOK__) {
      frameworks.push('react');
    }

    // Vue
    if (window.__VUE__ || document.querySelector('[data-v-]')) {
      frameworks.push('vue');
    }

    // Angular
    if (window.angular || document.querySelector('[ng-app]') || 
        document.querySelector('[ng-controller]')) {
      frameworks.push('angular');
    }

    // Next.js
    if (window.__NEXT_DATA__) {
      frameworks.push('nextjs');
    }

    // Svelte
    if (document.querySelector('[class*="svelte-"]')) {
      frameworks.push('svelte');
    }

    return frameworks;
  }
}

// Export for use in content.js
if (typeof window !== 'undefined') {
  window.BantzElementScanner = ElementScanner;
}

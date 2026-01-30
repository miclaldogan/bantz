/**
 * Bantz Browser Extension v2 - Main Content Script
 * Coordinates element scanning, form detection, and page extraction
 * Communicates with background service worker via messaging
 */

class BantzContentScript {
  constructor() {
    // Components
    this.elementScanner = new (window.BantzElementScanner || ElementScanner)();
    this.formDetector = new (window.BantzFormDetector || FormDetector)();
    this.pageExtractor = new (window.BantzPageExtractor || PageExtractor)();

    // State
    this.overlayEnabled = false;
    this.overlayContainer = null;
    this.elements = [];
    this.instanceId = Math.random().toString(36).substr(2, 9);
    this.isInitialized = false;

    // DOM Observer
    this.mutationObserver = null;
    this.resizeObserver = null;

    // Initialize
    this.init();
  }

  // ========================================================================
  // Initialization
  // ========================================================================

  init() {
    if (this.isInitialized) return;
    this.isInitialized = true;

    console.log('[Bantz] Content script v2 initializing...', this.instanceId);

    // Set up message listener
    this.setupMessageListener();

    // Set up DOM observers
    this.setupObservers();

    // Notify background we're ready
    this.sendToBackground({ type: 'content_ready', instanceId: this.instanceId });

    console.log('[Bantz] Content script v2 ready');
  }

  // ========================================================================
  // Message Handling
  // ========================================================================

  setupMessageListener() {
    // Listen for messages from background script
    browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
      return this.handleMessage(message, sendResponse);
    });

    // Also handle chrome.runtime for compatibility
    if (typeof chrome !== 'undefined' && chrome.runtime) {
      chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        return this.handleMessage(message, sendResponse);
      });
    }
  }

  handleMessage(message, sendResponse) {
    const { type, ...params } = message;

    console.log('[Bantz] Received message:', type);

    try {
      switch (type) {
        case 'scan':
          const scanResult = this.scan(params);
          sendResponse({ success: true, data: scanResult });
          break;

        case 'click':
          this.click(params).then(result => {
            sendResponse({ success: true, data: result });
          });
          return true; // Async response

        case 'type':
          this.typeText(params).then(result => {
            sendResponse({ success: true, data: result });
          });
          return true;

        case 'scroll':
          const scrollResult = this.scroll(params);
          sendResponse({ success: true, data: scrollResult });
          break;

        case 'detect_forms':
          const forms = this.formDetector.detect();
          sendResponse({ success: true, data: forms });
          break;

        case 'extract_content':
          const content = this.pageExtractor.extract(params);
          sendResponse({ success: true, data: content });
          break;

        case 'extract_videos':
          const videos = this.pageExtractor.extractVideos();
          sendResponse({ success: true, data: videos });
          break;

        case 'extract_article':
          const article = this.pageExtractor.extractArticle();
          sendResponse({ success: true, data: article });
          break;

        case 'get_page_info':
          const pageInfo = this.pageExtractor.getQuickInfo();
          sendResponse({ success: true, data: pageInfo });
          break;

        case 'overlay':
          this.handleOverlay(params);
          sendResponse({ success: true });
          break;

        case 'fill_form':
          this.fillForm(params).then(result => {
            sendResponse({ success: true, data: result });
          });
          return true;

        case 'submit_form':
          this.submitForm(params).then(result => {
            sendResponse({ success: true, data: result });
          });
          return true;

        case 'wait_for_element':
          this.elementScanner.waitForElement(params.selector, params.timeout).then(el => {
            sendResponse({ success: !!el, found: !!el });
          });
          return true;

        case 'get_element':
          const element = this.elementScanner.findElement(params.query);
          sendResponse({ 
            success: true, 
            found: !!element,
            data: element ? this.elementScanner.extractElementInfo(element, 0) : null,
          });
          break;

        case 'ping':
          sendResponse({ success: true, pong: true, instanceId: this.instanceId });
          break;

        default:
          console.warn('[Bantz] Unknown message type:', type);
          sendResponse({ success: false, error: 'Unknown message type' });
      }
    } catch (error) {
      console.error('[Bantz] Error handling message:', error);
      sendResponse({ success: false, error: error.message });
    }

    return false; // Sync response
  }

  sendToBackground(message) {
    try {
      if (typeof browser !== 'undefined') {
        browser.runtime.sendMessage(message);
      } else if (typeof chrome !== 'undefined') {
        chrome.runtime.sendMessage(message);
      }
    } catch (e) {
      console.error('[Bantz] Error sending to background:', e);
    }
  }

  // ========================================================================
  // Core Actions
  // ========================================================================

  /**
   * Scan page for interactable elements
   */
  scan(options = {}) {
    const result = this.elementScanner.scan(options);
    this.elements = result.elements;

    // Update overlay if enabled
    if (this.overlayEnabled) {
      this.updateOverlay();
    }

    return result;
  }

  /**
   * Click an element
   */
  async click(params) {
    const { selector, index, text, options = {} } = params;
    const { retryCount = 3, retryDelay = 500 } = options;

    let element = null;

    // Find element
    if (selector) {
      element = this.elementScanner.findElement(selector);
    } else if (typeof index === 'number') {
      element = this.elementScanner.findElement(index);
    } else if (text) {
      element = this.elementScanner.findByText(text);
    }

    // Retry if not found
    for (let i = 0; i < retryCount && !element; i++) {
      await this.sleep(retryDelay);
      if (selector) element = this.elementScanner.findElement(selector);
      else if (text) element = this.elementScanner.findByText(text);
    }

    if (!element) {
      return { success: false, error: 'Element not found' };
    }

    try {
      // Scroll into view
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
      await this.sleep(300);

      // Focus first
      if (element.focus) element.focus();

      // Click
      element.click();

      // Visual feedback
      this.flashElement(element);

      return { success: true };
    } catch (error) {
      return { success: false, error: error.message };
    }
  }

  /**
   * Type text into an element
   */
  async typeText(params) {
    const { selector, index, text, options = {} } = params;
    const { clear = true, delay = 50, submit = false } = options;

    let element = null;

    // Find element
    if (selector) {
      element = this.elementScanner.findElement(selector);
    } else if (typeof index === 'number') {
      element = this.elementScanner.findElement(index);
    }

    if (!element) {
      return { success: false, error: 'Element not found' };
    }

    try {
      // Focus
      element.focus();
      await this.sleep(100);

      // Clear if needed
      if (clear) {
        element.value = '';
        element.dispatchEvent(new Event('input', { bubbles: true }));
      }

      // Type character by character (more natural)
      for (const char of text) {
        element.value += char;
        element.dispatchEvent(new Event('input', { bubbles: true }));
        await this.sleep(delay);
      }

      // Trigger change
      element.dispatchEvent(new Event('change', { bubbles: true }));

      // Submit if requested
      if (submit) {
        const form = element.closest('form');
        if (form) {
          form.submit();
        } else {
          element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13 }));
        }
      }

      return { success: true };
    } catch (error) {
      return { success: false, error: error.message };
    }
  }

  /**
   * Scroll the page
   */
  scroll(params) {
    const { direction = 'down', amount = 'page', element: targetSelector } = params;

    let scrollAmount;
    if (amount === 'page') {
      scrollAmount = window.innerHeight * 0.8;
    } else if (amount === 'half') {
      scrollAmount = window.innerHeight * 0.5;
    } else if (typeof amount === 'number') {
      scrollAmount = amount;
    } else {
      scrollAmount = 300;
    }

    // Determine target
    let target = window;
    if (targetSelector) {
      const el = this.elementScanner.findElement(targetSelector);
      if (el) target = el;
    }

    // Calculate scroll
    let scrollX = 0;
    let scrollY = 0;

    switch (direction) {
      case 'down':
        scrollY = scrollAmount;
        break;
      case 'up':
        scrollY = -scrollAmount;
        break;
      case 'left':
        scrollX = -scrollAmount;
        break;
      case 'right':
        scrollX = scrollAmount;
        break;
      case 'top':
        if (target === window) {
          window.scrollTo({ top: 0, behavior: 'smooth' });
        } else {
          target.scrollTop = 0;
        }
        return { success: true };
      case 'bottom':
        if (target === window) {
          window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
        } else {
          target.scrollTop = target.scrollHeight;
        }
        return { success: true };
    }

    // Perform scroll
    if (target === window) {
      window.scrollBy({ top: scrollY, left: scrollX, behavior: 'smooth' });
    } else {
      target.scrollBy({ top: scrollY, left: scrollX, behavior: 'smooth' });
    }

    return { success: true, scrolled: { x: scrollX, y: scrollY } };
  }

  /**
   * Fill a form with provided data
   */
  async fillForm(params) {
    const { formIndex = 0, data = {}, autoDetect = true } = params;

    const detection = this.formDetector.detect();
    const form = detection.forms[formIndex];

    if (!form) {
      return { success: false, error: 'Form not found' };
    }

    const results = [];

    // If autoDetect, match data keys to field types
    for (const [key, value] of Object.entries(data)) {
      let field = null;

      // Find matching field
      if (autoDetect) {
        // Try to match by fieldType
        field = form.fields.find(f => f.fieldType === key);
      }

      // Fall back to name/id match
      if (!field) {
        field = form.fields.find(f => f.name === key || f.id === key);
      }

      if (field) {
        try {
          await this.typeText({
            selector: field.selector,
            text: value,
            options: { clear: true, delay: 30 },
          });
          results.push({ field: key, success: true });
        } catch (e) {
          results.push({ field: key, success: false, error: e.message });
        }
      } else {
        results.push({ field: key, success: false, error: 'Field not found' });
      }
    }

    return { success: true, results };
  }

  /**
   * Submit a form
   */
  async submitForm(params) {
    const { formIndex = 0 } = params;

    const detection = this.formDetector.detect();
    const form = detection.forms[formIndex];

    if (!form) {
      return { success: false, error: 'Form not found' };
    }

    if (form.submitButton) {
      await this.click({ selector: form.submitButton.selector });
      return { success: true, method: 'button' };
    }

    // Try to find form element and submit directly
    const formEl = document.querySelectorAll('form')[formIndex];
    if (formEl) {
      formEl.submit();
      return { success: true, method: 'form.submit' };
    }

    return { success: false, error: 'No submit button found' };
  }

  // ========================================================================
  // Overlay System
  // ========================================================================

  handleOverlay(params) {
    const { action, position } = params;

    switch (action) {
      case 'show':
        this.overlayEnabled = true;
        this.updateOverlay();
        break;
      case 'hide':
        this.overlayEnabled = false;
        this.removeOverlay();
        break;
      case 'toggle':
        this.overlayEnabled = !this.overlayEnabled;
        if (this.overlayEnabled) {
          this.updateOverlay();
        } else {
          this.removeOverlay();
        }
        break;
      case 'move':
        if (position) {
          this.moveOverlay(position);
        }
        break;
    }
  }

  updateOverlay() {
    if (!this.overlayEnabled) return;

    // Create container if needed
    if (!this.overlayContainer) {
      this.overlayContainer = document.createElement('div');
      this.overlayContainer.id = 'bantz-overlay-container';
      this.overlayContainer.style.cssText = 'position: fixed; top: 0; left: 0; pointer-events: none; z-index: 2147483647;';
      document.body.appendChild(this.overlayContainer);
    }

    // Clear existing labels
    this.overlayContainer.innerHTML = '';

    // Scan if no elements
    if (this.elements.length === 0) {
      const result = this.scan({ maxElements: 50 });
      this.elements = result.elements;
    }

    // Create labels for visible elements
    this.elements.forEach(el => {
      if (el.rect.y < 0 || el.rect.y > window.innerHeight) return;
      if (el.rect.x < 0 || el.rect.x > window.innerWidth) return;

      const label = document.createElement('div');
      label.className = 'bantz-element-label';
      label.textContent = el.index;
      label.style.cssText = `
        position: fixed;
        left: ${el.rect.x}px;
        top: ${el.rect.y}px;
        background: #ff6b35;
        color: white;
        font-size: 10px;
        font-weight: bold;
        padding: 1px 4px;
        border-radius: 3px;
        font-family: monospace;
        z-index: 2147483647;
        pointer-events: none;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3);
      `;
      this.overlayContainer.appendChild(label);
    });
  }

  removeOverlay() {
    if (this.overlayContainer) {
      this.overlayContainer.remove();
      this.overlayContainer = null;
    }
  }

  moveOverlay(position) {
    // For future: move the main Bantz overlay UI
    console.log('[Bantz] Move overlay to:', position);
  }

  // ========================================================================
  // Observers
  // ========================================================================

  setupObservers() {
    // Mutation observer for DOM changes
    this.mutationObserver = new MutationObserver((mutations) => {
      // Debounce
      if (this._mutationTimeout) clearTimeout(this._mutationTimeout);
      this._mutationTimeout = setTimeout(() => {
        // Notify background of DOM change
        this.sendToBackground({
          type: 'dom_changed',
          url: location.href,
        });

        // Update overlay if visible
        if (this.overlayEnabled) {
          this.elements = [];
          this.updateOverlay();
        }
      }, 300);
    });

    this.mutationObserver.observe(document.body, {
      childList: true,
      subtree: true,
    });

    // Resize observer
    if (typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(() => {
        if (this.overlayEnabled) {
          this.updateOverlay();
        }
      });
      this.resizeObserver.observe(document.body);
    }

    // Scroll listener for overlay update
    window.addEventListener('scroll', () => {
      if (this.overlayEnabled) {
        if (this._scrollTimeout) clearTimeout(this._scrollTimeout);
        this._scrollTimeout = setTimeout(() => {
          this.updateOverlay();
        }, 100);
      }
    }, { passive: true });
  }

  // ========================================================================
  // Utility Methods
  // ========================================================================

  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  flashElement(element) {
    const originalOutline = element.style.outline;
    element.style.outline = '3px solid #ff6b35';
    setTimeout(() => {
      element.style.outline = originalOutline;
    }, 500);
  }
}

// ========================================================================
// Initialize
// ========================================================================

// Wait for other scripts to load
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.bantzContentScript = new BantzContentScript();
  });
} else {
  window.bantzContentScript = new BantzContentScript();
}

// Expose global for debugging
window.Bantz = {
  scan: () => window.bantzContentScript?.scan(),
  detectForms: () => window.bantzContentScript?.formDetector.detect(),
  extractContent: () => window.bantzContentScript?.pageExtractor.extract(),
  click: (q) => window.bantzContentScript?.click({ selector: q }),
  type: (s, t) => window.bantzContentScript?.typeText({ selector: s, text: t }),
};

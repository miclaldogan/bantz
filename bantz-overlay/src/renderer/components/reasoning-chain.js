/**
 * Bantz Overlay — Reasoning Chain Display
 *
 * Shows the assistant's chain-of-thought above the typewriter speech.
 * Muted, smaller text that fades in during thinking and out when speaking.
 *
 * @module reasoning-chain
 */

// ─── Configuration ──────────────────────────────────────────────
const REASONING_CONFIG = {
  tokenDelay: 15,            // ms — faster than speech
  fadeInMs: 200,
  fadeOutMs: 300,
  maxVisibleLines: 2,
  label: '[düşünüyor...]',
};

/**
 * ReasoningChain — muted thinking text display.
 */
class ReasoningChain {
  /**
   * @param {HTMLElement} container - The reasoning chain container (#reasoning-chain)
   */
  constructor(container) {
    this._container = container;
    this._visible = true;  // can be toggled via settings
    this._isActive = false;

    // Create internal elements
    this._labelEl = document.createElement('span');
    this._labelEl.className = 'reasoning-label';
    this._labelEl.textContent = REASONING_CONFIG.label + ' ';

    this._textEl = document.createElement('span');
    this._textEl.className = 'reasoning-text';

    this._container.appendChild(this._labelEl);
    this._container.appendChild(this._textEl);

    // Token queue
    this._tokenQueue = [];
    this._typeTimer = null;
    this._isTyping = false;
    this._fullText = '';

    // Style
    this._applyStyles();

    // Start hidden
    this._container.style.opacity = '0';
    this._container.style.height = '0';
    this._container.style.overflow = 'hidden';

    console.log('[Reasoning] Initialized');
  }

  // ─── Public API ───────────────────────────────────────────────

  /**
   * Begin reasoning display.
   */
  begin() {
    if (!this._visible) return;

    this._clear();
    this._isActive = true;

    // Fade in
    this._container.style.transition = `opacity ${REASONING_CONFIG.fadeInMs}ms ease, height ${REASONING_CONFIG.fadeInMs}ms ease`;
    this._container.style.opacity = '1';
    this._container.style.height = `${REASONING_CONFIG.maxVisibleLines * 1.5}em`;
  }

  /**
   * Add a reasoning token.
   * @param {string} token
   */
  addToken(token) {
    if (!this._visible) return;

    if (!this._isActive) {
      this.begin();
    }

    this._tokenQueue.push(token);
    if (!this._isTyping) {
      this._processQueue();
    }
  }

  /**
   * End reasoning, fade out.
   */
  end() {
    // Flush remaining tokens
    this._flushQueue();

    this._isActive = false;

    // Fade out
    this._container.style.transition = `opacity ${REASONING_CONFIG.fadeOutMs}ms ease, height ${REASONING_CONFIG.fadeOutMs}ms ease`;
    this._container.style.opacity = '0';

    setTimeout(() => {
      this._container.style.height = '0';
    }, REASONING_CONFIG.fadeOutMs);
  }

  /**
   * Toggle visibility (settings control).
   * @param {boolean} visible
   */
  setVisible(visible) {
    this._visible = visible;
    if (!visible && this._isActive) {
      this.end();
    }
  }

  /**
   * Clean up.
   */
  dispose() {
    if (this._typeTimer) clearTimeout(this._typeTimer);
  }

  // ─── Internal ─────────────────────────────────────────────────

  /** @private */
  _clear() {
    if (this._typeTimer) clearTimeout(this._typeTimer);
    this._tokenQueue = [];
    this._isTyping = false;
    this._fullText = '';
    this._textEl.textContent = '';
  }

  /** @private */
  _processQueue() {
    if (this._tokenQueue.length === 0) {
      this._isTyping = false;
      return;
    }

    this._isTyping = true;
    const token = this._tokenQueue.shift();
    this._fullText += token;
    this._textEl.textContent = this._fullText;

    // Scroll to end
    this._container.scrollLeft = this._container.scrollWidth;

    this._typeTimer = setTimeout(() => {
      this._processQueue();
    }, REASONING_CONFIG.tokenDelay);
  }

  /** @private */
  _flushQueue() {
    if (this._typeTimer) clearTimeout(this._typeTimer);
    while (this._tokenQueue.length > 0) {
      this._fullText += this._tokenQueue.shift();
    }
    this._textEl.textContent = this._fullText;
    this._isTyping = false;
  }

  /** @private */
  _applyStyles() {
    this._container.style.cssText += `
      max-height: ${REASONING_CONFIG.maxVisibleLines * 1.5}em;
      white-space: nowrap;
      overflow-x: auto;
      overflow-y: hidden;
    `;
  }
}

// ─── CSS Injection ──────────────────────────────────────────────
(function injectReasoningStyles() {
  if (document.getElementById('reasoning-styles')) return;

  const style = document.createElement('style');
  style.id = 'reasoning-styles';
  style.textContent = `
    #reasoning-chain {
      font-family: 'JetBrains Mono', 'Fira Code', monospace;
      font-size: 11px;
      padding: 2px 12px;
      line-height: 1.5;
    }

    .reasoning-label {
      color: rgba(74, 153, 153, 0.6);
      font-weight: bold;
    }

    .reasoning-text {
      color: rgba(74, 153, 153, 0.4);
    }

    /* Hide scrollbar */
    #reasoning-chain::-webkit-scrollbar {
      height: 2px;
    }

    #reasoning-chain::-webkit-scrollbar-thumb {
      background: rgba(74, 153, 153, 0.2);
    }
  `;
  document.head.appendChild(style);
})();

// Expose globally
window.ReasoningChain = ReasoningChain;

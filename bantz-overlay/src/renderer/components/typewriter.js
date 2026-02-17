/**
 * Bantz Overlay — Typewriter Speech Output
 *
 * Token-by-token daktilo-style text rendering for assistant speech.
 * Text appears character by character with a blinking block cursor.
 *
 * @module typewriter
 */

// ─── Configuration ──────────────────────────────────────────────
const TYPEWRITER_CONFIG = {
  tokenDelay: 30,             // ms between tokens
  cursorBlinkInterval: 500,   // ms on/off cycle
  maxVisibleLines: 4,
  holdCursorMs: 1000,         // cursor holds after speech complete
  dimAfterMs: 3000,           // text dims after speech + hold
  dimOpacity: 0.4,
};

/**
 * TypewriterOutput — daktilo speech renderer.
 */
class TypewriterOutput {
  /**
   * @param {HTMLElement} container - The typewriter output container (#typewriter-output)
   */
  constructor(container) {
    this._container = container;
    this._textEl = container.querySelector('#typewriter-text') || this._createTextEl();
    this._cursorEl = container.querySelector('#typewriter-cursor') || this._createCursorEl();

    // Token queue and state
    this._tokenQueue = [];
    this._isTyping = false;
    this._typeTimer = null;
    this._cursorTimer = null;
    this._holdTimer = null;
    this._dimTimer = null;
    this._cursorVisible = true;
    this._speechActive = false;

    // Current speech content
    this._fullText = '';
    this._displayedIndex = 0;

    // Start cursor blink
    this._startCursorBlink();

    // Apply styles
    this._applyStyles();

    console.log('[Typewriter] Initialized');
  }

  // ─── Public API ───────────────────────────────────────────────

  /**
   * Begin a new utterance (clears previous).
   */
  beginSpeech() {
    this._clear();
    this._speechActive = true;
    this._container.style.opacity = '1';
    this._showCursor();
  }

  /**
   * Add a token to the typewriter queue.
   * @param {string} token - The text token to append
   */
  addToken(token) {
    if (!this._speechActive) {
      this.beginSpeech();
    }

    this._tokenQueue.push(token);

    if (!this._isTyping) {
      this._processQueue();
    }
  }

  /**
   * Signal that speech is complete.
   */
  endSpeech() {
    this._speechActive = false;

    // Flush remaining queue immediately
    this._flushQueue();

    // Hold cursor for a moment, then dim
    this._holdTimer = setTimeout(() => {
      this._dimTimer = setTimeout(() => {
        this._container.style.opacity = String(TYPEWRITER_CONFIG.dimOpacity);
        this._hideCursor();
      }, TYPEWRITER_CONFIG.dimAfterMs - TYPEWRITER_CONFIG.holdCursorMs);
    }, TYPEWRITER_CONFIG.holdCursorMs);
  }

  /**
   * Set the full text at once (for non-streaming mode).
   * @param {string} text
   */
  setText(text) {
    this.beginSpeech();
    this._fullText = text;
    this._textEl.innerHTML = this._formatText(text);
    this._displayedIndex = text.length;
    this._scrollToBottom();
  }

  /**
   * Clear all text.
   */
  clear() {
    this._clear();
  }

  /**
   * Clean up timers.
   */
  dispose() {
    this._stopCursorBlink();
    if (this._typeTimer) clearTimeout(this._typeTimer);
    if (this._holdTimer) clearTimeout(this._holdTimer);
    if (this._dimTimer) clearTimeout(this._dimTimer);
  }

  // ─── Internal ─────────────────────────────────────────────────

  /** @private */
  _clear() {
    if (this._typeTimer) clearTimeout(this._typeTimer);
    if (this._holdTimer) clearTimeout(this._holdTimer);
    if (this._dimTimer) clearTimeout(this._dimTimer);

    this._tokenQueue = [];
    this._isTyping = false;
    this._fullText = '';
    this._displayedIndex = 0;
    this._textEl.innerHTML = '';
    this._container.style.opacity = '1';
    this._showCursor();
  }

  /**
   * Process the token queue one token at a time.
   * @private
   */
  _processQueue() {
    if (this._tokenQueue.length === 0) {
      this._isTyping = false;
      return;
    }

    this._isTyping = true;
    const token = this._tokenQueue.shift();
    this._appendToken(token);

    this._typeTimer = setTimeout(() => {
      this._processQueue();
    }, TYPEWRITER_CONFIG.tokenDelay);
  }

  /**
   * Flush remaining queue immediately.
   * @private
   */
  _flushQueue() {
    if (this._typeTimer) clearTimeout(this._typeTimer);
    while (this._tokenQueue.length > 0) {
      this._appendToken(this._tokenQueue.shift());
    }
    this._isTyping = false;
  }

  /**
   * Append a single token to the display.
   * @private
   */
  _appendToken(token) {
    this._fullText += token;
    this._textEl.innerHTML = this._formatText(this._fullText);
    this._displayedIndex = this._fullText.length;
    this._scrollToBottom();
  }

  /**
   * Format text with basic markdown support.
   * @private
   */
  _formatText(text) {
    let html = this._escapeHtml(text);

    // **bold** → bright white
    html = html.replace(/\*\*(.+?)\*\*/g, '<span class="tw-bold">$1</span>');

    // *italic* → dimmed
    html = html.replace(/\*(.+?)\*/g, '<span class="tw-italic">$1</span>');

    // Paragraph breaks
    html = html.replace(/\n\n/g, '<br><br>');
    html = html.replace(/\n/g, '<br>');

    return html;
  }

  /** @private */
  _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /** @private */
  _scrollToBottom() {
    this._container.scrollTop = this._container.scrollHeight;
  }

  // ─── Cursor ───────────────────────────────────────────────────

  /** @private */
  _startCursorBlink() {
    this._stopCursorBlink();
    this._cursorTimer = setInterval(() => {
      this._cursorVisible = !this._cursorVisible;
      if (this._cursorEl) {
        this._cursorEl.style.opacity = this._cursorVisible ? '1' : '0';
      }
    }, TYPEWRITER_CONFIG.cursorBlinkInterval);
  }

  /** @private */
  _stopCursorBlink() {
    if (this._cursorTimer) {
      clearInterval(this._cursorTimer);
      this._cursorTimer = null;
    }
  }

  /** @private */
  _showCursor() {
    if (this._cursorEl) {
      this._cursorEl.style.display = 'inline';
      this._cursorVisible = true;
      this._cursorEl.style.opacity = '1';
    }
    this._startCursorBlink();
  }

  /** @private */
  _hideCursor() {
    this._stopCursorBlink();
    if (this._cursorEl) {
      this._cursorEl.style.display = 'none';
    }
  }

  // ─── DOM Setup ────────────────────────────────────────────────

  /** @private */
  _createTextEl() {
    const el = document.createElement('span');
    el.id = 'typewriter-text';
    this._container.appendChild(el);
    return el;
  }

  /** @private */
  _createCursorEl() {
    const el = document.createElement('span');
    el.id = 'typewriter-cursor';
    el.className = 'cursor';
    el.textContent = '█';
    this._container.appendChild(el);
    return el;
  }

  /** @private */
  _applyStyles() {
    this._container.style.cssText += `
      max-height: ${TYPEWRITER_CONFIG.maxVisibleLines * 1.6}em;
      overflow-y: auto;
      scroll-behavior: smooth;
      transition: opacity 0.5s ease;
    `;
  }
}

// ─── CSS Injection ──────────────────────────────────────────────
(function injectTypewriterStyles() {
  if (document.getElementById('typewriter-styles')) return;

  const style = document.createElement('style');
  style.id = 'typewriter-styles';
  style.textContent = `
    #typewriter-output {
      font-family: 'JetBrains Mono', 'Fira Code', monospace;
      font-size: 16px;
      color: #ffb300;
      padding: 8px 12px;
      line-height: 1.6;
    }

    #typewriter-text {
      word-wrap: break-word;
      white-space: pre-wrap;
    }

    #typewriter-cursor {
      color: #ffb300;
      font-weight: bold;
      margin-left: 1px;
    }

    .tw-bold {
      color: #ffffff;
      font-weight: bold;
    }

    .tw-italic {
      color: rgba(255, 179, 0, 0.6);
      font-style: italic;
    }

    /* Scrollbar styling for typewriter area */
    #typewriter-output::-webkit-scrollbar {
      width: 3px;
    }

    #typewriter-output::-webkit-scrollbar-thumb {
      background: rgba(255, 179, 0, 0.3);
      border-radius: 2px;
    }
  `;
  document.head.appendChild(style);
})();

// Expose globally
window.TypewriterOutput = TypewriterOutput;

/**
 * Bantz Overlay — Floating Text Input Component
 *
 * A draggable, glassmorphic text input panel that allows users
 * to type commands to the assistant. Supports multi-line input
 * (Shift+Enter) and sends on Enter.
 *
 * Features:
 * - Floating, draggable position anywhere on screen
 * - Glass morphism dark theme matching overlay aesthetics
 * - Hotkey toggle (Ctrl+Space or /)
 * - Multi-line support (Shift+Enter for newline)
 * - Sends typed message to daemon via IPC
 * - Position persists across toggle cycles
 * - Auto-hides after sending
 *
 * @module text-input
 */

'use strict';

// ─── Configuration ──────────────────────────────────────────────
const TEXT_INPUT_CONFIG = {
  width: 420,
  minHeight: 48,
  maxHeight: 200,
  placeholder: 'Bir komut yaz...',
  sendOnEnter: true,
  hotkey: 'Space',         // Ctrl+Space
  hotkeyModifier: 'ctrlKey',
  dismissAfterSend: false, // Keep visible after sending
  animationDuration: 200,  // ms fade in/out
};

/**
 * FloatingTextInput — draggable text input for overlay commands.
 */
class FloatingTextInput {
  constructor() {
    /** @type {HTMLElement|null} */
    this._element = null;
    /** @type {HTMLTextAreaElement|null} */
    this._textarea = null;
    /** @type {boolean} */
    this._visible = false;
    /** @type {boolean} */
    this._dragging = false;
    /** @type {{x: number, y: number}} */
    this._dragOffset = { x: 0, y: 0 };
    /** @type {{x: number, y: number}} */
    this._position = { x: -1, y: -1 }; // -1 = center on first show
    /** @type {Function|null} */
    this._onSend = null;

    this._build();
    this._setupHotkey();
    this._setupDrag();
  }

  // ─── Public API ─────────────────────────────────────────────

  /**
   * Mount the input into the DOM.
   * @param {HTMLElement} parent - Usually document.body or overlay-root
   */
  mount(parent) {
    parent.appendChild(this._element);
  }

  /**
   * Show the text input with animation.
   */
  show() {
    if (this._visible) {
      this._textarea.focus();
      return;
    }
    this._visible = true;
    this._element.style.display = 'flex';

    // Center on first show
    if (this._position.x < 0) {
      this._position.x = Math.round((window.innerWidth - TEXT_INPUT_CONFIG.width) / 2);
      this._position.y = Math.round(window.innerHeight * 0.7);
    }
    this._applyPosition();

    // Enable mouse events while input is visible
    if (window.overlayAPI) window.overlayAPI.enableMouse();

    // Trigger fade-in
    requestAnimationFrame(() => {
      this._element.style.opacity = '1';
      this._element.style.transform = 'translateY(0)';
      this._textarea.focus();
    });

    console.log('[TextInput] Shown');
  }

  /**
   * Hide the text input with animation.
   */
  hide() {
    if (!this._visible) return;
    this._visible = false;

    this._element.style.opacity = '0';
    this._element.style.transform = 'translateY(10px)';

    // Disable mouse after animation
    setTimeout(() => {
      this._element.style.display = 'none';
      if (window.overlayAPI) window.overlayAPI.disableMouse();
    }, TEXT_INPUT_CONFIG.animationDuration);

    console.log('[TextInput] Hidden');
  }

  /**
   * Toggle visibility.
   */
  toggle() {
    if (this._visible) {
      this.hide();
    } else {
      this.show();
    }
  }

  /**
   * Set callback for when user sends a message.
   * @param {(text: string) => void} callback
   */
  onSend(callback) {
    this._onSend = callback;
  }

  /**
   * Get the root element.
   * @returns {HTMLElement}
   */
  get element() {
    return this._element;
  }

  /**
   * Whether the input is currently visible.
   * @returns {boolean}
   */
  get visible() {
    return this._visible;
  }

  // ─── Internal ───────────────────────────────────────────────

  /**
   * Build the DOM structure.
   * @private
   */
  _build() {
    // Container
    this._element = document.createElement('div');
    this._element.className = 'text-input-container';
    this._element.style.cssText = `
      position: fixed;
      width: ${TEXT_INPUT_CONFIG.width}px;
      min-height: ${TEXT_INPUT_CONFIG.minHeight}px;
      display: none;
      flex-direction: row;
      align-items: flex-end;
      gap: 8px;
      padding: 10px 14px;
      background: rgba(10, 12, 16, 0.88);
      backdrop-filter: blur(18px) saturate(1.4);
      -webkit-backdrop-filter: blur(18px) saturate(1.4);
      border: 1px solid rgba(0, 229, 255, 0.15);
      border-radius: 12px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), 0 0 1px rgba(0, 229, 255, 0.1);
      z-index: 9999;
      pointer-events: auto;
      opacity: 0;
      transform: translateY(10px);
      transition: opacity ${TEXT_INPUT_CONFIG.animationDuration}ms ease, 
                  transform ${TEXT_INPUT_CONFIG.animationDuration}ms ease;
      cursor: default;
      font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
    `;

    // Drag handle (left grip)
    const dragHandle = document.createElement('div');
    dragHandle.className = 'text-input-drag';
    dragHandle.style.cssText = `
      width: 12px;
      min-height: 24px;
      cursor: grab;
      display: flex;
      align-items: center;
      justify-content: center;
      color: rgba(0, 229, 255, 0.3);
      font-size: 14px;
      user-select: none;
      flex-shrink: 0;
    `;
    dragHandle.textContent = '⠿';
    this._dragHandle = dragHandle;
    this._element.appendChild(dragHandle);

    // Textarea
    this._textarea = document.createElement('textarea');
    this._textarea.className = 'text-input-field';
    this._textarea.placeholder = TEXT_INPUT_CONFIG.placeholder;
    this._textarea.rows = 1;
    this._textarea.style.cssText = `
      flex: 1;
      background: transparent;
      border: none;
      outline: none;
      color: #e0e0e0;
      font-family: inherit;
      font-size: 14px;
      line-height: 1.5;
      resize: none;
      max-height: ${TEXT_INPUT_CONFIG.maxHeight}px;
      overflow-y: auto;
      scrollbar-width: thin;
      scrollbar-color: rgba(0, 229, 255, 0.2) transparent;
    `;
    this._textarea.style.setProperty('caret-color', '#00e5ff');
    this._element.appendChild(this._textarea);

    // Send button
    const sendBtn = document.createElement('button');
    sendBtn.className = 'text-input-send';
    sendBtn.style.cssText = `
      width: 32px;
      height: 32px;
      border: 1px solid rgba(0, 229, 255, 0.25);
      border-radius: 6px;
      background: rgba(0, 229, 255, 0.08);
      color: #00e5ff;
      font-size: 16px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      transition: background 0.15s, border-color 0.15s;
    `;
    sendBtn.textContent = '↵';
    sendBtn.addEventListener('mouseenter', () => {
      sendBtn.style.background = 'rgba(0, 229, 255, 0.2)';
      sendBtn.style.borderColor = 'rgba(0, 229, 255, 0.5)';
    });
    sendBtn.addEventListener('mouseleave', () => {
      sendBtn.style.background = 'rgba(0, 229, 255, 0.08)';
      sendBtn.style.borderColor = 'rgba(0, 229, 255, 0.25)';
    });
    sendBtn.addEventListener('click', () => this._send());
    this._element.appendChild(sendBtn);

    // Textarea events
    this._textarea.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && TEXT_INPUT_CONFIG.sendOnEnter) {
        e.preventDefault();
        this._send();
      }
      if (e.key === 'Escape') {
        this.hide();
      }
    });

    // Auto-resize textarea
    this._textarea.addEventListener('input', () => {
      this._textarea.style.height = 'auto';
      this._textarea.style.height = Math.min(
        this._textarea.scrollHeight,
        TEXT_INPUT_CONFIG.maxHeight
      ) + 'px';
    });

    // Prevent mouse events from passing through
    this._element.addEventListener('mouseenter', () => {
      if (window.overlayAPI) window.overlayAPI.enableMouse();
    });
    this._element.addEventListener('mouseleave', () => {
      if (!this._visible) {
        if (window.overlayAPI) window.overlayAPI.disableMouse();
      }
    });
  }

  /**
   * Set up global hotkey (Ctrl+Space) to toggle the input.
   * @private
   */
  _setupHotkey() {
    document.addEventListener('keydown', (e) => {
      if (e[TEXT_INPUT_CONFIG.hotkeyModifier] && e.code === TEXT_INPUT_CONFIG.hotkey) {
        e.preventDefault();
        this.toggle();
      }
    });
  }

  /**
   * Set up drag functionality on the grip handle.
   * @private
   */
  _setupDrag() {
    this._dragHandle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      this._dragging = true;
      this._dragHandle.style.cursor = 'grabbing';
      this._dragOffset.x = e.clientX - this._position.x;
      this._dragOffset.y = e.clientY - this._position.y;
    });

    document.addEventListener('mousemove', (e) => {
      if (!this._dragging) return;
      this._position.x = e.clientX - this._dragOffset.x;
      this._position.y = e.clientY - this._dragOffset.y;

      // Clamp to viewport
      this._position.x = Math.max(0, Math.min(
        this._position.x,
        window.innerWidth - TEXT_INPUT_CONFIG.width
      ));
      this._position.y = Math.max(0, Math.min(
        this._position.y,
        window.innerHeight - 60
      ));

      this._applyPosition();
    });

    document.addEventListener('mouseup', () => {
      if (this._dragging) {
        this._dragging = false;
        this._dragHandle.style.cursor = 'grab';
      }
    });
  }

  /**
   * Apply the stored position to the element.
   * @private
   */
  _applyPosition() {
    this._element.style.left = `${this._position.x}px`;
    this._element.style.top = `${this._position.y}px`;
  }

  /**
   * Send the current input text.
   * @private
   */
  _send() {
    const text = this._textarea.value.trim();
    if (!text) return;

    console.log(`[TextInput] Sending: "${text.substring(0, 50)}..."`);

    // Call the send callback
    if (this._onSend) {
      this._onSend(text);
    }

    // Send via IPC to daemon
    if (window.overlayAPI && window.overlayAPI.sendDaemonEvent) {
      window.overlayAPI.sendDaemonEvent({
        type: 'user_text_input',
        payload: { text },
      });
    }

    // Clear input
    this._textarea.value = '';
    this._textarea.style.height = 'auto';

    // Optionally hide after sending
    if (TEXT_INPUT_CONFIG.dismissAfterSend) {
      this.hide();
    }

    // Flash the send button for feedback
    this._flashSendButton();
  }

  /**
   * Brief visual feedback on the send button.
   * @private
   */
  _flashSendButton() {
    const btn = this._element.querySelector('.text-input-send');
    if (!btn) return;
    btn.style.background = 'rgba(0, 229, 255, 0.4)';
    btn.style.color = '#ffffff';
    setTimeout(() => {
      btn.style.background = 'rgba(0, 229, 255, 0.08)';
      btn.style.color = '#00e5ff';
    }, 200);
  }
}

// Export globally
window.FloatingTextInput = FloatingTextInput;

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { FloatingTextInput, TEXT_INPUT_CONFIG };
}

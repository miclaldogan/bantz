/**
 * Bantz Overlay — Terminal Panel Component
 *
 * Reusable terminal-style sub-panel that can be positioned
 * around (and partially outside) the main HUD rectangle.
 *
 * Usage:
 *   const panel = new TerminalPanel({
 *     id: 'news-feed',
 *     title: 'HABER AKIŞI',
 *     slot: 'right',       // left | right | bottom-left | top-float
 *     width: 300,
 *     height: 400,
 *   });
 *   panel.mount(document.getElementById('hud-panel'));
 *   panel.appendLine('[09:30] Tech news headline — TechCrunch');
 *   panel.show();
 *
 * @module terminal-panel
 */

/**
 * Panel slot definitions.
 * Each slot has a CSS positioning strategy relative to its region column.
 *
 * @enum {string}
 */
const PanelSlot = {
  LEFT: 'left',
  RIGHT: 'right',
  BOTTOM_LEFT: 'bottom-left',
  BOTTOM_RIGHT: 'bottom-right',
  TOP_FLOAT: 'top-float',
};

/**
 * Slot → CSS style map.
 * Panels are now placed inside their region column containers (not overflowing HUD).
 */
const SLOT_STYLES = {
  [PanelSlot.LEFT]: {
    animation: 'slide-in-left 0.3s ease-out',
  },
  [PanelSlot.RIGHT]: {
    animation: 'slide-in-right 0.3s ease-out',
  },
  [PanelSlot.BOTTOM_LEFT]: {
    animation: 'slide-in-bottom 0.3s ease-out',
  },
  [PanelSlot.BOTTOM_RIGHT]: {
    animation: 'slide-in-bottom 0.3s ease-out',
  },
  [PanelSlot.TOP_FLOAT]: {
    animation: 'fade-in 0.4s ease-out',
  },
};

/**
 * Create a reusable terminal sub-panel DOM element.
 */
class TerminalPanel {
  /**
   * @param {object} options
   * @param {string} options.id         - Unique panel ID (used as DOM id)
   * @param {string} options.title      - Header title text (e.g. "HABER AKIŞI")
   * @param {string} [options.slot]     - Positioning slot (PanelSlot)
   * @param {number} [options.width]    - Panel width in px (default 280)
   * @param {number} [options.height]   - Panel height in px (default 350)
   * @param {number} [options.maxLines] - Max lines before FIFO (default 50)
   * @param {boolean} [options.autoScroll] - Auto-scroll to bottom (default true)
   */
  constructor(options) {
    this.id = options.id;
    this.title = options.title;
    this.slot = options.slot || PanelSlot.RIGHT;
    this.width = options.width || 280;
    this.height = options.height || 350;
    this.maxLines = options.maxLines || 50;
    this.autoScroll = options.autoScroll !== false;

    /** @type {HTMLElement|null} */
    this._element = null;
    /** @type {HTMLElement|null} */
    this._contentEl = null;
    /** @type {HTMLElement|null} */
    this._parent = null;
    /** @type {boolean} */
    this._visible = false;
    /** @type {boolean} */
    this._hovered = false;
    /** @type {number} */
    this._lineCount = 0;

    this._build();
  }

  // ─── Public API ───────────────────────────────────────────────

  /**
   * Mount the panel into a parent element.
   * @param {HTMLElement} parent - Usually the HUD panel
   */
  mount(parent) {
    this._parent = parent;
    parent.appendChild(this._element);
  }

  /**
   * Remove from DOM.
   */
  unmount() {
    if (this._element && this._element.parentNode) {
      this._element.parentNode.removeChild(this._element);
    }
  }

  /**
   * Show the panel with animation.
   */
  show() {
    if (this._visible) return;
    this._visible = true;
    this._element.style.display = 'flex';

    // Trigger reflow then add animation
    void this._element.offsetHeight;
    const slotStyle = SLOT_STYLES[this.slot] || {};
    if (slotStyle.animation) {
      this._element.style.animation = slotStyle.animation;
    }
  }

  /**
   * Hide the panel with fade-out.
   */
  hide() {
    if (!this._visible) return;
    this._visible = false;

    this._element.style.opacity = '0';
    this._element.style.transform = 'scale(0.95)';
    setTimeout(() => {
      this._element.style.display = 'none';
      this._element.style.opacity = '';
      this._element.style.transform = '';
    }, 250);
  }

  /**
   * Whether the panel is currently visible.
   * @returns {boolean}
   */
  get visible() {
    return this._visible;
  }

  /**
   * Append a text line to the panel content.
   * Respects maxLines with FIFO (oldest removed).
   * @param {string} text - Line text (can contain HTML)
   * @param {string} [className] - Optional CSS class for the line
   */
  appendLine(text, className) {
    const line = document.createElement('div');
    line.className = 'terminal-line' + (className ? ` ${className}` : '');
    line.innerHTML = text;
    this._contentEl.appendChild(line);
    this._lineCount++;

    // FIFO: remove oldest if over max
    while (this._lineCount > this.maxLines) {
      const first = this._contentEl.querySelector('.terminal-line');
      if (first) {
        this._contentEl.removeChild(first);
        this._lineCount--;
      } else {
        break;
      }
    }

    // Auto-scroll
    if (this.autoScroll && !this._hovered) {
      this._contentEl.scrollTop = this._contentEl.scrollHeight;
    }
  }

  /**
   * Set the full content (replaces existing).
   * @param {string} html - HTML content
   */
  setContent(html) {
    this._contentEl.innerHTML = html;
    this._lineCount = this._contentEl.querySelectorAll('.terminal-line').length;
  }

  /**
   * Clear all content.
   */
  clear() {
    this._contentEl.innerHTML = '';
    this._lineCount = 0;
  }

  /**
   * Get the content container element.
   * @returns {HTMLElement}
   */
  get contentElement() {
    return this._contentEl;
  }

  /**
   * Get the root panel element.
   * @returns {HTMLElement}
   */
  get element() {
    return this._element;
  }

  /**
   * Briefly flash the panel border (e.g. when active).
   * @param {string} [color] - CSS color (default: cyan)
   * @param {number} [durationMs] - Flash duration (default: 600)
   */
  flash(color = 'rgba(0, 229, 255, 0.5)', durationMs = 600) {
    const original = this._element.style.borderColor;
    this._element.style.borderColor = color;
    this._element.style.boxShadow = `0 0 12px ${color}`;
    setTimeout(() => {
      this._element.style.borderColor = original || '';
      this._element.style.boxShadow = '';
    }, durationMs);
  }

  // ─── Internal Build ────────────────────────────────────────────

  /**
   * Construct the DOM tree.
   * @private
   */
  _build() {
    // Root element
    this._element = document.createElement('div');
    this._element.id = `terminal-${this.id}`;
    this._element.className = 'terminal-panel';
    this._element.style.width = `${this.width}px`;
    this._element.style.height = `${this.height}px`;
    this._element.style.display = 'none'; // hidden by default
    this._element.style.position = 'relative';  // flow in region column
    this._element.style.flexShrink = '0';

    // Slot animation only (positioning handled by region containers)
    const slotStyle = SLOT_STYLES[this.slot] || {};
    // No positional styles applied — those come from the grid region

    // Header
    const header = document.createElement('div');
    header.className = 'terminal-panel-header';

    const dots = document.createElement('div');
    dots.className = 'dots';
    for (let i = 0; i < 3; i++) {
      const dot = document.createElement('span');
      dot.className = 'dot';
      dots.appendChild(dot);
    }
    header.appendChild(dots);

    const title = document.createElement('span');
    title.className = 'title';
    title.textContent = `> ${this.title}`;
    header.appendChild(title);

    this._element.appendChild(header);

    // Content area
    this._contentEl = document.createElement('div');
    this._contentEl.className = 'terminal-panel-content terminal-content';
    this._element.appendChild(this._contentEl);

    // Mouse interaction: pause auto-scroll on hover
    this._contentEl.addEventListener('mouseenter', () => {
      this._hovered = true;
    });
    this._contentEl.addEventListener('mouseleave', () => {
      this._hovered = false;
    });

    // Interaction zones: enable mouse on panel hover
    this._element.addEventListener('mouseenter', () => {
      if (window.overlayAPI) window.overlayAPI.enableMouse();
    });
    this._element.addEventListener('mouseleave', () => {
      if (window.overlayAPI) window.overlayAPI.disableMouse();
    });
  }
}

// Export for use in renderer
window.TerminalPanel = TerminalPanel;
window.PanelSlot = PanelSlot;
window.SLOT_STYLES = SLOT_STYLES;

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { TerminalPanel, PanelSlot, SLOT_STYLES };
}

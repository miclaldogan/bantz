/**
 * Bantz Overlay — Panel Layout Engine (#1412)
 *
 * Positions terminal sub-panels around the main HUD rectangle
 * with controlled "harmonious overflow" — panels partially extend
 * beyond the overlay edges.
 *
 * Layout slots:
 *   left          — Left edge, 40% overflow left
 *   right         — Right edge, 40% overflow right
 *   bottom-left   — Bottom-left corner, overflow bottom+left
 *   top-float     — Floating above, free-positioned with rotation
 *
 * Features:
 *   - Slot-based anchor positioning with overflow percentages
 *   - Responsive reflow on viewport resize
 *   - Panel z-index management (active panel on top)
 *   - Individual panel visibility toggle
 *   - Min-width collapse: panels auto-hide below threshold
 *
 * @module panel-layout
 */

'use strict';

// ── Layout Constants ──────────────────────────────────────────────
const MIN_VIEWPORT_WIDTH = 800;   // Below this, overflow panels collapse
const REPOSITION_DEBOUNCE = 150;  // ms

/**
 * Slot definition: anchor point + overflow configuration.
 * Positions are computed relative to HUD panel bounding rect.
 *
 * @typedef {object} SlotDef
 * @property {string} anchor      — CSS anchor edge ('left'|'right'|'bottom-left'|'top')
 * @property {number} overflowPct — % of panel that overflows beyond HUD boundary
 * @property {number} baseZIndex  — Default z-index for this slot
 * @property {string} slideAnim   — CSS animation class for entry
 */
const SLOT_DEFINITIONS = {
  left: {
    anchor: 'left',
    overflowPct: 0.75,       // 75% of panel width overflows left
    baseZIndex: 20,
    slideAnim: 'slide-in-left',
    verticalAlign: 0.05,     // 5% from top
  },
  right: {
    anchor: 'right',
    overflowPct: 0.75,       // 75% of panel width overflows right
    baseZIndex: 20,
    slideAnim: 'slide-in-right',
    verticalAlign: 0.05,
  },
  'bottom-left': {
    anchor: 'bottom-left',
    overflowPct: 0.65,       // 65% overflow on both bottom and left
    baseZIndex: 15,
    slideAnim: 'slide-in-bottom',
    verticalAlign: null,     // computed from bottom
  },
  'bottom-right': {
    anchor: 'bottom-right',
    overflowPct: 0.65,       // 65% overflow on both bottom and right
    baseZIndex: 15,
    slideAnim: 'slide-in-bottom',
    verticalAlign: null,
  },
  'top-float': {
    anchor: 'top',
    overflowPct: 0.15,       // 15% above top edge
    baseZIndex: 30,          // floaters on top
    slideAnim: 'fade-in',
    verticalAlign: null,
  },
};

/**
 * Panel Layout Engine — manages panel positioning and lifecycle.
 */
class PanelLayoutEngine {
  /**
   * @param {HTMLElement} hudPanel — The main HUD panel element
   */
  constructor(hudPanel) {
    /** @type {HTMLElement} */
    this._hud = hudPanel;

    /**
     * Registered panels: id → { panel, slot, el, visible, pinned }
     * @type {Map<string, object>}
     */
    this._panels = new Map();

    /** Active panel id (highest z-index) */
    this._activeId = null;

    /** Next z-index counter for bringToFront */
    this._topZ = 50;

    /** Resize observer */
    this._resizeTimer = null;
    this._onResize = this._handleResize.bind(this);
    window.addEventListener('resize', this._onResize);

    console.log('[PanelLayout] Engine initialized');
  }

  // ── Public API ────────────────────────────────────────────────

  /**
   * Register a panel with the layout engine.
   *
   * @param {string}      id    — Unique panel identifier
   * @param {object}      panel — Panel instance (must have .element, .show(), .hide())
   * @param {string}      slot  — Slot name from SLOT_DEFINITIONS
   * @param {object}      [opts]
   * @param {boolean}     [opts.pinned=false] — If true, panel won't auto-hide on collapse
   */
  register(id, panel, slot, opts = {}) {
    if (!SLOT_DEFINITIONS[slot]) {
      console.warn(`[PanelLayout] Unknown slot "${slot}", defaulting to right`);
      slot = 'right';
    }

    const el = panel.element || panel._element;
    if (!el) {
      console.warn(`[PanelLayout] Panel "${id}" has no element`);
      return;
    }

    this._panels.set(id, {
      panel,
      slot,
      el,
      visible: false,
      pinned: !!opts.pinned,
      width: parseInt(el.style.width) || el.offsetWidth || 280,
      height: parseInt(el.style.height) || el.offsetHeight || 350,
    });

    // Apply initial position
    this._positionPanel(id);
    console.log(`[PanelLayout] Registered "${id}" → slot "${slot}"`);
  }

  /**
   * Unregister a panel.
   * @param {string} id
   */
  unregister(id) {
    this._panels.delete(id);
    if (this._activeId === id) this._activeId = null;
  }

  /**
   * Show a panel (positioned in its slot).
   * @param {string} id
   */
  show(id) {
    const entry = this._panels.get(id);
    if (!entry) return;

    entry.visible = true;
    this._positionPanel(id);

    if (entry.panel.show) entry.panel.show();
    this.bringToFront(id);
  }

  /**
   * Hide a panel.
   * @param {string} id
   */
  hide(id) {
    const entry = this._panels.get(id);
    if (!entry) return;

    entry.visible = false;
    if (entry.panel.hide) entry.panel.hide();
  }

  /**
   * Toggle panel visibility.
   * @param {string} id
   * @returns {boolean} New visibility state
   */
  toggle(id) {
    const entry = this._panels.get(id);
    if (!entry) return false;

    if (entry.visible) {
      this.hide(id);
    } else {
      this.show(id);
    }
    return entry.visible;
  }

  /**
   * Bring a panel to the front (highest z-index).
   * @param {string} id
   */
  bringToFront(id) {
    const entry = this._panels.get(id);
    if (!entry) return;

    this._topZ++;
    entry.el.style.zIndex = String(this._topZ);
    this._activeId = id;
  }

  /**
   * Reposition all visible panels (e.g. after resize).
   */
  repositionAll() {
    for (const [id, entry] of this._panels) {
      if (entry.visible) {
        this._positionPanel(id);
      }
    }
  }

  /**
   * Get all registered panel IDs.
   * @returns {string[]}
   */
  getPanelIds() {
    return Array.from(this._panels.keys());
  }

  /**
   * Get panel info.
   * @param {string} id
   * @returns {object|null}
   */
  getPanel(id) {
    const entry = this._panels.get(id);
    if (!entry) return null;
    return {
      id,
      slot: entry.slot,
      visible: entry.visible,
      pinned: entry.pinned,
    };
  }

  /**
   * Cleanup.
   */
  destroy() {
    window.removeEventListener('resize', this._onResize);
    clearTimeout(this._resizeTimer);
    this._panels.clear();
  }

  // ── Internal ──────────────────────────────────────────────────

  /**
   * Compute and apply CSS position for a panel based on its slot.
   * @param {string} id
   * @private
   */
  _positionPanel(id) {
    const entry = this._panels.get(id);
    if (!entry) return;

    const slotDef = SLOT_DEFINITIONS[entry.slot];
    if (!slotDef) return;

    const hudRect = this._hud.getBoundingClientRect();
    const el = entry.el;
    const pw = entry.width;
    const ph = entry.height;
    const overflow = slotDef.overflowPct;

    // Reset positioning
    el.style.position = 'absolute';

    switch (slotDef.anchor) {
      case 'left': {
        // Panel on left edge, overflowing left
        const overflowPx = Math.round(pw * overflow);
        el.style.left = `${-overflowPx}px`;
        el.style.right = '';
        el.style.top = `${Math.round(hudRect.height * (slotDef.verticalAlign || 0.1))}px`;
        el.style.bottom = '';
        break;
      }

      case 'right': {
        // Panel on right edge, overflowing right
        const overflowPx = Math.round(pw * overflow);
        el.style.right = `${-overflowPx}px`;
        el.style.left = '';
        el.style.top = `${Math.round(hudRect.height * (slotDef.verticalAlign || 0.1))}px`;
        el.style.bottom = '';
        break;
      }

      case 'bottom-left': {
        // Panel at bottom-left corner, overflowing both
        const overflowX = Math.round(pw * overflow);
        const overflowY = Math.round(ph * overflow);
        el.style.left = `${-overflowX}px`;
        el.style.right = '';
        el.style.top = '';
        el.style.bottom = `${-overflowY}px`;
        break;
      }

      case 'bottom-right': {
        // Panel at bottom-right corner, overflowing both
        const overflowX = Math.round(pw * overflow);
        const overflowY = Math.round(ph * overflow);
        el.style.right = `${-overflowX}px`;
        el.style.left = '';
        el.style.top = '';
        el.style.bottom = `${-overflowY}px`;
        break;
      }

      case 'top': {
        // Floating above, right-aligned with slight offset
        const overflowY = Math.round(ph * overflow);
        el.style.top = `${-overflowY}px`;
        el.style.bottom = '';
        el.style.right = '15%';
        el.style.left = '';
        break;
      }

      default:
        break;
    }

    // Set base z-index if not explicitly brought to front
    if (!el.style.zIndex || parseInt(el.style.zIndex) < slotDef.baseZIndex) {
      el.style.zIndex = String(slotDef.baseZIndex);
    }
  }

  /**
   * Handle viewport resize with debounce.
   * @private
   */
  _handleResize() {
    clearTimeout(this._resizeTimer);
    this._resizeTimer = setTimeout(() => {
      const vw = window.innerWidth;

      // Collapse non-pinned panels below min viewport width
      if (vw < MIN_VIEWPORT_WIDTH) {
        for (const [id, entry] of this._panels) {
          if (entry.visible && !entry.pinned) {
            this.hide(id);
          }
        }
      }

      // Reposition all visible panels
      this.repositionAll();
    }, REPOSITION_DEBOUNCE);
  }
}

// ── Expose globally ───────────────────────────────────────────────
window.PanelLayoutEngine = PanelLayoutEngine;
window.SLOT_DEFINITIONS = SLOT_DEFINITIONS;

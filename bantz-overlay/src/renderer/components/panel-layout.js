/**
 * Bantz Overlay — Panel Layout Engine (#1412, #1450)
 *
 * Positions terminal sub-panels in a full-screen 3-column grid layout.
 * Panels are placed into their respective region containers
 * (left, center, right) as flow elements, not overflowing HUD edges.
 *
 * Layout regions:
 *   #region-left    — Left column (300px), vertical stack
 *   #region-center  — Center column (flexible), HUD panel
 *   #region-right   — Right column (340px), vertical stack
 *
 * Slot → Region mapping:
 *   left, bottom-left   → #region-left
 *   right, bottom-right → #region-right
 *   top-float           → #region-center (absolute positioned)
 *
 * Features:
 *   - Region-based placement (panels flow inside their column)
 *   - Panel z-index management (active panel on top)
 *   - Individual panel visibility toggle
 *   - Min-width collapse: panels auto-hide below threshold
 *   - Responsive reflow on viewport resize
 *
 * @module panel-layout
 */

'use strict';

// ── Layout Constants ──────────────────────────────────────────────
const MIN_VIEWPORT_WIDTH = 800;   // Below this, side panels collapse
const REPOSITION_DEBOUNCE = 150;  // ms

/**
 * Slot definition: region target + styling config.
 *
 * @typedef {object} SlotDef
 * @property {string}  region     — Target region element ID
 * @property {number}  baseZIndex — Default z-index for this slot
 * @property {string}  slideAnim  — CSS animation class for entry
 * @property {boolean} absolute   — If true, use absolute positioning inside region
 */
const SLOT_DEFINITIONS = {
  left: {
    region: 'region-left',
    baseZIndex: 20,
    slideAnim: 'slide-in-left',
    absolute: false,
  },
  right: {
    region: 'region-right',
    baseZIndex: 20,
    slideAnim: 'slide-in-right',
    absolute: false,
  },
  'bottom-left': {
    region: 'region-left',
    baseZIndex: 15,
    slideAnim: 'slide-in-bottom',
    absolute: false,
  },
  'bottom-right': {
    region: 'region-right',
    baseZIndex: 15,
    slideAnim: 'slide-in-bottom',
    absolute: false,
  },
  'top-float': {
    region: 'region-center',
    baseZIndex: 30,
    slideAnim: 'fade-in',
    absolute: true,   // floats above center content
  },
};

/**
 * Panel Layout Engine — manages panel placement in grid regions.
 */
class PanelLayoutEngine {
  /**
   * @param {HTMLElement} hudPanel — The main HUD panel element
   */
  constructor(hudPanel) {
    /** @type {HTMLElement} */
    this._hud = hudPanel;

    /** @type {Map<string, HTMLElement>} Region elements cache */
    this._regions = new Map();
    for (const id of ['region-left', 'region-center', 'region-right']) {
      const el = document.getElementById(id);
      if (el) this._regions.set(id, el);
    }

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

    const slotDef = SLOT_DEFINITIONS[slot];
    const regionEl = this._regions.get(slotDef.region);

    // Move panel to its region container (instead of staying in hud-panel)
    if (regionEl && el.parentNode !== regionEl) {
      if (el.parentNode) el.parentNode.removeChild(el);
      regionEl.appendChild(el);
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
    console.log(`[PanelLayout] Registered "${id}" → slot "${slot}" → region "${slotDef.region}"`);
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

    const el = entry.el;

    if (slotDef.absolute) {
      // Absolute-positioned panels (top-float) inside their region
      el.style.position = 'absolute';
      el.style.top = '20px';
      el.style.right = '15%';
    } else {
      // Flow-positioned panels stack in their region column
      el.style.position = 'relative';
      el.style.width = '100%'; // Fill region width
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

      // Hide/show region columns based on viewport width
      const leftRegion = this._regions.get('region-left');
      const rightRegion = this._regions.get('region-right');
      if (leftRegion) leftRegion.style.display = vw < MIN_VIEWPORT_WIDTH ? 'none' : '';
      if (rightRegion) rightRegion.style.display = vw < MIN_VIEWPORT_WIDTH ? 'none' : '';

      // Reposition all visible panels
      this.repositionAll();
    }, REPOSITION_DEBOUNCE);
  }
}

// ── Expose globally ───────────────────────────────────────────────
window.PanelLayoutEngine = PanelLayoutEngine;
window.SLOT_DEFINITIONS = SLOT_DEFINITIONS;

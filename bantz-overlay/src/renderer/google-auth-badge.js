/**
 * Bantz Overlay — Google Auth HUD Badge (Issue #1468)
 *
 * A compact HUD badge showing whether Google account is connected.
 *
 * Connected state:  ● Gmail • Takvim • Classroom   (green dot)
 * Disconnected:     ● Google bağlan                (red dot, clickable)
 *
 * The badge:
 *  - Mounts itself into any parent element
 *  - Subscribes to `auth:status` IPC updates via `window.overlayAPI.onAuthStatus`
 *  - Checks initial state within 5 s of construction via `window.overlayAPI.getAuthStatus`
 *  - Triggers `window.overlayAPI.requestGoogleOAuth()` when user clicks the
 *    disconnected badge (AC: tıklayınca OAuth flow tetiklenir)
 *  - Exposes `applyStatus(status)` for direct / test-driven updates
 *
 * Usage:
 *   const badge = new GoogleAuthBadge();
 *   badge.mount(document.getElementById('hud-panel'));
 *
 * Run tests: node bantz-overlay/tests/test_google_auth_badge.js
 */

'use strict';

// How long to wait before first auto-check (ms).  Kept as a constant so
// tests can override it without touching production code.
const INITIAL_CHECK_DELAY_MS = 5000;

class GoogleAuthBadge {
  /**
   * @param {object} [opts]
   * @param {number} [opts.initialCheckDelay] - ms before first getAuthStatus call (default 5000)
   */
  constructor(opts = {}) {
    this._delay    = (opts.initialCheckDelay != null) ? opts.initialCheckDelay : INITIAL_CHECK_DELAY_MS;
    this._root     = null;
    this._dot      = null;
    this._label    = null;
    this._pending  = false;   // OAuth flow in progress
    this._connected = false;
    this._timer    = null;
  }

  /**
   * Inject badge DOM into `parent`.  Idempotent.
   * @param {HTMLElement} parent
   */
  mount(parent) {
    if (this._root) return;

    // ── Wrapper ──
    const root = document.createElement('div');
    root.className = 'google-auth-badge';
    root.setAttribute('role', 'status');
    root.setAttribute('aria-live', 'polite');

    // ── Dot ──
    const dot = document.createElement('span');
    dot.className = 'google-auth-badge__dot google-auth-badge__dot--disconnected';
    dot.setAttribute('aria-hidden', 'true');
    this._dot = dot;

    // ── Label ──
    const label = document.createElement('button');
    label.className = 'google-auth-badge__label';
    label.setAttribute('type', 'button');
    label.textContent = 'Google bağlan';
    this._label = label;

    root.appendChild(dot);
    root.appendChild(label);
    parent.appendChild(root);
    this._root = root;

    // ── Wire click ──
    label.addEventListener('click', () => this._onClick());

    // ── Subscribe to live updates ──
    const api = this._api();
    if (api && typeof api.onAuthStatus === 'function') {
      api.onAuthStatus((status) => this.applyStatus(status));
    }

    // ── Initial check within _delay ms ──
    this._timer = setTimeout(() => {
      this._timer = null;
      const a = this._api();
      if (a && typeof a.getAuthStatus === 'function') {
        Promise.resolve(a.getAuthStatus())
          .then((s) => { if (s) this.applyStatus(s); })
          .catch(() => {});
      }
    }, this._delay);
  }

  /**
   * Update badge to reflect the given auth status.
   * Safe to call before mount (no-op if not yet mounted) or from tests.
   *
   * @param {{ google: boolean, github?: boolean, needsSetup?: boolean,
   *           calendar?: boolean, gmail?: boolean, classroom?: boolean }} status
   */
  applyStatus(status) {
    if (!status) return;

    const connected = !!(status.google);
    this._connected = connected;

    if (!this._root) return;  // not yet mounted

    const dot   = this._dot;
    const label = this._label;

    if (connected) {
      dot.className = 'google-auth-badge__dot google-auth-badge__dot--connected';
      // Build service list from per-scope flags (fall back to assuming all active)
      const services = [];
      if (status.gmail     !== false) services.push('Gmail');
      if (status.calendar  !== false) services.push('Takvim');
      if (status.classroom !== false) services.push('Classroom');
      label.textContent = services.length ? services.join(' • ') : 'Google bağlı';
      label.setAttribute('title', 'Google hesabı bağlı — tıkla izinleri yönet');
      label.classList.add('google-auth-badge__label--connected');
      label.classList.remove('google-auth-badge__label--disconnected');
    } else {
      dot.className = 'google-auth-badge__dot google-auth-badge__dot--disconnected';
      label.textContent = 'Google bağlan';
      label.setAttribute('title', 'Google hesabı bağlı değil — tıkla bağlan');
      label.classList.add('google-auth-badge__label--disconnected');
      label.classList.remove('google-auth-badge__label--connected');
    }
  }

  /** Whether the badge currently shows connected state. */
  get connected() { return this._connected; }

  // ── Private ────────────────────────────────────────────────

  /**
   * Handle user click:
   * - If disconnected → trigger OAuth flow with all core scopes
   * - If connected    → trigger OAuth to manage / re-authorise scopes
   * @private
   */
  async _onClick() {
    if (this._pending) return;

    const api = this._api();
    if (!api || typeof api.requestGoogleOAuth !== 'function') return;

    this._pending = true;
    const origText = this._label ? this._label.textContent : '';
    if (this._label) {
      this._label.textContent = '…';
      this._label.classList.add('google-auth-badge__label--pending');
    }

    try {
      const result = await api.requestGoogleOAuth(['calendar', 'gmail', 'classroom']);
      if (result && result.success) {
        this.applyStatus({ google: true });
      } else {
        // Restore previous text on failure
        if (this._label) this._label.textContent = origText;
      }
    } catch (_err) {
      if (this._label) this._label.textContent = origText;
    } finally {
      this._pending = false;
      if (this._label) this._label.classList.remove('google-auth-badge__label--pending');
    }
  }

  /**
   * Convenience accessor for `window.overlayAPI` (allows test injection).
   * @returns {object|null}
   * @private
   */
  _api() {
    return (typeof window !== 'undefined' && window.overlayAPI) ? window.overlayAPI : null;
  }
}

// ── Export ────────────────────────────────────────────────────────────────────

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { GoogleAuthBadge, INITIAL_CHECK_DELAY_MS };
} else if (typeof window !== 'undefined') {
  window.GoogleAuthBadge = GoogleAuthBadge;
}

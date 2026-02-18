/**
 * Bantz Overlay — Classroom Dialog (Issue #1467)
 *
 * Provides two UI components for Google Classroom integration:
 *
 *   1. ClassroomDialog
 *      - "Classroom'a Katıl" enrollment code form
 *      - Calls window.overlayAPI.openClassroomEnrollment(code) on submit
 *      - Shows success / error feedback inline
 *
 *   2. GoogleAuthScopeIndicator
 *      - Shows which Google scopes are active (calendar / gmail / classroom)
 *      - Calls window.overlayAPI.requestGoogleOAuth(['classroom']) when the
 *        classroom scope badge is clicked and is not yet authorized
 *      - Updates when 'auth:status' arrives via window.overlayAPI.onAuthStatus
 *
 * Both classes follow the existing Overlay component pattern:
 *   - constructor() — set up state
 *   - mount(parent) — inject DOM
 *   - show() / hide() — toggle visibility
 *
 * Run tests: node bantz-overlay/tests/test_classroom_dialog.js
 */

'use strict';

// ─── ClassroomDialog ──────────────────────────────────────────────────────────

/**
 * Modal dialog that lets the user join a Google Classroom course by pasting
 * an enrollment / invitation code.
 *
 * Usage:
 *   const dlg = new ClassroomDialog();
 *   dlg.mount(document.body);
 *   dlg.show();
 */
class ClassroomDialog {
  constructor() {
    this._visible = false;
    this._root    = null;
    this._input   = null;
    this._status  = null;
    this._pending = false;
  }

  /**
   * Inject dialog DOM into the given parent element.
   * Idempotent — second call is a no-op.
   * @param {HTMLElement} parent
   */
  mount(parent) {
    if (this._root) return; // already mounted

    const overlay = document.createElement('div');
    overlay.className  = 'classroom-dialog-overlay hidden';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', "Classroom'a Katıl");

    const box = document.createElement('div');
    box.className = 'classroom-dialog-box';

    // ── Title ──
    const title = document.createElement('h2');
    title.className   = 'classroom-dialog-title';
    title.textContent = "Classroom'a Katıl";

    // ── Subtitle ──
    const subtitle = document.createElement('p');
    subtitle.className   = 'classroom-dialog-subtitle';
    subtitle.textContent = 'Katılmak istediğin dersin kodunu gir.';

    // ── Input ──
    const input = document.createElement('input');
    input.type        = 'text';
    input.className   = 'classroom-dialog-input';
    input.placeholder = 'Örn: abc123xz';
    input.maxLength   = 32;
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('aria-label', 'Classroom kodu');
    this._input = input;

    // ── Status message ──
    const status = document.createElement('p');
    status.className   = 'classroom-dialog-status hidden';
    status.setAttribute('role', 'status');
    this._status = status;

    // ── Buttons ──
    const btnRow = document.createElement('div');
    btnRow.className = 'classroom-dialog-btn-row';

    const btnJoin = document.createElement('button');
    btnJoin.className   = 'classroom-dialog-btn classroom-dialog-btn--primary';
    btnJoin.textContent = 'Katıl';
    btnJoin.setAttribute('type', 'button');

    const btnCancel = document.createElement('button');
    btnCancel.className   = 'classroom-dialog-btn classroom-dialog-btn--secondary';
    btnCancel.textContent = 'İptal';
    btnCancel.setAttribute('type', 'button');

    btnRow.appendChild(btnJoin);
    btnRow.appendChild(btnCancel);

    // ── Assemble ──
    box.appendChild(title);
    box.appendChild(subtitle);
    box.appendChild(input);
    box.appendChild(status);
    box.appendChild(btnRow);
    overlay.appendChild(box);
    parent.appendChild(overlay);

    this._root = overlay;

    // ── Event wiring ──
    btnJoin.addEventListener('click', () => this._submit());
    btnCancel.addEventListener('click', () => this.hide());

    // Close on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this._visible) this.hide();
    });

    // Close on backdrop click (click outside the box)
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) this.hide();
    });

    // Also submit on Enter inside input
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this._submit();
    });
  }

  /** Show the dialog and focus the input. */
  show() {
    if (!this._root) return;
    this._setStatus('', false);
    if (this._input) this._input.value = '';
    this._root.classList.remove('hidden');
    this._visible = true;
    if (this._input) this._input.focus();
  }

  /** Hide the dialog. */
  hide() {
    if (!this._root) return;
    this._root.classList.add('hidden');
    this._visible = false;
  }

  /** Whether the dialog is currently visible. */
  get visible() {
    return this._visible;
  }

  // ── Private Helpers ────────────────────────────────────────

  /**
   * Validate and submit the enrollment code.
   * @private
   */
  async _submit() {
    if (this._pending) return;

    const raw = this._input ? this._input.value.trim() : '';
    if (!raw) {
      this._setStatus('Lütfen bir Classroom kodu gir.', 'error');
      return;
    }
    // Enforce same rule as the IPC handler: alphanumeric, 1-32 chars
    const clean = raw.replace(/[^a-zA-Z0-9]/g, '');
    if (!clean) {
      this._setStatus('Geçersiz kod — yalnızca harf ve rakam kabul edilir.', 'error');
      return;
    }

    const api = (typeof window !== 'undefined') ? window.overlayAPI : null;
    if (!api || typeof api.openClassroomEnrollment !== 'function') {
      this._setStatus('overlayAPI mevcut değil.', 'error');
      return;
    }

    this._pending = true;
    this._setStatus('Açılıyor...', 'info');

    let ok = false;
    try {
      ok = await api.openClassroomEnrollment(clean);
    } catch (err) {
      console.warn('[ClassroomDialog] openClassroomEnrollment error:', err);
      ok = false;
    } finally {
      this._pending = false;
    }

    if (ok) {
      this._setStatus('Tarayıcıda açıldı!', 'success');
      setTimeout(() => this.hide(), 1500);
    } else {
      this._setStatus('Bağlantı açılamadı. Kodu kontrol et.', 'error');
    }
  }

  /**
   * Set the inline status message.
   * @param {string} text
   * @param {'error'|'success'|'info'|false} type  false → hide
   * @private
   */
  _setStatus(text, type) {
    if (!this._status) return;
    this._status.textContent = text;
    this._status.className   = 'classroom-dialog-status';
    if (!type) {
      this._status.classList.add('hidden');
    } else {
      this._status.classList.add(`classroom-dialog-status--${type}`);
    }
  }
}

// ─── GoogleAuthScopeIndicator ─────────────────────────────────────────────────

/**
 * Small status badge row showing which Google scopes are currently authorized.
 * Clicking a missing scope badge triggers the OAuth flow for that scope.
 *
 * Usage:
 *   const ind = new GoogleAuthScopeIndicator();
 *   ind.mount(document.getElementById('hud-panel'));
 *   // Automatically subscribes to auth:status updates.
 *
 * Emits no external events; self-contained.
 */
class GoogleAuthScopeIndicator {
  /**
   * @param {string[]} [scopes] - Which scopes to display. Defaults to all three.
   */
  constructor(scopes = ['calendar', 'gmail', 'classroom']) {
    this._scopes  = scopes;
    this._root    = null;
    this._badges  = {}; // scope → badge element
    this._status  = { calendar: false, gmail: false, classroom: false };
  }

  /**
   * Inject badge row DOM into the given parent element.
   * @param {HTMLElement} parent
   */
  mount(parent) {
    if (this._root) return;

    const container = document.createElement('div');
    container.className = 'google-auth-scope-indicator';

    const label = document.createElement('span');
    label.className   = 'google-auth-scope-label';
    label.textContent = 'Google:';
    container.appendChild(label);

    for (const scope of this._scopes) {
      const badge = document.createElement('button');
      badge.className = `google-auth-scope-badge google-auth-scope-badge--${scope} google-auth-scope-badge--inactive`;
      badge.textContent = this._scopeLabel(scope);
      badge.setAttribute('type', 'button');
      badge.setAttribute('title', `${this._scopeLabel(scope)} yetkisi — tıkla ve etkinleştir`);
      badge.dataset.scope = scope;
      badge.addEventListener('click', () => this._onBadgeClick(scope));
      container.appendChild(badge);
      this._badges[scope] = badge;
    }

    parent.appendChild(container);
    this._root = container;

    // Subscribe to live auth status updates
    const api = (typeof window !== 'undefined') ? window.overlayAPI : null;
    if (api && typeof api.onAuthStatus === 'function') {
      api.onAuthStatus((authStatus) => this._applyStatus(authStatus));
    }

    // Fetch current status
    if (api && typeof api.getAuthStatus === 'function') {
      api.getAuthStatus().then((s) => { if (s) this._applyStatus(s); }).catch(() => {});
    }
  }

  /**
   * Programmatically update which scopes are marked as authorized.
   * @param {{ google?: boolean, calendar?: boolean, gmail?: boolean, classroom?: boolean, needsSetup?: boolean }} authStatus
   */
  _applyStatus(authStatus) {
    if (!authStatus) return;

    // The auth:status event shape from main.js: { google: bool, needsSetup: bool }
    // For per-scope granularity we also handle { calendar, gmail, classroom } keys.
    const scopeMap = {
      calendar:  authStatus.calendar  ?? authStatus.google ?? false,
      gmail:     authStatus.gmail     ?? authStatus.google ?? false,
      classroom: authStatus.classroom ?? authStatus.google ?? false,
    };

    for (const scope of this._scopes) {
      const active = !!scopeMap[scope];
      this._status[scope] = active;
      const badge = this._badges[scope];
      if (!badge) continue;
      badge.classList.remove('google-auth-scope-badge--active', 'google-auth-scope-badge--inactive');
      badge.classList.add(active ? 'google-auth-scope-badge--active' : 'google-auth-scope-badge--inactive');
      badge.setAttribute('title', active
        ? `${this._scopeLabel(scope)} yetkisi aktif`
        : `${this._scopeLabel(scope)} yetkisi yok — tıkla ve etkinleştir`
      );
    }
  }

  /**
   * Handle badge click — trigger OAuth for that scope if not yet active.
   * @param {string} scope
   * @private
   */
  async _onBadgeClick(scope) {
    if (this._status[scope]) return; // already authorized, nothing to do

    const api = (typeof window !== 'undefined') ? window.overlayAPI : null;
    if (!api || typeof api.requestGoogleOAuth !== 'function') return;

    const badge = this._badges[scope];
    if (badge) {
      badge.classList.add('google-auth-scope-badge--pending');
      badge.textContent = '…';
    }

    try {
      const result = await api.requestGoogleOAuth([scope]);
      if (result && result.success) {
        this._status[scope] = true;
        if (badge) {
          badge.classList.remove('google-auth-scope-badge--pending');
          badge.classList.remove('google-auth-scope-badge--inactive');
          badge.classList.add('google-auth-scope-badge--active');
          badge.textContent = this._scopeLabel(scope);
        }
      } else {
        if (badge) {
          badge.classList.remove('google-auth-scope-badge--pending');
          badge.classList.add('google-auth-scope-badge--inactive');
          badge.textContent = this._scopeLabel(scope);
        }
        console.warn('[AuthScopeIndicator] OAuth failed:', result && result.error);
      }
    } catch (err) {
      if (badge) {
        badge.classList.remove('google-auth-scope-badge--pending');
        badge.classList.add('google-auth-scope-badge--inactive');
        badge.textContent = this._scopeLabel(scope);
      }
      console.warn('[AuthScopeIndicator] OAuth error:', err);
    }
  }

  /**
   * Human-readable label for a scope key.
   * @param {string} scope
   * @returns {string}
   * @private
   */
  _scopeLabel(scope) {
    const MAP = { calendar: 'Takvim', gmail: 'Gmail', classroom: 'Classroom' };
    return MAP[scope] || scope;
  }
}

// ─── Export ───────────────────────────────────────────────────────────────────

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { ClassroomDialog, GoogleAuthScopeIndicator };
} else if (typeof window !== 'undefined') {
  window.ClassroomDialog         = ClassroomDialog;
  window.GoogleAuthScopeIndicator = GoogleAuthScopeIndicator;
}

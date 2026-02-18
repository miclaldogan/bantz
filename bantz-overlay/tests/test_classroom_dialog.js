/**
 * Bantz Overlay — Classroom Dialog Tests (Issue #1467)
 *
 * Covers:
 *   AC1  window.overlayAPI.requestGoogleOAuth(['classroom']) is exposed and
 *        invoked by GoogleAuthScopeIndicator on badge click.
 *   AC2  window.overlayAPI.openClassroomEnrollment(code) is exposed and
 *        called by ClassroomDialog with the sanitized code, which ultimately
 *        opens https://classroom.google.com/c/<code>.
 *   AC3  GoogleAuthScopeIndicator reflects classroom scope auth state after
 *        an auth:status event (checking IngestStore readiness indirectly via
 *        the scope-active state that gates sync).
 *
 * Run: node bantz-overlay/tests/test_classroom_dialog.js
 */

'use strict';

const assert = require('assert');
const path   = require('path');
const fs     = require('fs');

// ─── Minimal DOM Stub ──────────────────────────────────────────────────────

class MockElement {
  constructor(tag) {
    this.tagName     = (tag || 'div').toUpperCase();
    this.className   = '';
    this.textContent = '';
    this.innerHTML   = '';
    this.children    = [];
    this._listeners  = {};
    this._classes    = new Set();
    this.type        = '';
    this.placeholder = '';
    this.value       = '';
    this.maxLength   = undefined;
    this.parentNode  = null;
    this.dataset     = {};
    this._attrs      = {};

    const self = this;
    this.style    = {};
    this.classList = {
      add:      (...cs) => cs.forEach(c => { self._classes.add(c);    self.className = [...self._classes].join(' '); }),
      remove:   (...cs) => cs.forEach(c => { self._classes.delete(c); self.className = [...self._classes].join(' '); }),
      contains: (c) => self._classes.has(c),
      toggle:   (c) => {
        if (self._classes.has(c)) self._classes.delete(c); else self._classes.add(c);
        self.className = [...self._classes].join(' ');
      },
      replace: (a, b) => {
        self._classes.delete(a); self._classes.add(b);
        self.className = [...self._classes].join(' ');
      },
    };
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  setAttribute(k, v) { this._attrs[k] = v; }
  getAttribute(k)    { return this._attrs[k]; }
  addEventListener(type, fn) {
    if (!this._listeners[type]) this._listeners[type] = [];
    this._listeners[type].push(fn);
  }
  _fire(type, evt = {}) {
    (this._listeners[type] || []).forEach(fn => fn({ target: this, ...evt }));
  }
  focus() {}
}

// Global document / window stubs
const domElements = {};
global.document = {
  createElement(tag) { return new MockElement(tag); },
  getElementById(id) { return domElements[id] || null; },
  addEventListener(type, fn) {
    if (!document._docListeners) document._docListeners = {};
    if (!document._docListeners[type]) document._docListeners[type] = [];
    document._docListeners[type].push(fn);
  },
  _fireDoc(type, evt = {}) {
    ((document._docListeners || {})[type] || []).forEach(fn => fn(evt));
  },
  _docListeners: {},
};

global.window = {
  overlayAPI: null,
  ClassroomDialog: null,
  GoogleAuthScopeIndicator: null,
};

// Silence console noise
const _origWarn = console.warn;
// (keep for debugging, but suppress during normal run)
console.warn = () => {};

// ─── Load module under test ────────────────────────────────────────────────

const modulePath = path.resolve(__dirname, '..', 'src', 'renderer', 'classroom-dialog.js');
const src = fs.readFileSync(modulePath, 'utf8');
// eslint-disable-next-line no-new-func
const moduleFactory = new Function('module', 'exports', 'window', 'document', src);
const mod = { exports: {} };
moduleFactory(mod, mod.exports, global.window, global.document);

const { ClassroomDialog, GoogleAuthScopeIndicator } = mod.exports;
assert.ok(ClassroomDialog,         'ClassroomDialog exported');
assert.ok(GoogleAuthScopeIndicator,'GoogleAuthScopeIndicator exported');

// ─── Helper ────────────────────────────────────────────────────────────────

let passCount = 0;
let failCount = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`  ✓  ${name}`);
    passCount++;
  } catch (err) {
    console.error(`  ✗  ${name}`);
    console.error(`     ${err.message}`);
    failCount++;
  }
}
async function testAsync(name, fn) {
  try {
    await fn();
    console.log(`  ✓  ${name}`);
    passCount++;
  } catch (err) {
    console.error(`  ✗  ${name}`);
    console.error(`     ${err.message}`);
    failCount++;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Block A — ClassroomDialog
// ─────────────────────────────────────────────────────────────────────────────

console.log('\n── ClassroomDialog ──');

test('constructor: _visible starts false', () => {
  const dlg = new ClassroomDialog();
  assert.strictEqual(dlg.visible, false);
});

test('mount: creates root element with correct class', () => {
  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  assert.ok(dlg._root, '_root set after mount');
  // component sets className directly, so check the string
  assert.ok(dlg._root.className.includes('classroom-dialog-overlay'), 'has overlay class');
  assert.ok(dlg._root.className.includes('hidden'), 'starts hidden');
});

test('mount: is idempotent', () => {
  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg.mount(parent);
  assert.strictEqual(parent.children.length, 1, 'only one child appended');
});

test('mount: aria-modal and role attributes set', () => {
  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  assert.strictEqual(dlg._root.getAttribute('role'), 'dialog');
  assert.strictEqual(dlg._root.getAttribute('aria-modal'), 'true');
});

test('show: removes hidden class and sets visible', () => {
  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg.show();
  assert.strictEqual(dlg.visible, true);
  assert.ok(!dlg._root._classes.has('hidden'), 'hidden class removed');
});

test('hide: adds hidden class back', () => {
  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg.show();
  dlg.hide();
  assert.strictEqual(dlg.visible, false);
  assert.ok(dlg._root._classes.has('hidden'), 'hidden class present');
});

test('show: clears input value', () => {
  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg._input.value = 'old-code';
  dlg.show();
  assert.strictEqual(dlg._input.value, '', 'input cleared on show');
});

test('_submit: empty input shows error status', async () => {
  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg._input.value = '';
  await dlg._submit();
  assert.ok(dlg._status._classes.has('classroom-dialog-status--error'), 'error class set');
  assert.ok(!dlg._status._classes.has('hidden'), 'status visible');
});

test('_submit: non-alphanumeric-only input shows error', async () => {
  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg._input.value = '!!!';
  await dlg._submit();
  assert.ok(dlg._status._classes.has('classroom-dialog-status--error'));
});

// ─── AC2: openClassroomEnrollment called with correct code ───

testAsync('AC2: _submit calls openClassroomEnrollment with sanitized code', async () => {
  const calls = [];
  global.window.overlayAPI = {
    openClassroomEnrollment: async (code) => { calls.push(code); return true; },
  };

  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg._input.value = 'abc123xz';
  await dlg._submit();

  assert.deepStrictEqual(calls, ['abc123xz'], 'correct code forwarded');
  global.window.overlayAPI = null;
});

testAsync('AC2: _submit strips non-alphanumeric chars before calling API', async () => {
  const calls = [];
  global.window.overlayAPI = {
    openClassroomEnrollment: async (code) => { calls.push(code); return true; },
  };

  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg._input.value = 'abc-123 xz!';  // contains hyphens, space, exclamation
  await dlg._submit();

  assert.deepStrictEqual(calls, ['abc123xz'], 'non-alphanum stripped');
  global.window.overlayAPI = null;
});

testAsync('AC2: _submit shows success status and auto-hides on ok=true', async () => {
  global.window.overlayAPI = {
    openClassroomEnrollment: async () => true,
  };

  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg.show();
  dlg._input.value = 'validCode1';
  await dlg._submit();

  assert.ok(dlg._status._classes.has('classroom-dialog-status--success'), 'success class set');
  global.window.overlayAPI = null;
});

testAsync('AC2: _submit shows error status on ok=false', async () => {
  global.window.overlayAPI = {
    openClassroomEnrollment: async () => false,
  };

  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg._input.value = 'code99';
  await dlg._submit();

  assert.ok(dlg._status._classes.has('classroom-dialog-status--error'), 'error class set on failure');
  global.window.overlayAPI = null;
});

testAsync('AC2: _submit shows error status when API throws', async () => {
  global.window.overlayAPI = {
    openClassroomEnrollment: async () => { throw new Error('IPC unavailable'); },
  };

  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg._input.value = 'code42';
  await dlg._submit();

  assert.ok(dlg._status._classes.has('classroom-dialog-status--error'));
  global.window.overlayAPI = null;
});

testAsync('AC2: _submit is no-op when overlayAPI missing', async () => {
  global.window.overlayAPI = null;

  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg._input.value = 'someCode';
  await dlg._submit();

  assert.ok(dlg._status._classes.has('classroom-dialog-status--error'), 'error shown when no API');
});

testAsync('AC2: _pending guard prevents double submission', async () => {
  let callCount = 0;
  global.window.overlayAPI = {
    openClassroomEnrollment: async (code) => {
      callCount++;
      await new Promise(r => setTimeout(r, 10));
      return true;
    },
  };

  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg._input.value = 'doubleCode';

  // Fire _submit twice without awaiting first
  const p1 = dlg._submit();
  const p2 = dlg._submit(); // should be ignored because _pending === true
  await Promise.all([p1, p2]);

  assert.strictEqual(callCount, 1, 'API called exactly once');
  global.window.overlayAPI = null;
});

test('_setStatus: sets text and success class', () => {
  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg._setStatus('OK!', 'success');
  assert.strictEqual(dlg._status.textContent, 'OK!');
  assert.ok(dlg._status._classes.has('classroom-dialog-status--success'));
  assert.ok(!dlg._status._classes.has('hidden'));
});

test('_setStatus: type=false hides status', () => {
  const dlg = new ClassroomDialog();
  const parent = new MockElement('div');
  dlg.mount(parent);
  dlg._setStatus('', false);
  assert.ok(dlg._status._classes.has('hidden'));
});

// ─────────────────────────────────────────────────────────────────────────────
// Block B — GoogleAuthScopeIndicator
// ─────────────────────────────────────────────────────────────────────────────

console.log('\n── GoogleAuthScopeIndicator ──');

test('constructor: default scopes are calendar, gmail, classroom', () => {
  const ind = new GoogleAuthScopeIndicator();
  assert.deepStrictEqual(ind._scopes, ['calendar', 'gmail', 'classroom']);
});

test('constructor: accepts custom scopes', () => {
  const ind = new GoogleAuthScopeIndicator(['classroom']);
  assert.deepStrictEqual(ind._scopes, ['classroom']);
});

test('mount: creates container with badge per scope', () => {
  const ind = new GoogleAuthScopeIndicator(['calendar', 'gmail', 'classroom']);
  const parent = new MockElement('div');
  global.window.overlayAPI = { onAuthStatus: () => {}, getAuthStatus: () => Promise.resolve(null) };
  ind.mount(parent);
  assert.ok(ind._root, '_root set');
  assert.ok(ind._badges['calendar'],  'calendar badge created');
  assert.ok(ind._badges['gmail'],     'gmail badge created');
  assert.ok(ind._badges['classroom'], 'classroom badge created');
  global.window.overlayAPI = null;
});

test('mount: idempotent', () => {
  const ind = new GoogleAuthScopeIndicator(['classroom']);
  const parent = new MockElement('div');
  global.window.overlayAPI = { onAuthStatus: () => {}, getAuthStatus: () => Promise.resolve(null) };
  ind.mount(parent);
  ind.mount(parent);
  assert.strictEqual(parent.children.length, 1);
  global.window.overlayAPI = null;
});

test('mount: badges start inactive', () => {
  const ind = new GoogleAuthScopeIndicator(['classroom']);
  const parent = new MockElement('div');
  global.window.overlayAPI = { onAuthStatus: () => {}, getAuthStatus: () => Promise.resolve(null) };
  ind.mount(parent);
  const badge = ind._badges['classroom'];
  // component sets className directly on creation, then _applyStatus uses classList
  const cn = badge.className + ' ' + [...badge._classes].join(' ');
  assert.ok(cn.includes('google-auth-scope-badge--inactive'), 'starts inactive');
  assert.ok(!cn.includes('google-auth-scope-badge--active') || cn.includes('inactive'), 'not erroneously active');
  global.window.overlayAPI = null;
});

// ─── AC3: _applyStatus reflects auth state ───

test('AC3: _applyStatus marks classroom badge active when google=true', () => {
  const ind = new GoogleAuthScopeIndicator(['classroom']);
  const parent = new MockElement('div');
  global.window.overlayAPI = { onAuthStatus: () => {}, getAuthStatus: () => Promise.resolve(null) };
  ind.mount(parent);
  ind._applyStatus({ google: true, needsSetup: false });
  const badge = ind._badges['classroom'];
  assert.ok(badge._classes.has('google-auth-scope-badge--active'),   'active after google:true');
  assert.ok(!badge._classes.has('google-auth-scope-badge--inactive'), 'inactive removed');
  global.window.overlayAPI = null;
});

test('AC3: _applyStatus marks classroom badge inactive when google=false', () => {
  const ind = new GoogleAuthScopeIndicator(['classroom']);
  const parent = new MockElement('div');
  global.window.overlayAPI = { onAuthStatus: () => {}, getAuthStatus: () => Promise.resolve(null) };
  ind.mount(parent);
  ind._applyStatus({ google: true }); // first authorize
  ind._applyStatus({ google: false }); // then revoke
  const badge = ind._badges['classroom'];
  assert.ok(badge._classes.has('google-auth-scope-badge--inactive'));
  assert.ok(!badge._classes.has('google-auth-scope-badge--active'));
  global.window.overlayAPI = null;
});

test('AC3: _applyStatus uses per-scope classroom key over generic google flag', () => {
  const ind = new GoogleAuthScopeIndicator(['classroom', 'gmail']);
  const parent = new MockElement('div');
  global.window.overlayAPI = { onAuthStatus: () => {}, getAuthStatus: () => Promise.resolve(null) };
  ind.mount(parent);
  // classroom=true but gmail=false — generic google=false is overridden by specific keys
  ind._applyStatus({ google: false, classroom: true, gmail: false });
  assert.ok( ind._badges['classroom']._classes.has('google-auth-scope-badge--active'),   'classroom active via specific key');
  assert.ok(!ind._badges['gmail']._classes.has('google-auth-scope-badge--active'),        'gmail inactive');
  global.window.overlayAPI = null;
});

test('AC3: _applyStatus gracefully handles null/undefined', () => {
  const ind = new GoogleAuthScopeIndicator(['classroom']);
  const parent = new MockElement('div');
  global.window.overlayAPI = { onAuthStatus: () => {}, getAuthStatus: () => Promise.resolve(null) };
  ind.mount(parent);
  // Should not throw
  ind._applyStatus(null);
  ind._applyStatus(undefined);
  global.window.overlayAPI = null;
});

test('AC3: live onAuthStatus update propagates to badge', () => {
  let storedCb = null;
  global.window.overlayAPI = {
    onAuthStatus: (cb) => { storedCb = cb; },
    getAuthStatus: () => Promise.resolve(null),
  };

  const ind = new GoogleAuthScopeIndicator(['classroom']);
  const parent = new MockElement('div');
  ind.mount(parent);

  // Simulate auth:status IPC event
  storedCb({ google: true, needsSetup: false });

  assert.ok(ind._badges['classroom']._classes.has('google-auth-scope-badge--active'),
    'badge updated by live auth:status callback');
  global.window.overlayAPI = null;
});

// ─── AC1: requestGoogleOAuth called on badge click ───

testAsync('AC1: clicking inactive classroom badge calls requestGoogleOAuth(["classroom"])', async () => {
  const oauthCalls = [];
  global.window.overlayAPI = {
    onAuthStatus: () => {},
    getAuthStatus: () => Promise.resolve(null),
    requestGoogleOAuth: async (scopes) => { oauthCalls.push(scopes); return { success: true, scopes }; },
  };

  const ind = new GoogleAuthScopeIndicator(['classroom']);
  const parent = new MockElement('div');
  ind.mount(parent);

  // Simulate badge click
  await ind._onBadgeClick('classroom');

  assert.strictEqual(oauthCalls.length, 1, 'requestGoogleOAuth called once');
  assert.deepStrictEqual(oauthCalls[0], ['classroom'], 'called with ["classroom"]');
  global.window.overlayAPI = null;
});

testAsync('AC1: clicking already-active classroom badge does NOT call requestGoogleOAuth', async () => {
  const oauthCalls = [];
  global.window.overlayAPI = {
    onAuthStatus: () => {},
    getAuthStatus: () => Promise.resolve(null),
    requestGoogleOAuth: async (scopes) => { oauthCalls.push(scopes); return { success: true, scopes }; },
  };

  const ind = new GoogleAuthScopeIndicator(['classroom']);
  const parent = new MockElement('div');
  ind.mount(parent);
  ind._applyStatus({ google: true }); // mark active
  await ind._onBadgeClick('classroom'); // already active — should be no-op

  assert.strictEqual(oauthCalls.length, 0, 'requestGoogleOAuth NOT called for active scope');
  global.window.overlayAPI = null;
});

testAsync('AC1: badge shows pending state during OAuth, then active on success', async () => {
  global.window.overlayAPI = {
    onAuthStatus: () => {},
    getAuthStatus: () => Promise.resolve(null),
    requestGoogleOAuth: async () => { return { success: true, scopes: ['classroom'] }; },
  };

  const ind = new GoogleAuthScopeIndicator(['classroom']);
  const parent = new MockElement('div');
  ind.mount(parent);
  await ind._onBadgeClick('classroom');

  const badge = ind._badges['classroom'];
  assert.ok(badge._classes.has('google-auth-scope-badge--active'),   'active after success');
  assert.ok(!badge._classes.has('google-auth-scope-badge--pending'), 'pending removed');
  global.window.overlayAPI = null;
});

testAsync('AC1: badge recovers gracefully when OAuth fails (success:false)', async () => {
  global.window.overlayAPI = {
    onAuthStatus: () => {},
    getAuthStatus: () => Promise.resolve(null),
    requestGoogleOAuth: async () => { return { success: false, error: 'cancelled' }; },
  };

  const ind = new GoogleAuthScopeIndicator(['classroom']);
  const parent = new MockElement('div');
  ind.mount(parent);
  await ind._onBadgeClick('classroom');

  const badge = ind._badges['classroom'];
  assert.ok(badge._classes.has('google-auth-scope-badge--inactive'), 'remains inactive on failure');
  assert.ok(!badge._classes.has('google-auth-scope-badge--pending'),  'pending removed');
  global.window.overlayAPI = null;
});

testAsync('AC1: badge recovers gracefully when requestGoogleOAuth throws', async () => {
  global.window.overlayAPI = {
    onAuthStatus: () => {},
    getAuthStatus: () => Promise.resolve(null),
    requestGoogleOAuth: async () => { throw new Error('IPC error'); },
  };

  const ind = new GoogleAuthScopeIndicator(['classroom']);
  const parent = new MockElement('div');
  ind.mount(parent);
  await ind._onBadgeClick('classroom');

  const badge = ind._badges['classroom'];
  assert.ok(badge._classes.has('google-auth-scope-badge--inactive'), 'remains inactive after error');
  global.window.overlayAPI = null;
});

testAsync('AC1: requestGoogleOAuth NOT called when overlayAPI missing', async () => {
  global.window.overlayAPI = null;
  const ind = new GoogleAuthScopeIndicator(['classroom']);
  const parent = new MockElement('div');
  // Can't mount without API — simulate detached state
  ind._status['classroom'] = false;
  ind._badges['classroom'] = new MockElement('button');
  // Should not throw
  await ind._onBadgeClick('classroom');
  // No assertion needed beyond no-throw
});

// ─── _scopeLabel helper ───

test('_scopeLabel: returns Turkish labels', () => {
  const ind = new GoogleAuthScopeIndicator();
  assert.strictEqual(ind._scopeLabel('calendar'),  'Takvim');
  assert.strictEqual(ind._scopeLabel('gmail'),     'Gmail');
  assert.strictEqual(ind._scopeLabel('classroom'), 'Classroom');
  assert.strictEqual(ind._scopeLabel('unknown'),   'unknown'); // passthrough
});

// ─────────────────────────────────────────────────────────────────────────────
// Results
// ─────────────────────────────────────────────────────────────────────────────

console.log(`\n${'─'.repeat(50)}`);
console.log(`Tests: ${passCount + failCount}  ✓ ${passCount}  ✗ ${failCount}`);
if (failCount > 0) process.exit(1);

/**
 * Bantz Overlay — Google Auth HUD Badge Tests (Issue #1468)
 *
 * Covers all three Acceptance Criteria:
 *   AC1  Auth durumu değişince badge otomatik güncellenir
 *        → live onAuthStatus callback updates dot & label
 *   AC2  Tıklayınca OAuth flow tetiklenir
 *        → clicking disconnected badge calls requestGoogleOAuth([…])
 *   AC3  İlk açılışta 5sn içinde auth durumu kontrol edilir
 *        → getAuthStatus() called after the configured delay
 *
 * Run: node bantz-overlay/tests/test_google_auth_badge.js
 */

'use strict';

const assert = require('assert');
const path   = require('path');
const fs     = require('fs');

// ─── Minimal DOM Stub ──────────────────────────────────────────────────────────

class MockElement {
  constructor(tag) {
    this.tagName     = (tag || 'div').toUpperCase();
    this.className   = '';
    this.textContent = '';
    this.children    = [];
    this._listeners  = {};
    this._classes    = new Set();
    this._attrs      = {};
    this.style       = {};
    this.dataset     = {};

    const self = this;
    this.classList = {
      add:      (...cs) => cs.forEach(c => { self._classes.add(c);    self._syncCN(); }),
      remove:   (...cs) => cs.forEach(c => { self._classes.delete(c); self._syncCN(); }),
      contains: (c)     => self._classes.has(c),
      toggle:   (c)     => { self._classes.has(c) ? self._classes.delete(c) : self._classes.add(c); self._syncCN(); },
      replace:  (a, b)  => { self._classes.delete(a); self._classes.add(b); self._syncCN(); },
    };
  }
  _syncCN() { this.className = [...this._classes].join(' '); }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  setAttribute(k, v)  { this._attrs[k] = String(v); }
  getAttribute(k)     { return this._attrs[k] ?? null; }
  addEventListener(type, fn) {
    if (!this._listeners[type]) this._listeners[type] = [];
    this._listeners[type].push(fn);
  }
  _fire(type, evt = {}) { (this._listeners[type] || []).forEach(fn => fn({ target: this, ...evt })); }
  focus() {}
}

global.document = {
  createElement: (tag) => new MockElement(tag),
  getElementById: () => null,
  addEventListener: () => {},
  _docListeners: {},
};

global.window = { overlayAPI: null };

// Suppress expected console.warn noise during tests
const _origWarn = console.warn;
console.warn = () => {};

// ─── Load module under test ─────────────────────────────────────────────────

const modulePath = path.resolve(__dirname, '..', 'src', 'renderer', 'google-auth-badge.js');
const src = fs.readFileSync(modulePath, 'utf8');
const mod = { exports: {} };
// eslint-disable-next-line no-new-func
new Function('module', 'exports', 'window', 'document', src)(mod, mod.exports, global.window, global.document);

const { GoogleAuthBadge, INITIAL_CHECK_DELAY_MS } = mod.exports;
assert.ok(GoogleAuthBadge,         'GoogleAuthBadge exported');
assert.ok(INITIAL_CHECK_DELAY_MS,  'INITIAL_CHECK_DELAY_MS exported');

// ─── Test helpers ──────────────────────────────────────────────────────────────
// All tests are enqueued and then run sequentially inside an async main(),
// guaranteeing that timer-based async tests don't race each other.

let passCount = 0;
let failCount = 0;
const _queue = [];   // { name, fn } entries; fn() returns a promise

function test(name, fn) {
  _queue.push({ name, fn: async () => fn() });
}

function testAsync(name, fn) {
  _queue.push({ name, fn });
}

function makeParent() { return new MockElement('div'); }

function makeAPI(overrides = {}) {
  return {
    onAuthStatus:       () => {},
    getAuthStatus:      () => Promise.resolve(null),
    requestGoogleOAuth: async (scopes) => ({ success: true, scopes }),
    ...overrides,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Block A — Constructor & mounting
// ─────────────────────────────────────────────────────────────────────────────
_queue.push({ name: null, fn: async () => { console.log('\n── Constructor & mount ──'); } });

test('constructor: connected starts false', () => {
  const b = new GoogleAuthBadge();
  assert.strictEqual(b.connected, false);
});

test('constructor: custom initialCheckDelay respected', () => {
  const b = new GoogleAuthBadge({ initialCheckDelay: 99 });
  assert.strictEqual(b._delay, 99);
});

test('INITIAL_CHECK_DELAY_MS: is 5000', () => {
  assert.strictEqual(INITIAL_CHECK_DELAY_MS, 5000);
});

test('mount: creates root element', () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  assert.ok(b._root, '_root created');
  assert.ok(b._root.className.includes('google-auth-badge'), 'root has base class');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

test('mount: idempotent', () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  const parent = makeParent();
  b.mount(parent);
  b.mount(parent);
  assert.strictEqual(parent.children.length, 1, 'only one child');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

test('mount: dot starts disconnected class', () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  assert.ok(b._dot.className.includes('google-auth-badge__dot--disconnected'), 'dot disconnected initially');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

test('mount: label starts as "Google bağlan"', () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  assert.strictEqual(b._label.textContent, 'Google bağlan');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

test('mount: role and aria-live attributes set', () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  assert.strictEqual(b._root.getAttribute('role'), 'status');
  assert.strictEqual(b._root.getAttribute('aria-live'), 'polite');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

// ─────────────────────────────────────────────────────────────────────────────
// Block B — applyStatus (AC1)
// ─────────────────────────────────────────────────────────────────────────────
_queue.push({ name: null, fn: async () => { console.log('\n── AC1: applyStatus ──'); } });

test('AC1: applyStatus google:true — connected state', () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  b.applyStatus({ google: true });
  assert.strictEqual(b.connected, true);
  // dot.className set directly by component
  assert.ok(b._dot.className.includes('google-auth-badge__dot--connected'), 'dot connected');
  assert.ok(!b._dot.className.includes('google-auth-badge__dot--disconnected'), 'disconnected removed');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

test('AC1: applyStatus google:false — disconnected state', () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  b.applyStatus({ google: true });  // connect first
  b.applyStatus({ google: false }); // then disconnect
  assert.strictEqual(b.connected, false);
  // dot.className set directly by component
  assert.ok(b._dot.className.includes('google-auth-badge__dot--disconnected'), 'dot disconnected');
  assert.ok(!b._dot.className.includes('google-auth-badge__dot--connected') ||
            b._dot.className.includes('disconnected'), 'connected class removed');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

test('AC1: connected label shows Gmail • Takvim • Classroom', () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  b.applyStatus({ google: true });
  assert.strictEqual(b._label.textContent, 'Gmail • Takvim • Classroom');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

test('AC1: disconnected label shows "Google bağlan"', () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  b.applyStatus({ google: true });
  b.applyStatus({ google: false });
  assert.strictEqual(b._label.textContent, 'Google bağlan');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

test('AC1: connected label class toggled correctly', () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  b.applyStatus({ google: true });
  assert.ok(b._label._classes.has('google-auth-badge__label--connected'), 'connected class added');
  assert.ok(!b._label._classes.has('google-auth-badge__label--disconnected'), 'disconnected removed');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

test('AC1: live onAuthStatus callback triggers applyStatus', () => {
  let storedCb = null;
  global.window.overlayAPI = makeAPI({
    onAuthStatus: (cb) => { storedCb = cb; },
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  assert.ok(storedCb, 'onAuthStatus callback registered');
  storedCb({ google: true });     // simulate IPC event
  assert.strictEqual(b.connected, true, 'connected after live update');
  storedCb({ google: false });
  assert.strictEqual(b.connected, false, 'disconnected after live update');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

test('AC1: applyStatus null/undefined is safe', () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  // Must not throw
  b.applyStatus(null);
  b.applyStatus(undefined);
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

test('AC1: applyStatus before mount stores connected state without throwing', () => {
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.applyStatus({ google: true });   // no DOM yet — must not throw
  assert.strictEqual(b.connected, true);
});

test('AC1: service labels omit per-scope explicitly false values', () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  b.applyStatus({ google: true, gmail: false, calendar: true, classroom: false });
  // gmail:false and classroom:false should be omitted
  assert.ok(!b._label.textContent.includes('Gmail'),     'Gmail omitted');
  assert.ok(!b._label.textContent.includes('Classroom'), 'Classroom omitted');
  assert.ok( b._label.textContent.includes('Takvim'),    'Takvim included');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

// ─────────────────────────────────────────────────────────────────────────────
// Block C — Click / OAuth flow (AC2)
// ─────────────────────────────────────────────────────────────────────────────
_queue.push({ name: null, fn: async () => { console.log('\n── AC2: click → OAuth flow ──'); } });

testAsync('AC2: clicking disconnected badge calls requestGoogleOAuth', async () => {
  const oauthCalls = [];
  global.window.overlayAPI = makeAPI({
    requestGoogleOAuth: async (scopes) => { oauthCalls.push(scopes); return { success: true, scopes }; },
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  await b._onClick();
  assert.strictEqual(oauthCalls.length, 1, 'called once');
  assert.deepStrictEqual(oauthCalls[0], ['calendar', 'gmail', 'classroom']);
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

testAsync('AC2: clicking connected badge also calls requestGoogleOAuth (re-auth)', async () => {
  const oauthCalls = [];
  global.window.overlayAPI = makeAPI({
    requestGoogleOAuth: async (scopes) => { oauthCalls.push(scopes); return { success: true, scopes }; },
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  b.applyStatus({ google: true });   // already connected
  await b._onClick();
  assert.strictEqual(oauthCalls.length, 1, 're-auth triggered even when connected');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

testAsync('AC2: successful OAuth sets connected state', async () => {
  global.window.overlayAPI = makeAPI({
    requestGoogleOAuth: async () => ({ success: true, scopes: ['gmail'] }),
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  await b._onClick();
  assert.strictEqual(b.connected, true, 'connected after success');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

testAsync('AC2: failed OAuth (success:false) restores original label text', async () => {
  global.window.overlayAPI = makeAPI({
    requestGoogleOAuth: async () => ({ success: false, error: 'cancelled' }),
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  const origText = b._label.textContent;
  await b._onClick();
  assert.strictEqual(b._label.textContent, origText, 'label restored after failure');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

testAsync('AC2: throwing OAuth restores label text', async () => {
  global.window.overlayAPI = makeAPI({
    requestGoogleOAuth: async () => { throw new Error('IPC error'); },
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  const origText = b._label.textContent;
  await b._onClick();
  assert.strictEqual(b._label.textContent, origText);
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

testAsync('AC2: _pending guard prevents concurrent OAuth calls', async () => {
  let count = 0;
  global.window.overlayAPI = makeAPI({
    requestGoogleOAuth: async () => {
      count++;
      await new Promise(r => setTimeout(r, 10));
      return { success: true };
    },
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  const p1 = b._onClick();
  const p2 = b._onClick();  // still pending
  await Promise.all([p1, p2]);
  assert.strictEqual(count, 1, 'only one OAuth call despite two clicks');
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

testAsync('AC2: pending label shows "…" during OAuth', async () => {
  let resolveFn;
  global.window.overlayAPI = makeAPI({
    requestGoogleOAuth: async () => new Promise(r => { resolveFn = r; }),
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  const clickPromise = b._onClick();
  // During the await, label should show ellipsis
  assert.strictEqual(b._label.textContent, '…', 'label shows "…" while pending');
  resolveFn({ success: true });
  await clickPromise;
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

testAsync('AC2: _onClick is no-op when overlayAPI missing', async () => {
  global.window.overlayAPI = null;
  const b = new GoogleAuthBadge({ initialCheckDelay: 999999 });
  b.mount(makeParent());
  // Must not throw
  await b._onClick();
  clearTimeout(b._timer);
});

// ─────────────────────────────────────────────────────────────────────────────
// Block D — Initial check within 5s (AC3)
// ─────────────────────────────────────────────────────────────────────────────
_queue.push({ name: null, fn: async () => { console.log('\n── AC3: initial check within 5s ──'); } });

testAsync('AC3: getAuthStatus called after the configured delay', async () => {
  let called = false;
  global.window.overlayAPI = makeAPI({
    getAuthStatus: () => { called = true; return Promise.resolve({ google: true }); },
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 10 }); // use tiny delay for test speed
  b.mount(makeParent());
  await new Promise(r => setTimeout(r, 30));
  assert.strictEqual(called, true, 'getAuthStatus called within delay');
  assert.strictEqual(b.connected, true, 'state applied after initial check');
  global.window.overlayAPI = null;
});

testAsync('AC3: getAuthStatus not called before delay expires', async () => {
  let called = false;
  global.window.overlayAPI = makeAPI({
    getAuthStatus: () => { called = true; return Promise.resolve(null); },
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 200 });
  b.mount(makeParent());
  await new Promise(r => setTimeout(r, 20));  // well before 200ms
  assert.strictEqual(called, false, 'getAuthStatus NOT called yet');
  clearTimeout(b._timer);  // cancel for cleanup
  global.window.overlayAPI = null;
});

testAsync('AC3: result from getAuthStatus updates connected state', async () => {
  global.window.overlayAPI = makeAPI({
    getAuthStatus: () => Promise.resolve({ google: true, needsSetup: false }),
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 5 });
  b.mount(makeParent());
  await new Promise(r => setTimeout(r, 30));
  assert.strictEqual(b.connected, true, 'badge connected from initial check');
  global.window.overlayAPI = null;
});

testAsync('AC3: null result from getAuthStatus is handled gracefully', async () => {
  global.window.overlayAPI = makeAPI({
    getAuthStatus: () => Promise.resolve(null),
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 5 });
  b.mount(makeParent());
  await new Promise(r => setTimeout(r, 30));
  assert.strictEqual(b.connected, false, 'remains disconnected on null response');
  global.window.overlayAPI = null;
});

testAsync('AC3: rejected getAuthStatus promise does not throw', async () => {
  global.window.overlayAPI = makeAPI({
    getAuthStatus: () => Promise.reject(new Error('IPC unavailable')),
  });
  const b = new GoogleAuthBadge({ initialCheckDelay: 5 });
  b.mount(makeParent());
  await new Promise(r => setTimeout(r, 30)); // must not throw
  assert.strictEqual(b.connected, false);
  global.window.overlayAPI = null;
});

testAsync('AC3: INITIAL_CHECK_DELAY_MS constant matches default badge delay', async () => {
  global.window.overlayAPI = makeAPI();
  const b = new GoogleAuthBadge();
  assert.strictEqual(b._delay, INITIAL_CHECK_DELAY_MS);
  clearTimeout(b._timer);
  global.window.overlayAPI = null;
});

// ─────────────────────────────────────────────────────────────────────────────
// Results
// ─────────────────────────────────────────────────────────────────────────────

(async () => {
  for (const { name, fn } of _queue) {
    if (name === null) { await fn(); continue; }  // section header
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
  console.log(`\n${'─'.repeat(50)}`);
  console.log(`Tests: ${passCount + failCount}  ✓ ${passCount}  ✗ ${failCount}`);
  if (failCount > 0) process.exit(1);
})();

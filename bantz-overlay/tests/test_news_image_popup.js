/**
 * Bantz Overlay — News Image Popup Tests (Issue #1465)
 *
 * Validates the spreadSlots off-screen bug fix:
 *   - Popups use `position: fixed` (viewport-relative)
 *   - No popup slot places the element off-screen (-% values)
 *   - 3 popups can show concurrently in 3 different corners
 *   - Loading placeholder shown initially; replaced on image load
 *   - `loading="lazy"` is NOT set (Electron IntersectionObserver unreliable)
 *
 * Run: node bantz-overlay/tests/test_news_image_popup.js
 */

'use strict';

const assert = require('assert');
const path   = require('path');
const fs     = require('fs');

// ─── Minimal DOM Stub ──────────────────────────────────────────────────────
// Provides just enough browser API surface for news-image-popup.js to execute.

class MockElement {
  constructor(tag) {
    this.tagName     = tag.toUpperCase();
    this.className   = '';
    this.style       = {};
    this.textContent = '';
    this.innerHTML   = '';
    this.children    = [];
    this._listeners  = {};
    this._classes    = new Set();
    this.src         = '';
    this.alt         = '';
    this.loading     = undefined; // deliberately undefined by default
    this.onload      = null;
    this.onerror     = null;
    this.parentNode  = null;
    // classList stub
    const self = this;
    this.classList = {
      add:    (...cs) => cs.forEach(c => { self._classes.add(c); self.className = [...self._classes].join(' '); }),
      remove: (...cs) => cs.forEach(c => { self._classes.delete(c); self.className = [...self._classes].join(' '); }),
      contains: (c) => self._classes.has(c),
      toggle: (c) => { if (self._classes.has(c)) { self._classes.delete(c); } else { self._classes.add(c); } self.className = [...self._classes].join(' '); },
    };
  }
  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  removeChild(child) {
    const i = this.children.indexOf(child);
    if (i !== -1) this.children.splice(i, 1);
  }
  addEventListener(type, fn) {
    if (!this._listeners[type]) this._listeners[type] = [];
    this._listeners[type].push(fn);
  }
  dispatchEvent(type) {
    (this._listeners[type] || []).forEach(fn => fn());
  }
  setAttribute(k, v) { this[k] = v; }
  // Simulate DOM insertion end-to-end: let style.cssText setter split into keys
  set cssText(val) {
    // Parse "key: value;" pairs into this.style object
    val.split(';').forEach(part => {
      const [k, ...rest] = part.split(':');
      if (k && rest.length) {
        const key   = k.trim().replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        const value = rest.join(':').trim();
        this.style[key] = value;
      }
    });
  }
}

// Override style.cssText setter on instances
function makeMockElement(tag) {
  const el = new MockElement(tag);
  let _cssText = '';
  Object.defineProperty(el.style, 'cssText', {
    get: () => _cssText,
    set: (val) => {
      _cssText = val;
      val.split(';').forEach(part => {
        const [k, ...rest] = part.split(':');
        if (k && rest.length) {
          const key   = k.trim().replace(/-([a-z])/g, (_, c) => c.toUpperCase());
          const value = rest.join(':').trim();
          el.style[key] = value;
        }
      });
    },
    configurable: true,
  });
  return el;
}

// ─── Global stubs ──────────────────────────────────────────────────────────

const createdElements = [];
global.document = {
  createElement: (tag) => {
    const el = makeMockElement(tag);
    createdElements.push(el);
    return el;
  },
  getElementById: () => null,
  head: { appendChild: () => {} },
};
global.window = {
  overlayAPI: null,
};
global.requestAnimationFrame = (fn) => fn();

// Silence setTimeout/clearTimeout for auto-dismiss (not under test here)
global.setTimeout  = (fn, _ms) => { /* no-op */ return 0; };
global.clearTimeout = () => {};

// ─── Load the component ────────────────────────────────────────────────────

const popupSrc = fs.readFileSync(
  path.resolve(__dirname, '../src/renderer/components/news-image-popup.js'),
  'utf8'
);
// Execute in this context so global.window, global.document are picked up.
// eslint-disable-next-line no-new-func
new Function('window', 'document', 'requestAnimationFrame', 'setTimeout', 'clearTimeout', popupSrc)(
  global.window,
  global.document,
  global.requestAnimationFrame,
  global.setTimeout,
  global.clearTimeout,
);
const NewsImagePopup = global.window.NewsImagePopup;

// ─── Helpers ───────────────────────────────────────────────────────────────

function makeParent() {
  return makeMockElement('div');
}

function extractStyleMap(el) {
  // Parse el.style.cssText back into a plain object for assertions
  const map = {};
  (el.style.cssText || '').split(';').forEach(part => {
    const [k, ...rest] = part.split(':');
    if (k && rest.length) map[k.trim()] = rest.join(':').trim();
  });
  // Also include individually-set keys
  Object.entries(el.style).forEach(([k, v]) => {
    if (k !== 'cssText' && typeof v === 'string' && v) map[k] = v;
  });
  return map;
}

// ─── Test Runner ───────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    console.log(`  ✓  ${name}`);
    passed++;
  } catch (err) {
    console.error(`  ✗  ${name}`);
    console.error(`     ${err.message}`);
    failed++;
    failures.push({ name, err });
  }
}

// ─── Suite: IMAGE_CONFIG shape ─────────────────────────────────────────────

console.log('\nIMAGE_CONFIG shape');

test('IMAGE_CONFIG exported via class usage (NewsImagePopup exists)', () => {
  assert.strictEqual(typeof NewsImagePopup, 'function');
});

// Re-read source to inspect the config literal directly (no export needed)
test('spreadSlots has exactly 3 entries', () => {
  const match = popupSrc.match(/spreadSlots\s*:\s*\[[\s\S]*?\],/);
  assert.ok(match, 'spreadSlots not found in source');
  // Count opening { in the array
  const slots = popupSrc.match(/\{\s*(?:top|bottom):[^}]+\}/g) || [];
  // Filter to only the spreadSlots block
  const blockStart = popupSrc.indexOf('spreadSlots');
  const blockEnd   = popupSrc.indexOf('],', blockStart);
  const block      = popupSrc.slice(blockStart, blockEnd);
  const slotCount  = (block.match(/\{/g) || []).length;
  assert.strictEqual(slotCount, 3, `Expected 3 spreadSlots, got ${slotCount}`);
});

test('maxConcurrent is 3', () => {
  assert.ok(/maxConcurrent\s*:\s*3/.test(popupSrc), 'maxConcurrent should be 3');
});

test('popupWidth is 560', () => {
  assert.ok(/popupWidth\s*:\s*560/.test(popupSrc), 'popupWidth should be 560');
});

test('popupHeight is 380', () => {
  assert.ok(/popupHeight\s*:\s*380/.test(popupSrc), 'popupHeight should be 380');
});

test('no spreadSlot uses negative percentage values like -108% or -110%', () => {
  const blockStart = popupSrc.indexOf('spreadSlots');
  const blockEnd   = popupSrc.indexOf('],', blockStart);
  const block      = popupSrc.slice(blockStart, blockEnd);
  assert.ok(!/-\d+%/.test(block), 'Found negative % in spreadSlots — off-screen bug!');
});

// ─── Suite: position: fixed (viewport-relative) ────────────────────────────

console.log('\nposition: fixed (AC: no popup is off-screen)');

test('popup element uses position: fixed, not absolute', () => {
  const parent = makeParent();
  const popup  = new NewsImagePopup(parent);
  popup.show({ image_url: 'https://example.com/img.jpg', title: 'Test' });

  const popupEl = parent.children[0];
  assert.ok(popupEl, 'popup element should be appended to parent');

  const cssText = popupEl.style.cssText || '';
  assert.ok(
    /position\s*:\s*fixed/.test(cssText),
    `Expected "position: fixed" in popup style, got: ${cssText}`,
  );
});

test('popup position uses viewport-safe slot values (top/bottom within 0-100%)', () => {
  const parent = makeParent();
  const instance = new NewsImagePopup(parent);
  instance.show({ image_url: 'https://example.com/img.jpg', title: 'Slot test' });

  const popupEl = parent.children[0];
  const cssText = popupEl.style.cssText || '';

  // Extract first % value found in top/bottom/left/right declarations
  const pctMatches = cssText.match(/(?:top|bottom|left|right)\s*:\s*(-?[\d.]+)%/g) || [];
  pctMatches.forEach(decl => {
    const val = parseFloat(decl.match(/-?[\d.]+/)[0]);
    assert.ok(
      val >= 0 && val <= 100,
      `Off-screen slot value detected: "${decl}" — value ${val}% is outside viewport`,
    );
  });
});

// ─── Suite: 3 popups in 3 corners ─────────────────────────────────────────

console.log('\n3 concurrent popups in 3 corners (AC: 3 visible corners)');

test('3 popups use 3 distinct slot positions', () => {
  const parent = makeParent();
  const instance = new NewsImagePopup(parent);

  instance.show({ image_url: 'https://a.com/1.jpg', title: 'Article 1' });
  instance.show({ image_url: 'https://a.com/2.jpg', title: 'Article 2' });
  instance.show({ image_url: 'https://a.com/3.jpg', title: 'Article 3' });

  assert.strictEqual(parent.children.length, 3, 'Expected 3 popups appended');

  // Extract position fingerprint: first top/left/bottom/right combo
  const posFingerprints = parent.children.map(el => {
    const css = el.style.cssText || '';
    const top    = (css.match(/top\s*:\s*([^;]+)/)    || [])[1] || '';
    const bottom = (css.match(/bottom\s*:\s*([^;]+)/) || [])[1] || '';
    const left   = (css.match(/left\s*:\s*([^;]+)/)   || [])[1] || '';
    const right  = (css.match(/right\s*:\s*([^;]+)/)  || [])[1] || '';
    return `${top.trim()}|${bottom.trim()}|${left.trim()}|${right.trim()}`;
  });

  const unique = new Set(posFingerprints);
  assert.strictEqual(unique.size, 3, `Expected 3 unique positions, got: ${JSON.stringify([...unique])}`);
});

test('4th popup replaces oldest (FIFO) keeping max 3', () => {
  const parent = makeParent();
  const instance = new NewsImagePopup(parent);

  for (let i = 1; i <= 4; i++) {
    instance.show({ image_url: `https://a.com/${i}.jpg`, title: `Article ${i}` });
  }

  // _popups is the authoritative count (parent.children may retain
  // dismissed elements until the async fade-out setTimeout fires,
  // which is a no-op in our test harness).
  assert.ok(
    instance._popups.length <= 3,
    `Expected ≤3 active popups in _popups, got ${instance._popups.length}`,
  );
});

// ─── Suite: loading placeholder → image visible ─────────────────────────────

console.log('\nLoading placeholder (AC: yükleniyor replaced after load)');

test('skeleton placeholder present before image loads', () => {
  const parent = makeParent();
  const instance = new NewsImagePopup(parent);
  instance.show({ image_url: 'https://a.com/img.jpg', title: 'Test' });

  const popupEl = parent.children[0];
  const imgContainer = popupEl.children.find(c => c.className === 'news-image-container');
  assert.ok(imgContainer, 'Expected news-image-container child');

  const skeleton = imgContainer.children.find(c => c.className === 'news-image-skeleton');
  assert.ok(skeleton, 'Expected skeleton placeholder');
  assert.ok(
    skeleton.textContent.includes('yükleniyor'),
    `Expected "yükleniyor" in skeleton text, got: "${skeleton.textContent}"`,
  );
});

test('skeleton hidden after image onload fires', () => {
  const parent = makeParent();
  const instance = new NewsImagePopup(parent);
  instance.show({ image_url: 'https://a.com/img.jpg', title: 'Test' });

  const popupEl = parent.children[0];
  const imgContainer = popupEl.children.find(c => c.className === 'news-image-container');
  const skeleton = imgContainer.children.find(c => c.className === 'news-image-skeleton');
  const img = imgContainer.children.find(c => c.tagName === 'IMG');

  assert.ok(img, 'Expected img element');
  // Initially hidden
  assert.strictEqual(img.style.display, 'none', 'img should be hidden before load');

  // Fire onload
  if (img.onload) img.onload();

  assert.strictEqual(img.style.display, 'block', 'img should be visible after onload');
  assert.strictEqual(skeleton.style.display, 'none', 'skeleton should be hidden after onload');
});

test('onerror shows error placeholder (no hard-fail)', () => {
  const parent = makeParent();
  const instance = new NewsImagePopup(parent);
  instance.show({ image_url: 'https://a.com/broken.jpg', title: 'Test' });

  const popupEl = parent.children[0];
  const imgContainer = popupEl.children.find(c => c.className === 'news-image-container');
  const skeleton = imgContainer.children.find(c => c.className === 'news-image-skeleton');
  const img = imgContainer.children.find(c => c.tagName === 'IMG');

  // Fire onerror
  if (img.onerror) img.onerror();

  assert.ok(
    skeleton.textContent.length > 0,
    'Skeleton should show error placeholder text',
  );
  // img should remain (not crash)
});

// ─── Suite: Electron lazy-loading not used ─────────────────────────────────

console.log('\nElectron loading=lazy not set (AC: images load immediately)');

test('img.loading is NOT set to "lazy"', () => {
  const parent = makeParent();
  const instance = new NewsImagePopup(parent);
  instance.show({ image_url: 'https://a.com/img.jpg', title: 'Test' });

  const popupEl = parent.children[0];
  const imgContainer = popupEl.children.find(c => c.className === 'news-image-container');
  const img = imgContainer.children.find(c => c.tagName === 'IMG');

  assert.ok(img, 'Expected img element');
  assert.notStrictEqual(
    img.loading,
    'lazy',
    'img.loading must NOT be "lazy" — Electron IntersectionObserver unreliable',
  );
  // Also check source: must not SET loading=lazy (comments are OK, actual assignment is not)
  const loadingLazySet = /img\.loading\s*=\s*['"]lazy['"]/.test(popupSrc);
  assert.ok(
    !loadingLazySet,
    'Source must not assign img.loading = "lazy"',
  );
});

// ─── Suite: dispose / clear ────────────────────────────────────────────────

console.log('\ndispose / clear');

test('clear() removes all popup children from parent', () => {
  const parent = makeParent();
  const instance = new NewsImagePopup(parent);

  instance.show({ image_url: 'https://a.com/1.jpg' });
  instance.show({ image_url: 'https://a.com/2.jpg' });
  assert.ok(parent.children.length > 0, 'Popups should be appended');

  instance.clear();
  // After fade-out (synchronous in our mock — setTimeout is no-op)
  // _popups array should be empty
  assert.strictEqual(instance._popups.length, 0, '_popups should be cleared');
});

test('dispose() does not throw', () => {
  const parent = makeParent();
  const instance = new NewsImagePopup(parent);
  instance.show({ image_url: 'https://a.com/img.jpg' });
  assert.doesNotThrow(() => instance.dispose());
});

// ─── Suite: show() with no image_url ──────────────────────────────────────

console.log('\nEdge cases');

test('show() with no image_url does not throw', () => {
  const parent = makeParent();
  const instance = new NewsImagePopup(parent);
  assert.doesNotThrow(() => instance.show({ title: 'No image' }));
  assert.strictEqual(parent.children.length, 0, 'No popup appended when no image');
});

test('show() with multiple image_urls shows up to maxConcurrent', () => {
  const parent = makeParent();
  const instance = new NewsImagePopup(parent);
  instance.show({
    image_urls: [
      'https://a.com/1.jpg',
      'https://a.com/2.jpg',
      'https://a.com/3.jpg',
      'https://a.com/4.jpg', // exceeds maxConcurrent=3
    ],
    title: 'Multi-image article',
  });
  assert.ok(parent.children.length <= 3, `Expected ≤3 popups, got ${parent.children.length}`);
});

test('caption truncated at captionMaxChars (90 chars)', () => {
  const parent = makeParent();
  const instance = new NewsImagePopup(parent);
  const longTitle = 'A'.repeat(150);
  instance.show({ image_url: 'https://a.com/img.jpg', title: longTitle });

  const popupEl = parent.children[0];
  const caption = popupEl.children.find(c => c.className === 'news-image-caption');
  assert.ok(caption, 'Expected caption element');
  assert.ok(caption.textContent.length <= 91, `Caption too long: ${caption.textContent.length}`); // 90 + ellipsis
  assert.ok(caption.textContent.endsWith('…'), 'Long caption should end with ellipsis');
});

// ─── Summary ──────────────────────────────────────────────────────────────

console.log(`\n${'─'.repeat(50)}`);
console.log(`  ${passed} passed, ${failed} failed`);

if (failures.length > 0) {
  console.error('\nFailed tests:');
  failures.forEach(({ name, err }) => console.error(`  • ${name}\n    ${err.message}`));
  process.exit(1);
}

console.log('  All tests passed ✓');

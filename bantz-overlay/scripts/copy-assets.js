#!/usr/bin/env node
/**
 * copy-assets.js — Boot Logo Asset Pipeline
 *
 * Issue #1464: Overlay boot logo & asset pipeline standardizasyonu
 *
 * Copies logo files from the canonical source directory (bantz-overlay/assets/)
 * to the renderer assets directory (bantz-overlay/src/renderer/assets/).
 *
 * Also generates a @2x symlink/copy for HiDPI displays.
 *
 * Run:
 *   node scripts/copy-assets.js
 *   npm run copy-assets
 *
 * Called automatically via prebuild / prestart / predev hooks.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const SRC_DIR = path.join(ROOT, 'assets');
const DEST_DIR = path.join(ROOT, 'src', 'renderer', 'assets');

// Assets to copy: [source filename, dest filename]
const ASSETS = [
  // Primary boot logo (transparent background)
  ['bantz_no_bg_KEEP_SMILE_CLEAN.png', 'bantz_no_bg_KEEP_SMILE_CLEAN.png'],
  // 2x HiDPI alias (source is 1600px — sufficient for @2x at 800px display size)
  ['bantz_no_bg_KEEP_SMILE_CLEAN.png', 'bantz_no_bg_KEEP_SMILE_CLEAN@2x.png'],
  // Fallback / tray icon source
  ['bantz.png', 'bantz.png'],
];

// ─── Ensure destination directory exists ─────────────────────────────────────
if (!fs.existsSync(DEST_DIR)) {
  fs.mkdirSync(DEST_DIR, { recursive: true });
  console.log(`[copy-assets] Created: ${path.relative(ROOT, DEST_DIR)}`);
}

// ─── Copy assets ─────────────────────────────────────────────────────────────
let copied = 0;
let skipped = 0;
let errors = 0;

for (const [srcFile, destFile] of ASSETS) {
  const srcPath = path.join(SRC_DIR, srcFile);
  const destPath = path.join(DEST_DIR, destFile);

  // Verify source exists
  if (!fs.existsSync(srcPath)) {
    console.warn(`[copy-assets] WARN: Source not found: ${path.relative(ROOT, srcPath)}`);
    errors++;
    continue;
  }

  // Check if dest is already up-to-date (same mtime)
  try {
    const srcStat = fs.statSync(srcPath);
    const destStat = fs.existsSync(destPath) ? fs.statSync(destPath) : null;

    if (destStat && srcStat.mtimeMs <= destStat.mtimeMs && srcStat.size === destStat.size) {
      console.log(`[copy-assets] OK (up-to-date): ${destFile}`);
      skipped++;
      continue;
    }
  } catch (_) {
    // If stat fails, proceed with copy
  }

  // Copy file
  try {
    fs.copyFileSync(srcPath, destPath);
    console.log(`[copy-assets] Copied: ${path.relative(ROOT, srcPath)} → ${path.relative(ROOT, destPath)}`);
    copied++;
  } catch (err) {
    console.error(`[copy-assets] ERROR copying ${srcFile}: ${err.message}`);
    errors++;
  }
}

// ─── Summary ─────────────────────────────────────────────────────────────────
console.log(`[copy-assets] Done — ${copied} copied, ${skipped} up-to-date, ${errors} errors`);

if (errors > 0) {
  console.warn('[copy-assets] WARNING: Some assets failed to copy. Boot logo fallback will be used.');
  // Do NOT exit(1) — failing here must not block the dev server startup.
  // The renderer has an onerror fallback for missing logos.
}

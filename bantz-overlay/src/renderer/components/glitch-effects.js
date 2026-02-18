/**
 * Bantz Overlay — Glitch Effects Controller (#1411)
 *
 * Manages retro-futuristic visual effects:
 * - CRT scanlines (CSS repeating-linear-gradient)
 * - Chromatic aberration (RGB offset text-shadow, on state transitions)
 * - Flicker (random brightness dip, irregular timing)
 * - Screen noise (CSS grain overlay)
 *
 * All effects are CSS-driven — no JS animation loops.
 * Individual + master toggle. Intensity presets: subtle / moderate / intense.
 * Respects `prefers-reduced-motion`.
 */

'use strict';

// ── Intensity Presets ─────────────────────────────────────────────
const INTENSITY_PRESETS = {
  subtle: {
    crtOpacity:       0.03,
    flickerOpacity:   0.01,
    noiseOpacity:     0.015,
    chromaticShift:   1,      // px
    chromaticAlpha:   0.2,
    flickerFrequency: 12,     // seconds per cycle (less frequent)
  },
  moderate: {
    crtOpacity:       0.05,
    flickerOpacity:   0.02,
    noiseOpacity:     0.025,
    chromaticShift:   2,
    chromaticAlpha:   0.3,
    flickerFrequency: 8,
  },
  intense: {
    crtOpacity:       0.08,
    flickerOpacity:   0.035,
    noiseOpacity:     0.04,
    chromaticShift:   3,
    chromaticAlpha:   0.4,
    flickerFrequency: 5,
  },
};

// ── Default Settings ──────────────────────────────────────────────
const DEFAULT_SETTINGS = {
  enabled:      true,
  intensity:    'moderate',
  scanlines:    true,
  chromatic:    true,
  flicker:      true,
  noise:        true,
};

class GlitchEffects {
  /**
   * @param {HTMLElement} hudPanel — The main HUD panel element
   */
  constructor(hudPanel) {
    this._hud = hudPanel;
    this._settings = { ...DEFAULT_SETTINGS };
    this._noiseOverlay = null;
    this._chromaticTimer = null;
    this._flickerTimer = null;
    this._reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Listen for reduced-motion changes
    window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', (e) => {
      this._reducedMotion = e.matches;
      this._applyAll();
    });

    this._createNoiseOverlay();
    this._applyAll();
    this._startRandomFlicker();

    console.log('[GlitchEffects] Initialized — intensity:', this._settings.intensity);
  }

  // ── Public API ────────────────────────────────────────────────

  /** Master toggle */
  setEnabled(enabled) {
    this._settings.enabled = !!enabled;
    this._applyAll();
  }

  /** Toggle individual effect */
  toggle(effect, enabled) {
    if (effect in this._settings && effect !== 'enabled' && effect !== 'intensity') {
      this._settings[effect] = typeof enabled === 'boolean' ? enabled : !this._settings[effect];
      this._applyAll();
    }
  }

  /** Set intensity preset: 'subtle' | 'moderate' | 'intense' */
  setIntensity(level) {
    if (INTENSITY_PRESETS[level]) {
      this._settings.intensity = level;
      this._applyAll();
    }
  }

  /** Get current settings (readonly copy) */
  getSettings() {
    return { ...this._settings };
  }

  /**
   * Trigger chromatic aberration flash (called on state transitions).
   * @param {'normal'|'intense'} mode — 'intense' for thinking state
   */
  triggerChromatic(mode = 'normal') {
    if (!this._isEffectActive('chromatic')) return;

    const preset = this._getPreset();
    const shift = mode === 'intense' ? preset.chromaticShift * 2 : preset.chromaticShift;
    const alpha = mode === 'intense' ? Math.min(preset.chromaticAlpha * 1.5, 0.6) : preset.chromaticAlpha;
    const duration = mode === 'intense' ? 800 : 500;

    // Set CSS custom properties for the animation
    this._hud.style.setProperty('--ca-shift', `${shift}px`);
    this._hud.style.setProperty('--ca-alpha', alpha);
    this._hud.style.setProperty('--ca-duration', `${duration}ms`);

    // Remove and re-add class to restart animation
    this._hud.classList.remove('chromatic-flash');
    // Force reflow to restart animation
    void this._hud.offsetWidth;
    this._hud.classList.add('chromatic-flash');

    // Clean up after animation ends
    clearTimeout(this._chromaticTimer);
    this._chromaticTimer = setTimeout(() => {
      this._hud.classList.remove('chromatic-flash');
    }, duration + 50);
  }

  /**
   * Trigger a brief intense flicker (e.g. on wake state).
   */
  triggerWakeFlicker() {
    if (!this._isEffectActive('flicker')) return;

    this._hud.classList.add('wake-flicker');
    setTimeout(() => {
      this._hud.classList.remove('wake-flicker');
    }, 150);
  }

  /** Cleanup */
  destroy() {
    clearTimeout(this._chromaticTimer);
    clearTimeout(this._flickerTimer);
    if (this._noiseOverlay && this._noiseOverlay.parentNode) {
      this._noiseOverlay.parentNode.removeChild(this._noiseOverlay);
    }
  }

  // ── Internal ──────────────────────────────────────────────────

  _getPreset() {
    return INTENSITY_PRESETS[this._settings.intensity] || INTENSITY_PRESETS.moderate;
  }

  _isEffectActive(effect) {
    return this._settings.enabled && this._settings[effect] && !this._reducedMotion;
  }

  _applyAll() {
    const root = document.documentElement;
    const preset = this._getPreset();
    const disabled = !this._settings.enabled || this._reducedMotion;

    // ── Scanlines ──
    root.style.setProperty(
      '--crt-opacity',
      disabled || !this._settings.scanlines ? '0' : String(preset.crtOpacity)
    );

    // ── Flicker ──
    root.style.setProperty(
      '--crt-flicker-opacity',
      disabled || !this._settings.flicker ? '0' : String(preset.flickerOpacity)
    );
    root.style.setProperty(
      '--crt-flicker-duration',
      `${preset.flickerFrequency}s`
    );

    // ── Noise overlay ──
    if (this._noiseOverlay) {
      this._noiseOverlay.style.opacity =
        disabled || !this._settings.noise ? '0' : String(preset.noiseOpacity);
    }

    // ── Chromatic aberration base values ──
    root.style.setProperty('--ca-shift', `${preset.chromaticShift}px`);
    root.style.setProperty('--ca-alpha', String(preset.chromaticAlpha));

    // Restart random flicker timing
    this._startRandomFlicker();
  }

  /**
   * Create a noise overlay element using CSS-generated grain.
   * Uses a tiny SVG filter for performance.
   */
  _createNoiseOverlay() {
    // Create SVG noise filter inline
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('width', '0');
    svg.setAttribute('height', '0');
    svg.style.position = 'absolute';
    svg.innerHTML = `
      <filter id="bantz-noise">
        <feTurbulence type="fractalNoise" baseFrequency="0.65" numOctaves="3" stitchTiles="stitch"/>
        <feColorMatrix type="saturate" values="0"/>
      </filter>
    `;
    document.body.appendChild(svg);

    // Create overlay div with the noise filter
    const overlay = document.createElement('div');
    overlay.className = 'glitch-noise-overlay';
    overlay.style.cssText = `
      position: absolute;
      inset: 0;
      border-radius: var(--radius-hud);
      pointer-events: none;
      z-index: 998;
      filter: url(#bantz-noise);
      opacity: ${this._getPreset().noiseOpacity};
      mix-blend-mode: overlay;
      width: 100%;
      height: 100%;
    `;
    this._hud.appendChild(overlay);
    this._noiseOverlay = overlay;
  }

  /**
   * Start random subtle flicker at irregular intervals.
   * 1-3 flickers per 10 seconds, CSS-driven via class toggle.
   */
  _startRandomFlicker() {
    clearTimeout(this._flickerTimer);
    if (!this._isEffectActive('flicker')) return;

    const scheduleNext = () => {
      // Random interval: 3-10 seconds between flickers
      const delay = 3000 + Math.random() * 7000;
      this._flickerTimer = setTimeout(() => {
        if (!this._isEffectActive('flicker')) return;

        this._hud.classList.add('random-flicker');
        setTimeout(() => {
          this._hud.classList.remove('random-flicker');
        }, 80 + Math.random() * 60); // 80-140ms flicker

        scheduleNext();
      }, delay);
    };

    scheduleNext();
  }
}

// Expose globally
window.GlitchEffects = GlitchEffects;

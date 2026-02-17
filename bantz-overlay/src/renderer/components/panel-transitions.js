/**
 * Bantz Overlay — Panel Transitions & Animation Choreography (#1413)
 *
 * Smooth animated transitions for panel appearance, dismissal,
 * and state changes. Panels materialize with staggered timing
 * during the boot sequence.
 *
 * Features:
 * - Slide-in/out from overflow edge + fade (GPU-accelerated)
 * - Staggered boot sequence (~2s total)
 * - CRT power-off dismiss effect (optional)
 * - State transition choreography
 * - Configurable speed multiplier (0.5x, 1x, 2x)
 * - Respects prefers-reduced-motion
 *
 * @module panel-transitions
 */

'use strict';

// ── Transition Config ─────────────────────────────────────────────
const TRANSITION_CONFIG = {
  appearDuration:   300,   // ms
  dismissDuration:  250,   // ms
  staggerDelay:     100,   // ms between panels during boot
  borderFlashMs:    400,   // green border flash on appear
  crtPowerOffMs:    300,   // CRT vertical collapse duration
  speedMultiplier:  1.0,   // 0.5 = slow, 1.0 = normal, 2.0 = fast
};

/**
 * Slide directions per slot (where panels come from).
 */
const SLIDE_VECTORS = {
  left:         { x: -60, y: 0 },
  right:        { x: 60, y: 0 },
  'bottom-left': { x: -40, y: 40 },
  'top-float':  { x: 0, y: -30 },
};

/**
 * Boot sequence order:
 * agenda (daily-tasks) → news (news-feed) → weather (system-status) → sphere
 */
const BOOT_ORDER = [
  'daily-tasks',
  'news-feed',
  'system-status',
  '__sphere__',    // Special: sphere materializes last
];

class PanelTransitions {
  /**
   * @param {HTMLElement} hudPanel — Main HUD panel
   * @param {object}      [config] — Override defaults
   */
  constructor(hudPanel, config = {}) {
    this._hud = hudPanel;
    this._config = { ...TRANSITION_CONFIG, ...config };
    this._reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this._bootPlayed = false;

    window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', (e) => {
      this._reducedMotion = e.matches;
    });

    console.log('[PanelTransitions] Initialized — speed:', this._config.speedMultiplier);
  }

  // ── Public API ────────────────────────────────────────────────

  /**
   * Set animation speed multiplier.
   * @param {number} mult — 0.5, 1.0, or 2.0
   */
  setSpeed(mult) {
    if ([0.5, 1, 2].includes(mult)) {
      this._config.speedMultiplier = mult;
    }
  }

  /**
   * Get effective duration after speed multiplier.
   * @param {number} baseMs
   * @returns {number}
   */
  _dur(baseMs) {
    if (this._reducedMotion) return 0;
    return Math.round(baseMs / this._config.speedMultiplier);
  }

  /**
   * Animate a panel appearing from its slot direction.
   *
   * @param {HTMLElement} el    — Panel element
   * @param {string}      slot  — Slot name (left/right/bottom-left/top-float)
   * @returns {Promise<void>}   — Resolves when animation completes
   */
  appear(el, slot) {
    return new Promise((resolve) => {
      const dur = this._dur(this._config.appearDuration);
      const vec = SLIDE_VECTORS[slot] || { x: 0, y: 0 };

      if (dur === 0) {
        el.style.opacity = '1';
        el.style.transform = '';
        el.style.display = 'flex';
        resolve();
        return;
      }

      // Start state: shifted + transparent
      el.style.transition = 'none';
      el.style.transform = `translate(${vec.x}px, ${vec.y}px)`;
      el.style.opacity = '0';
      el.style.display = 'flex';

      // Force reflow
      void el.offsetHeight;

      // Animate to final position
      el.style.transition = `transform ${dur}ms ease-out, opacity ${dur}ms ease-out`;
      el.style.transform = 'translate(0, 0)';
      el.style.opacity = '1';

      // Green border flash on appear
      this._borderFlash(el);

      setTimeout(() => {
        el.style.transition = '';
        el.style.transform = '';
        resolve();
      }, dur + 20);
    });
  }

  /**
   * Animate a panel dismissing toward its slot direction.
   *
   * @param {HTMLElement} el     — Panel element
   * @param {string}      slot   — Slot name
   * @param {boolean}     [crtEffect=false] — Use CRT power-off effect
   * @returns {Promise<void>}
   */
  dismiss(el, slot, crtEffect = false) {
    return new Promise((resolve) => {
      if (crtEffect) {
        return this._crtPowerOff(el).then(resolve);
      }

      const dur = this._dur(this._config.dismissDuration);
      const vec = SLIDE_VECTORS[slot] || { x: 0, y: 0 };

      if (dur === 0) {
        el.style.display = 'none';
        resolve();
        return;
      }

      el.style.transition = `transform ${dur}ms ease-in, opacity ${dur}ms ease-in`;
      el.style.transform = `translate(${vec.x}px, ${vec.y}px)`;
      el.style.opacity = '0';

      setTimeout(() => {
        el.style.display = 'none';
        el.style.transition = '';
        el.style.transform = '';
        el.style.opacity = '';
        resolve();
      }, dur + 20);
    });
  }

  /**
   * Play the full boot sequence: panels appear one by one,
   * sphere materializes last.
   *
   * @param {object} components — { 'daily-tasks': panel, 'news-feed': panel, ... }
   * @param {object} [sphere]   — ParticleSphere instance (for scatter animation)
   * @returns {Promise<void>}
   */
  async playBootSequence(components, sphere = null) {
    if (this._bootPlayed) return;
    this._bootPlayed = true;

    const stagger = this._dur(this._config.staggerDelay);

    for (const id of BOOT_ORDER) {
      if (id === '__sphere__') {
        // Sphere materializes last
        if (sphere) {
          await this._materializeSphere(sphere);
        }
        continue;
      }

      const panel = components[id];
      if (!panel) continue;

      const el = panel.element || panel._element;
      const slot = panel.slot || 'right';

      if (el) {
        await this.appear(el, slot);
        if (stagger > 0) {
          await this._delay(stagger);
        }
      }
    }

    console.log('[PanelTransitions] Boot sequence complete');
  }

  /**
   * Choreograph state transitions.
   * Call this from the state handler in renderer.js.
   *
   * @param {string} fromState — Previous state
   * @param {string} toState   — New state
   * @param {object} ctx       — { stateAnimator, typewriter, reasoningChain, glitchEffects }
   */
  choreographStateChange(fromState, toState, ctx) {
    const dur = this._dur(200);

    switch (`${fromState}->${toState}`) {
      case 'idle->listening':
        // Sphere pulses (handled by SphereStateAnimator)
        // Typewriter cursor brightens
        if (ctx.typewriter) {
          this._animateElement(
            ctx.typewriter._container || document.getElementById('typewriter-output'),
            { opacity: '0.6' },
            { opacity: '1' },
            dur
          );
        }
        break;

      case 'listening->thinking':
        // Sphere spins up (handled by SphereStateAnimator)
        // Reasoning text fades in
        if (ctx.reasoningChain) {
          const el = document.getElementById('reasoning-chain');
          if (el) {
            this._animateElement(el, { opacity: '0' }, { opacity: '1' }, dur);
          }
        }
        break;

      case 'thinking->speaking':
        // Reasoning fades out, typewriter begins
        if (ctx.reasoningChain) {
          const el = document.getElementById('reasoning-chain');
          if (el) {
            this._animateElement(el, { opacity: '1' }, { opacity: '0' }, dur);
          }
        }
        break;

      case 'speaking->idle':
        // Speech dims, sphere calms
        if (ctx.typewriter) {
          const el = ctx.typewriter._container || document.getElementById('typewriter-output');
          if (el) {
            this._animateElement(el, { opacity: '1' }, { opacity: '0.4' }, this._dur(600));
          }
        }
        break;
    }
  }

  /**
   * Reset boot state (allows replay).
   */
  resetBoot() {
    this._bootPlayed = false;
  }

  // ── Internal Effects ──────────────────────────────────────────

  /**
   * Brief green border flash (scanline appear effect).
   * @param {HTMLElement} el
   * @private
   */
  _borderFlash(el) {
    const dur = this._dur(this._config.borderFlashMs);
    if (dur === 0) return;

    const original = el.style.borderColor;
    el.style.borderColor = 'rgba(39, 201, 63, 0.6)';
    el.style.boxShadow = '0 0 8px rgba(39, 201, 63, 0.3)';

    setTimeout(() => {
      el.style.transition = `border-color ${dur}ms ease-out, box-shadow ${dur}ms ease-out`;
      el.style.borderColor = original || '';
      el.style.boxShadow = '';
      setTimeout(() => {
        el.style.transition = '';
      }, dur);
    }, 50);
  }

  /**
   * CRT power-off effect: vertical collapse to line, then fade.
   * @param {HTMLElement} el
   * @returns {Promise<void>}
   * @private
   */
  _crtPowerOff(el) {
    return new Promise((resolve) => {
      const dur = this._dur(this._config.crtPowerOffMs);
      if (dur === 0) {
        el.style.display = 'none';
        resolve();
        return;
      }

      // Phase 1: collapse vertically to a thin line
      el.style.transition = `transform ${dur}ms ease-in, opacity ${dur * 0.5}ms ease-in`;
      el.style.transformOrigin = 'center center';
      el.style.transform = 'scaleY(0.02)';

      setTimeout(() => {
        // Phase 2: horizontal collapse + fade
        el.style.transform = 'scaleY(0.02) scaleX(0)';
        el.style.opacity = '0';

        setTimeout(() => {
          el.style.display = 'none';
          el.style.transition = '';
          el.style.transform = '';
          el.style.opacity = '';
          el.style.transformOrigin = '';
          resolve();
        }, dur * 0.5);
      }, dur);
    });
  }

  /**
   * Sphere materialize: brief scatter then reform.
   * @param {object} sphere — ParticleSphere instance
   * @returns {Promise<void>}
   * @private
   */
  _materializeSphere(sphere) {
    return new Promise((resolve) => {
      const dur = this._dur(600);
      if (dur === 0 || !sphere) {
        resolve();
        return;
      }

      // Briefly make sphere invisible then fade in container
      const container = sphere._container || document.getElementById('sphere-container');
      if (container) {
        container.style.transition = `opacity ${dur}ms ease-out`;
        container.style.opacity = '0';

        // Force reflow
        void container.offsetHeight;

        container.style.opacity = '1';

        setTimeout(() => {
          container.style.transition = '';
          resolve();
        }, dur);
      } else {
        resolve();
      }
    });
  }

  /**
   * Animate element from one style to another.
   * @param {HTMLElement} el
   * @param {object} from — CSS props
   * @param {object} to — CSS props
   * @param {number} dur — ms
   * @private
   */
  _animateElement(el, from, to, dur) {
    if (!el || dur === 0) return;

    Object.assign(el.style, from);
    void el.offsetHeight;

    const props = Object.keys(to).map(p => p.replace(/([A-Z])/g, '-$1').toLowerCase());
    el.style.transition = props.map(p => `${p} ${dur}ms ease-out`).join(', ');
    Object.assign(el.style, to);

    setTimeout(() => {
      el.style.transition = '';
    }, dur + 20);
  }

  /**
   * Promise-based delay.
   * @param {number} ms
   * @returns {Promise<void>}
   * @private
   */
  _delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

// ── Expose globally ───────────────────────────────────────────────
window.PanelTransitions = PanelTransitions;

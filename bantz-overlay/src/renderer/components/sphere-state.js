/**
 * Bantz Overlay — Sphere State Animations
 *
 * Manages visual state of the particle sphere based on assistant state:
 * idle, wake, listening, thinking, speaking.
 *
 * Architecture:
 * - Registers as a plugin on ParticleSphere (update() called each frame)
 * - Uses smooth lerp transitions between states (300ms)
 * - Each state has its own animation function
 * - Exposed via sphere.setState() convenience API
 *
 * @module sphere-state
 */

import * as THREE from '../vendor/three.min.js';

// ─── State Enum ─────────────────────────────────────────────────
const SphereState = Object.freeze({
  IDLE: 'idle',
  WAKE: 'wake',
  LISTENING: 'listening',
  THINKING: 'thinking',
  SPEAKING: 'speaking',
});

// ─── Configuration ──────────────────────────────────────────────
const STATE_CONFIG = {
  transitionDuration: 300,      // ms for state transitions
  idle: {
    rotationSpeed: 0.002,
    scale: 1.0,
    particleSize: 2.0,
    opacity: 0.85,
  },
  wake: {
    duration: 500,               // ms for wake flash
    flashScale: 1.15,
    flashOpacity: 1.0,
    flashSize: 3.5,
  },
  listening: {
    rotationSpeed: 0.002,
    pulseAmplitude: 0.05,        // scale oscillation (1.0 ↔ 1.05)
    pulsePeriod: 2000,           // ms per pulse cycle
    particleSize: 2.4,
    opacity: 0.9,
  },
  thinking: {
    rotationSpeed: 0.010,        // 5x idle
    colorShiftSpeed: 3.0,        // color oscillation speed
    particleSize: 2.0,
    opacity: 0.9,
  },
  speaking: {
    rotationSpeed: 0.003,
    waveSpeed: 4.0,              // radial wave speed
    waveAmplitude: 8.0,          // base wave amplitude (modulated by volume)
    waveFrequency: 0.08,         // spatial frequency
    particleSize: 2.2,
    opacity: 0.9,
  },
};

/**
 * SphereStateAnimator — plugin for ParticleSphere.
 */
class SphereStateAnimator {
  /**
   * @param {import('./particle-sphere.js').ParticleSphere} sphere
   */
  constructor(sphere) {
    this._sphere = sphere;

    // State machine
    this._currentState = SphereState.IDLE;
    this._previousState = SphereState.IDLE;
    this._transitionStart = 0;
    this._transitionProgress = 1; // 1 = fully transitioned

    // Timing
    this._startTime = performance.now();
    this._wakeStartTime = 0;
    this._wakeCompleted = false;

    // Colors
    this._baseCyan = new THREE.Color(0x00e5ff);
    this._white = new THREE.Color(0xffffff);
    this._dimCyan = new THREE.Color(0x006688);

    // Speaking volume (set externally via setVolume)
    this._volume = 0;

    // Cache original colors for restore
    const colors = sphere.geometry.getAttribute('color');
    this._originalColors = new Float32Array(colors.array);

    console.log('[SphereState] Animator initialized');
  }

  // ─── Public API ───────────────────────────────────────────────

  /**
   * Get current state.
   * @returns {string}
   */
  get state() {
    return this._currentState;
  }

  /**
   * Transition to a new state.
   * @param {string} state - One of SphereState values
   */
  setState(state) {
    if (!Object.values(SphereState).includes(state)) {
      console.warn(`[SphereState] Unknown state: ${state}`);
      return;
    }

    if (state === this._currentState) return;

    this._previousState = this._currentState;
    this._currentState = state;
    this._transitionStart = performance.now();
    this._transitionProgress = 0;

    // Wake-specific init
    if (state === SphereState.WAKE) {
      this._wakeStartTime = performance.now();
      this._wakeCompleted = false;
    }

    console.log(`[SphereState] ${this._previousState} → ${state}`);
  }

  /**
   * Set speaking volume (0-1) for wave amplitude modulation.
   * @param {number} volume
   */
  setVolume(volume) {
    this._volume = Math.max(0, Math.min(1, volume));
  }

  /**
   * Called each frame by the plugin system.
   */
  update() {
    const now = performance.now();
    const elapsed = now - this._startTime;

    // Update transition progress
    if (this._transitionProgress < 1) {
      const dt = now - this._transitionStart;
      this._transitionProgress = Math.min(dt / STATE_CONFIG.transitionDuration, 1);
      // Ease-out cubic
      this._transitionProgress = 1 - Math.pow(1 - this._transitionProgress, 3);
    }

    // Handle wake auto-transition
    if (this._currentState === SphereState.WAKE && !this._wakeCompleted) {
      if (now - this._wakeStartTime > STATE_CONFIG.wake.duration) {
        this._wakeCompleted = true;
        this.setState(SphereState.LISTENING);
        return;
      }
    }

    // Apply current state animation
    switch (this._currentState) {
      case SphereState.IDLE:
        this._animateIdle(elapsed);
        break;
      case SphereState.WAKE:
        this._animateWake(now);
        break;
      case SphereState.LISTENING:
        this._animateListening(elapsed);
        break;
      case SphereState.THINKING:
        this._animateThinking(elapsed);
        break;
      case SphereState.SPEAKING:
        this._animateSpeaking(elapsed);
        break;
    }
  }

  /**
   * Clean up.
   */
  dispose() {
    // Restore original state
    this._applyRotationSpeed(STATE_CONFIG.idle.rotationSpeed);
    this._applyScale(STATE_CONFIG.idle.scale);
    this._restoreColors();
  }

  // ─── State Animations ─────────────────────────────────────────

  /** @private */
  _animateIdle(elapsed) {
    const cfg = STATE_CONFIG.idle;
    const t = this._transitionProgress;

    this._applyRotationSpeed(this._lerp(this._getStateRotation(this._previousState), cfg.rotationSpeed, t));
    this._applyScale(this._lerp(this._getStateScale(this._previousState), cfg.scale, t));
    this._applyParticleSize(this._lerp(this._getStateSize(this._previousState), cfg.particleSize, t));
    this._applyOpacity(this._lerp(this._getStateOpacity(this._previousState), cfg.opacity, t));

    // Restore colors gradually
    if (this._previousState === SphereState.THINKING) {
      this._restoreColorsLerp(t);
    }
  }

  /** @private */
  _animateWake(now) {
    const cfg = STATE_CONFIG.wake;
    const progress = (now - this._wakeStartTime) / cfg.duration;
    const t = Math.min(progress, 1);

    // Flash: quick scale up then back down
    const flashCurve = t < 0.3
      ? t / 0.3  // rise
      : 1 - ((t - 0.3) / 0.7); // fall
    const scale = 1 + (cfg.flashScale - 1) * flashCurve;

    this._applyScale(scale);
    this._applyOpacity(this._lerp(0.85, cfg.flashOpacity, flashCurve));
    this._applyParticleSize(this._lerp(2.0, cfg.flashSize, flashCurve));

    // Brief color flash to white
    this._shiftColorsToWhite(flashCurve * 0.6);
  }

  /** @private */
  _animateListening(elapsed) {
    const cfg = STATE_CONFIG.listening;
    const t = this._transitionProgress;

    // Rotation
    this._applyRotationSpeed(this._lerp(this._getStateRotation(this._previousState), cfg.rotationSpeed, t));

    // Breathing pulse
    const pulse = Math.sin((elapsed / cfg.pulsePeriod) * Math.PI * 2);
    const targetScale = 1 + pulse * cfg.pulseAmplitude;
    const scale = this._lerp(this._getStateScale(this._previousState), targetScale, t);
    this._applyScale(scale);

    // Particle size
    this._applyParticleSize(this._lerp(this._getStateSize(this._previousState), cfg.particleSize, t));
    this._applyOpacity(cfg.opacity);

    // Restore colors if coming from thinking
    if (this._previousState === SphereState.THINKING) {
      this._restoreColorsLerp(t);
    }
  }

  /** @private */
  _animateThinking(elapsed) {
    const cfg = STATE_CONFIG.thinking;
    const t = this._transitionProgress;

    // Fast rotation
    this._applyRotationSpeed(this._lerp(this._getStateRotation(this._previousState), cfg.rotationSpeed, t));
    this._applyScale(1.0);
    this._applyParticleSize(cfg.particleSize);
    this._applyOpacity(cfg.opacity);

    // Color shimmer: cyan ↔ white
    const shimmer = (Math.sin(elapsed * cfg.colorShiftSpeed * 0.001) + 1) / 2;
    this._shiftColorsToWhite(shimmer * 0.5 * t);
  }

  /** @private */
  _animateSpeaking(elapsed) {
    const cfg = STATE_CONFIG.speaking;
    const t = this._transitionProgress;
    const sphere = this._sphere;
    const positions = sphere.geometry.getAttribute('position');
    const original = sphere.originalPositions;
    const count = positions.count;

    // Rotation
    this._applyRotationSpeed(this._lerp(this._getStateRotation(this._previousState), cfg.rotationSpeed, t));
    this._applyParticleSize(cfg.particleSize);
    this._applyOpacity(cfg.opacity);

    // Scale
    this._applyScale(1.0);

    // Radial wave ripple
    const waveTime = elapsed * cfg.waveSpeed * 0.001;
    const amplitude = cfg.waveAmplitude * (0.3 + this._volume * 0.7) * t;

    for (let i = 0; i < count; i++) {
      const i3 = i * 3;
      const ox = original[i3];
      const oy = original[i3 + 1];
      const oz = original[i3 + 2];

      // Distance from center (for radial wave)
      const dist = Math.sqrt(ox * ox + oy * oy + oz * oz);

      // Radial wave displacement
      const wave = Math.sin(dist * cfg.waveFrequency - waveTime) * amplitude;

      // Push outward along normal direction
      const nx = ox / (dist || 1);
      const ny = oy / (dist || 1);
      const nz = oz / (dist || 1);

      positions.array[i3] = ox + nx * wave;
      positions.array[i3 + 1] = oy + ny * wave;
      positions.array[i3 + 2] = oz + nz * wave;
    }

    positions.needsUpdate = true;

    // Restore colors if coming from thinking
    if (this._previousState === SphereState.THINKING) {
      this._restoreColorsLerp(t);
    }
  }

  // ─── Helpers ──────────────────────────────────────────────────

  /** @private */
  _lerp(a, b, t) {
    return a + (b - a) * t;
  }

  /** @private */
  _applyRotationSpeed(speed) {
    this._sphere.rotationSpeed = speed;
  }

  /** @private */
  _applyScale(scale) {
    if (this._sphere.points) {
      this._sphere.points.scale.setScalar(scale);
    }
  }

  /** @private */
  _applyParticleSize(size) {
    if (this._sphere.points && this._sphere.points.material) {
      this._sphere.points.material.size = size;
    }
  }

  /** @private */
  _applyOpacity(opacity) {
    if (this._sphere.points && this._sphere.points.material) {
      this._sphere.points.material.opacity = opacity;
    }
  }

  /** @private — shift vertex colors toward white by factor t (0–1) */
  _shiftColorsToWhite(t) {
    const colors = this._sphere.geometry.getAttribute('color');
    const orig = this._originalColors;

    for (let i = 0; i < colors.count; i++) {
      const i3 = i * 3;
      colors.array[i3] = orig[i3] + (1 - orig[i3]) * t;
      colors.array[i3 + 1] = orig[i3 + 1] + (1 - orig[i3 + 1]) * t;
      colors.array[i3 + 2] = orig[i3 + 2] + (1 - orig[i3 + 2]) * t;
    }
    colors.needsUpdate = true;
  }

  /** @private — restore colors fully */
  _restoreColors() {
    const colors = this._sphere.geometry.getAttribute('color');
    colors.array.set(this._originalColors);
    colors.needsUpdate = true;
  }

  /** @private — partially restore colors by lerp factor t */
  _restoreColorsLerp(t) {
    const colors = this._sphere.geometry.getAttribute('color');
    const orig = this._originalColors;

    for (let i = 0; i < colors.array.length; i++) {
      colors.array[i] = colors.array[i] + (orig[i] - colors.array[i]) * t;
    }
    colors.needsUpdate = true;
  }

  /** @private — get rotation speed for a state (for transition from) */
  _getStateRotation(state) {
    switch (state) {
      case SphereState.THINKING: return STATE_CONFIG.thinking.rotationSpeed;
      case SphereState.SPEAKING: return STATE_CONFIG.speaking.rotationSpeed;
      case SphereState.LISTENING: return STATE_CONFIG.listening.rotationSpeed;
      default: return STATE_CONFIG.idle.rotationSpeed;
    }
  }

  /** @private */
  _getStateScale(state) {
    return 1.0; // Most states use 1.0 as base (listening pulse is dynamic)
  }

  /** @private */
  _getStateSize(state) {
    switch (state) {
      case SphereState.LISTENING: return STATE_CONFIG.listening.particleSize;
      case SphereState.SPEAKING: return STATE_CONFIG.speaking.particleSize;
      default: return STATE_CONFIG.idle.particleSize;
    }
  }

  /** @private */
  _getStateOpacity(state) {
    switch (state) {
      case SphereState.LISTENING:
      case SphereState.THINKING:
      case SphereState.SPEAKING:
        return 0.9;
      default: return STATE_CONFIG.idle.opacity;
    }
  }
}

export { SphereStateAnimator, SphereState, STATE_CONFIG };

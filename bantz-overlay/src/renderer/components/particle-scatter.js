/**
 * Bantz Overlay — Particle Scatter/Dust Effect
 *
 * When the mouse hovers over the particle sphere, nearby particles
 * scatter outward like dust, then slowly reform back to the globe shape.
 *
 * Physics model:
 * - Raycaster projects mouse onto a plane at z=0 in world space
 * - Particles within influence radius get a repulsion force
 * - Force is inversely proportional to distance (stronger when closer)
 * - Spring-back force lerps particles toward original positions
 * - Slight random drift during scatter for organic feel
 * - Opacity dims for scattered particles
 *
 * @module particle-scatter
 */

import * as THREE from '../vendor/three.min.js';

// ─── Configuration ──────────────────────────────────────────────
const SCATTER_CONFIG = {
  influenceRadius: 50,       // world-space radius of mouse influence
  repulsionStrength: 8.0,    // base repulsion force multiplier
  springBack: 0.02,          // lerp factor for returning home (per frame)
  damping: 0.92,             // velocity damping factor
  driftAmount: 0.3,          // random drift during scatter
  scatterOpacityMin: 0.35,   // minimum opacity when fully scattered
  maxDisplacement: 120,      // cap on how far a particle can scatter
};

/**
 * ParticleScatter — mouse hover scatter/dust interaction.
 *
 * Attaches to a ParticleSphere instance and manages scatter physics.
 */
class ParticleScatter {
  /**
   * @param {import('./particle-sphere.js').ParticleSphere} sphere - The sphere instance
   * @param {HTMLElement} container - The container element (for mouse coords)
   */
  constructor(sphere, container) {
    this._sphere = sphere;
    this._container = container;

    // Three.js helpers
    this._raycaster = new THREE.Raycaster();
    this._mouse = new THREE.Vector2(9999, 9999); // offscreen initially
    this._mouseWorld = new THREE.Vector3();
    this._plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);

    // Per-particle velocity buffer
    const count = sphere.geometry.getAttribute('position').count;
    this._velocities = new Float32Array(count * 3);
    this._displacements = new Float32Array(count); // displacement magnitude per particle

    // State
    this._isHovering = false;
    this._enabled = true;

    // Bind methods
    this._onMouseMove = this._onMouseMove.bind(this);
    this._onMouseLeave = this._onMouseLeave.bind(this);
    this._onTouchMove = this._onTouchMove.bind(this);
    this._onTouchEnd = this._onTouchEnd.bind(this);

    this._attachListeners();
  }

  // ─── Public API ───────────────────────────────────────────────

  /**
   * Enable scatter interaction.
   */
  enable() {
    this._enabled = true;
  }

  /**
   * Disable scatter interaction (particles will spring back).
   */
  disable() {
    this._enabled = false;
    this._isHovering = false;
    this._mouse.set(9999, 9999);
  }

  /**
   * Must be called every frame from the animation loop.
   * Updates particle positions based on scatter physics.
   */
  update() {
    const geometry = this._sphere.geometry;
    const positions = geometry.getAttribute('position');
    const original = this._sphere.originalPositions;
    const vel = this._velocities;
    const disp = this._displacements;
    const count = positions.count;

    // Project mouse to world space
    if (this._isHovering && this._enabled) {
      this._raycaster.setFromCamera(this._mouse, this._sphere._camera);
      this._raycaster.ray.intersectPlane(this._plane, this._mouseWorld);
    }

    const mx = this._mouseWorld.x;
    const my = this._mouseWorld.y;
    const mz = this._mouseWorld.z;
    const r2 = SCATTER_CONFIG.influenceRadius * SCATTER_CONFIG.influenceRadius;

    for (let i = 0; i < count; i++) {
      const i3 = i * 3;

      // Current position
      const px = positions.array[i3];
      const py = positions.array[i3 + 1];
      const pz = positions.array[i3 + 2];

      // Original position
      const ox = original[i3];
      const oy = original[i3 + 1];
      const oz = original[i3 + 2];

      // Apply repulsion if hovering
      if (this._isHovering && this._enabled) {
        // Distance from mouse (in XY plane — project sphere rotation)
        const rotatedPos = this._getRotatedPosition(i3);
        const dx = rotatedPos.x - mx;
        const dy = rotatedPos.y - my;
        const dist2 = dx * dx + dy * dy;

        if (dist2 < r2 && dist2 > 0.01) {
          const dist = Math.sqrt(dist2);
          const force = (1 - dist / SCATTER_CONFIG.influenceRadius) * SCATTER_CONFIG.repulsionStrength;

          // Normalized direction away from mouse
          const nx = dx / dist;
          const ny = dy / dist;

          // Add force + random drift
          vel[i3] += nx * force + (Math.random() - 0.5) * SCATTER_CONFIG.driftAmount;
          vel[i3 + 1] += ny * force + (Math.random() - 0.5) * SCATTER_CONFIG.driftAmount;
          vel[i3 + 2] += (Math.random() - 0.5) * SCATTER_CONFIG.driftAmount * 0.5;
        }
      }

      // Apply velocity
      positions.array[i3] += vel[i3];
      positions.array[i3 + 1] += vel[i3 + 1];
      positions.array[i3 + 2] += vel[i3 + 2];

      // Damping
      vel[i3] *= SCATTER_CONFIG.damping;
      vel[i3 + 1] *= SCATTER_CONFIG.damping;
      vel[i3 + 2] *= SCATTER_CONFIG.damping;

      // Spring back to original position
      positions.array[i3] += (ox - positions.array[i3]) * SCATTER_CONFIG.springBack;
      positions.array[i3 + 1] += (oy - positions.array[i3 + 1]) * SCATTER_CONFIG.springBack;
      positions.array[i3 + 2] += (oz - positions.array[i3 + 2]) * SCATTER_CONFIG.springBack;

      // Cap displacement
      const ddx = positions.array[i3] - ox;
      const ddy = positions.array[i3 + 1] - oy;
      const ddz = positions.array[i3 + 2] - oz;
      const dispMag = Math.sqrt(ddx * ddx + ddy * ddy + ddz * ddz);
      disp[i] = dispMag;

      if (dispMag > SCATTER_CONFIG.maxDisplacement) {
        const scale = SCATTER_CONFIG.maxDisplacement / dispMag;
        positions.array[i3] = ox + ddx * scale;
        positions.array[i3 + 1] = oy + ddy * scale;
        positions.array[i3 + 2] = oz + ddz * scale;
      }
    }

    // Update opacity based on average displacement
    this._updateOpacity(disp, count);

    positions.needsUpdate = true;
  }

  /**
   * Clean up event listeners.
   */
  dispose() {
    this._detachListeners();
  }

  // ─── Internal ─────────────────────────────────────────────────

  /**
   * Get the world-space position of a particle accounting for sphere rotation.
   * @private
   */
  _getRotatedPosition(i3) {
    const positions = this._sphere.geometry.getAttribute('position');
    const px = positions.array[i3];
    const py = positions.array[i3 + 1];
    const pz = positions.array[i3 + 2];

    // Apply the sphere's rotation to get screen-space position
    const v = new THREE.Vector3(px, py, pz);
    v.applyQuaternion(this._sphere.points.quaternion);
    return v;
  }

  /**
   * Update material opacity based on scatter state.
   * @private
   */
  _updateOpacity(displacements, count) {
    let maxDisp = 0;
    for (let i = 0; i < count; i++) {
      if (displacements[i] > maxDisp) maxDisp = displacements[i];
    }

    // Scale opacity: fully scattered → dim, at rest → full
    if (maxDisp > 1) {
      const scatterRatio = Math.min(maxDisp / SCATTER_CONFIG.maxDisplacement, 1);
      const opacity = 1 - scatterRatio * (1 - SCATTER_CONFIG.scatterOpacityMin);
      this._sphere.points.material.opacity = Math.max(opacity, SCATTER_CONFIG.scatterOpacityMin);
    } else {
      // Restore to default
      this._sphere.points.material.opacity = 0.85;
    }
  }

  /**
   * Convert DOM mouse coordinates to normalized device coordinates.
   * @private
   */
  _updateMouseNDC(clientX, clientY) {
    const rect = this._container.getBoundingClientRect();
    this._mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    this._mouse.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  }

  // ─── Event Handlers ───────────────────────────────────────────

  /** @private */
  _onMouseMove(e) {
    this._isHovering = true;
    this._updateMouseNDC(e.clientX, e.clientY);
  }

  /** @private */
  _onMouseLeave() {
    this._isHovering = false;
    this._mouse.set(9999, 9999);
  }

  /** @private — touch support */
  _onTouchMove(e) {
    if (e.touches.length > 0) {
      this._isHovering = true;
      this._updateMouseNDC(e.touches[0].clientX, e.touches[0].clientY);
    }
  }

  /** @private */
  _onTouchEnd() {
    this._isHovering = false;
    this._mouse.set(9999, 9999);
  }

  /** @private */
  _attachListeners() {
    this._container.addEventListener('mousemove', this._onMouseMove);
    this._container.addEventListener('mouseleave', this._onMouseLeave);
    this._container.addEventListener('touchmove', this._onTouchMove, { passive: true });
    this._container.addEventListener('touchend', this._onTouchEnd);
  }

  /** @private */
  _detachListeners() {
    this._container.removeEventListener('mousemove', this._onMouseMove);
    this._container.removeEventListener('mouseleave', this._onMouseLeave);
    this._container.removeEventListener('touchmove', this._onTouchMove);
    this._container.removeEventListener('touchend', this._onTouchEnd);
  }
}

export { ParticleScatter, SCATTER_CONFIG };

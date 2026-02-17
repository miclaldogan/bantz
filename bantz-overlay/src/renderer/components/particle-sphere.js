/**
 * Bantz Overlay — Particle Sphere Component
 *
 * A half-open globe of cyan dot particles rendered with Three.js.
 * The sphere rotates slowly in idle state and responds to state changes.
 *
 * Architecture:
 * - Uses Three.js Points with BufferGeometry
 * - Fibonacci sphere distribution for even particle placement
 * - Open hemisphere (no particles at bottom 30%)
 * - Particles are small circular sprites (cyan #00e5ff)
 *
 * @module particle-sphere
 */

import * as THREE from '../vendor/three.min.js';

// ─── Configuration ──────────────────────────────────────────────
const CONFIG = {
  particleCount: 800,
  sphereRadius: 80,
  particleSize: 2.0,
  color: 0x00e5ff,         // Cyan
  colorDim: 0x006688,      // Dimmed cyan for bottom particles
  openRatio: 0.30,         // Bottom 30% open (no particles)
  rotationSpeed: 0.002,    // radians per frame (idle)
  cameraDistance: 250,
};

/**
 * Create a circular particle texture (soft dot).
 * @returns {THREE.Texture}
 */
function createParticleTexture() {
  const size = 32;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');

  // Radial gradient: bright center, soft edges
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, 'rgba(255, 255, 255, 1)');
  gradient.addColorStop(0.3, 'rgba(255, 255, 255, 0.8)');
  gradient.addColorStop(0.7, 'rgba(255, 255, 255, 0.2)');
  gradient.addColorStop(1, 'rgba(255, 255, 255, 0)');

  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return texture;
}

/**
 * Generate Fibonacci sphere points for even distribution.
 * Returns only the upper portion (skipping bottom openRatio).
 *
 * @param {number} count - Total candidate points
 * @param {number} radius - Sphere radius
 * @param {number} openRatio - Fraction of bottom to skip [0,1]
 * @returns {{ positions: Float32Array, colors: Float32Array, count: number }}
 */
function generateSpherePoints(count, radius, openRatio) {
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  const positions = [];
  const colors = [];
  const baseColor = new THREE.Color(CONFIG.color);
  const dimColor = new THREE.Color(CONFIG.colorDim);

  for (let i = 0; i < count; i++) {
    // Fibonacci sphere distribution
    const y = 1 - (i / (count - 1)) * 2; // y from 1 to -1

    // Skip bottom portion (open hemisphere)
    if (y < -(1 - openRatio * 2)) continue;

    const radiusAtY = Math.sqrt(1 - y * y);
    const theta = goldenAngle * i;

    const x = Math.cos(theta) * radiusAtY * radius;
    const z = Math.sin(theta) * radiusAtY * radius;
    const yPos = y * radius;

    positions.push(x, yPos, z);

    // Color gradient: brighter at top, dimmer at bottom
    const t = (y + 1) / 2; // 0 (bottom) to 1 (top)
    const color = baseColor.clone().lerp(dimColor, 1 - t);
    colors.push(color.r, color.g, color.b);
  }

  return {
    positions: new Float32Array(positions),
    colors: new Float32Array(colors),
    count: positions.length / 3,
  };
}

/**
 * Particle Sphere — main component class.
 */
class ParticleSphere {
  /**
   * @param {HTMLElement} container - DOM element to render into
   */
  constructor(container) {
    this._container = container;
    this._width = container.clientWidth || 220;
    this._height = container.clientHeight || 220;

    // Three.js objects
    this._scene = null;
    this._camera = null;
    this._renderer = null;
    this._points = null;
    this._geometry = null;

    // Original positions (for reset after scatter)
    this._originalPositions = null;

    // Animation state
    this._animationId = null;
    this._rotationSpeed = CONFIG.rotationSpeed;
    this._running = false;

    // Plugin system: objects with update() called each frame
    this._plugins = [];

    this._init();
  }

  // ─── Public API ───────────────────────────────────────────────

  /**
   * Start the render loop.
   */
  start() {
    if (this._running) return;
    this._running = true;
    this._animate();
  }

  /**
   * Stop the render loop.
   */
  stop() {
    this._running = false;
    if (this._animationId) {
      cancelAnimationFrame(this._animationId);
      this._animationId = null;
    }
  }

  /**
   * Get the Three.js Points object (for external manipulation).
   * @returns {THREE.Points}
   */
  get points() {
    return this._points;
  }

  /**
   * Get the geometry for direct access to position/color buffers.
   * @returns {THREE.BufferGeometry}
   */
  get geometry() {
    return this._geometry;
  }

  /**
   * Get the original (home) positions array.
   * @returns {Float32Array}
   */
  get originalPositions() {
    return this._originalPositions;
  }

  /**
   * Set rotation speed.
   * @param {number} speed - radians per frame
   */
  set rotationSpeed(speed) {
    this._rotationSpeed = speed;
  }

  /**
   * Resize the renderer to match container.
   */
  resize() {
    this._width = this._container.clientWidth || 220;
    this._height = this._container.clientHeight || 220;
    this._camera.aspect = this._width / this._height;
    this._camera.updateProjectionMatrix();
    this._renderer.setSize(this._width, this._height);
  }

  /**
   * Register a plugin (e.g., ParticleScatter) to be updated each frame.
   * Plugin must have an update() method.
   * @param {{ update: Function, dispose?: Function }} plugin
   */
  addPlugin(plugin) {
    if (plugin && typeof plugin.update === 'function') {
      this._plugins.push(plugin);
    }
  }

  /**
   * Remove a registered plugin.
   * @param {{ update: Function }} plugin
   */
  removePlugin(plugin) {
    const idx = this._plugins.indexOf(plugin);
    if (idx !== -1) this._plugins.splice(idx, 1);
  }

  /**
   * Clean up Three.js resources.
   */
  dispose() {
    this.stop();
    // Dispose plugins
    for (const plugin of this._plugins) {
      if (typeof plugin.dispose === 'function') plugin.dispose();
    }
    this._plugins = [];
    if (this._geometry) this._geometry.dispose();
    if (this._points && this._points.material) this._points.material.dispose();
    if (this._renderer) {
      this._renderer.dispose();
      if (this._renderer.domElement.parentNode) {
        this._renderer.domElement.parentNode.removeChild(this._renderer.domElement);
      }
    }
  }

  // ─── Internal ─────────────────────────────────────────────────

  /**
   * Initialize Three.js scene, camera, renderer, and particles.
   * @private
   */
  _init() {
    // Scene
    this._scene = new THREE.Scene();

    // Camera
    this._camera = new THREE.PerspectiveCamera(
      45,
      this._width / this._height,
      1,
      1000
    );
    this._camera.position.z = CONFIG.cameraDistance;

    // Renderer — transparent background
    this._renderer = new THREE.WebGLRenderer({
      alpha: true,
      antialias: true,
    });
    this._renderer.setSize(this._width, this._height);
    this._renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this._renderer.setClearColor(0x000000, 0);
    this._container.appendChild(this._renderer.domElement);

    // Generate particles
    const { positions, colors, count } = generateSpherePoints(
      CONFIG.particleCount,
      CONFIG.sphereRadius,
      CONFIG.openRatio
    );

    // Store original positions for scatter/reform
    this._originalPositions = new Float32Array(positions);

    // Geometry
    this._geometry = new THREE.BufferGeometry();
    this._geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    this._geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    // Material
    const texture = createParticleTexture();
    const material = new THREE.PointsMaterial({
      size: CONFIG.particleSize,
      map: texture,
      vertexColors: true,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });

    // Points mesh
    this._points = new THREE.Points(this._geometry, material);
    this._scene.add(this._points);

    console.log(`[Sphere] Initialized: ${count} particles`);
  }

  /**
   * Animation loop.
   * @private
   */
  _animate() {
    if (!this._running) return;

    this._animationId = requestAnimationFrame(() => this._animate());

    // Rotate the sphere
    if (this._points) {
      this._points.rotation.y += this._rotationSpeed;
    }

    // Update plugins (scatter, state animations, etc.)
    for (const plugin of this._plugins) {
      plugin.update();
    }

    this._renderer.render(this._scene, this._camera);
  }
}

// Export
export { ParticleSphere, CONFIG as SPHERE_CONFIG };

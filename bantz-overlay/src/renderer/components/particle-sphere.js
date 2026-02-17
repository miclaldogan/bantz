/**
 * Bantz Overlay — Particle Sphere Component
 *
 * A rotating sphere of cyan dot particles rendered with Three.js.
 * Particles are distributed using Fibonacci sphere sampling for
 * even, aesthetically pleasing coverage.
 *
 * Architecture:
 * - Uses Three.js Points with BufferGeometry
 * - Fibonacci spiral distribution for uniform sphere coverage
 * - Larger, more prominent particles with size variation
 * - Interactive: click/hover on sphere surface
 * - State-responsive animation (idle/listening/thinking/speaking)
 *
 * @module particle-sphere
 */

import * as THREE from '../vendor/three.min.js';

// ─── Configuration ──────────────────────────────────────────────
const CONFIG = {
  sphereParticles: 700,    // total sphere surface particles
  sphereRadius: 85,        // radius of the sphere
  particleSize: 4.5,       // base particle size (larger = more prominent)
  particleSizeVariation: 1.5, // random ± size variation
  color: 0x00e5ff,         // Cyan
  colorCore: 0x99ffff,     // Bright cyan for prominent dots
  colorDim: 0x00aacc,      // Dimmer cyan for smaller dots
  rotationSpeed: 0.002,    // radians per frame (idle) — dual axis
  cameraDistance: 240,
  glowColor: 0x00e5ff,
  glowParticleCount: 120,
  glowRadius: 130,
  glowParticleSize: 5.0,
  glowOpacity: 0.12,
  // Breathing/pulse animation
  breatheSpeed: 0.008,     // radians per frame for pulse
  breatheAmplitude: 0.08,  // scale oscillation ±8%
  // Prominent dots (interactive highlights)
  prominentCount: 30,      // number of larger "node" particles
  prominentSize: 7.0,      // size of prominent particles
};

/**
 * Create a circular particle texture (soft dot).
 * @returns {THREE.Texture}
 */
function createParticleTexture() {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');

  // Bright core with wider glow halo
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, 'rgba(255, 255, 255, 1)');
  gradient.addColorStop(0.2, 'rgba(200, 255, 255, 1)');
  gradient.addColorStop(0.4, 'rgba(0, 229, 255, 0.8)');
  gradient.addColorStop(0.6, 'rgba(0, 229, 255, 0.4)');
  gradient.addColorStop(0.8, 'rgba(0, 229, 255, 0.1)');
  gradient.addColorStop(1, 'rgba(0, 229, 255, 0)');

  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return texture;
}

/**
 * Create a soft glow texture for the ambient halo particles.
 * @returns {THREE.Texture}
 */
function createGlowTexture() {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');

  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, 'rgba(0, 229, 255, 0.6)');
  gradient.addColorStop(0.3, 'rgba(0, 229, 255, 0.2)');
  gradient.addColorStop(0.7, 'rgba(0, 180, 220, 0.05)');
  gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');

  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return texture;
}

/**
 * Generate sphere points using Fibonacci sphere distribution.
 * Produces evenly-spaced particles on a sphere surface with
 * prominent "node" particles interspersed.
 *
 * @returns {{ positions: Float32Array, colors: Float32Array, sizes: Float32Array, count: number }}
 */
function generateSpherePoints() {
  const positions = [];
  const colors = [];
  const sizes = [];
  const coreColor = new THREE.Color(CONFIG.colorCore);
  const dimColor = new THREE.Color(CONFIG.colorDim);
  const mainColor = new THREE.Color(CONFIG.color);
  const n = CONFIG.sphereParticles;
  const r = CONFIG.sphereRadius;

  // Golden angle for Fibonacci sphere
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));

  // Indices of prominent particles (evenly distributed)
  const prominentStep = Math.floor(n / CONFIG.prominentCount);
  const prominentSet = new Set();
  for (let i = 0; i < CONFIG.prominentCount; i++) {
    prominentSet.add(i * prominentStep);
  }

  for (let i = 0; i < n; i++) {
    // Fibonacci sphere sampling
    const y = 1 - (i / (n - 1)) * 2; // y goes from 1 to -1
    const radiusAtY = Math.sqrt(1 - y * y);
    const theta = goldenAngle * i;

    const x = Math.cos(theta) * radiusAtY;
    const z = Math.sin(theta) * radiusAtY;

    positions.push(x * r, y * r, z * r);

    if (prominentSet.has(i)) {
      // Prominent node particles — bright, large
      colors.push(coreColor.r, coreColor.g, coreColor.b);
      sizes.push(CONFIG.prominentSize);
    } else {
      // Regular particles — subtle variation
      const brightness = 0.6 + Math.random() * 0.4;
      const c = i % 3 === 0 ? mainColor : dimColor;
      colors.push(c.r * brightness, c.g * brightness, c.b * brightness);
      sizes.push(
        CONFIG.particleSize + (Math.random() - 0.5) * CONFIG.particleSizeVariation
      );
    }
  }

  return {
    positions: new Float32Array(positions),
    colors: new Float32Array(colors),
    sizes: new Float32Array(sizes),
    count: n,
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
    this._breathePhase = 0;
    this._state = 'idle'; // 'idle' | 'listening' | 'thinking' | 'speaking'

    // Plugin system: objects with update() called each frame
    this._plugins = [];

    // Raycaster for click/hover interaction
    this._raycaster = new THREE.Raycaster();
    this._raycaster.params.Points.threshold = 8;
    this._mouse = new THREE.Vector2();

    this._init();
    this._setupInteraction();
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
    const { positions, colors, sizes, count } = generateSpherePoints();

    // Store original positions for scatter/reform
    this._originalPositions = new Float32Array(positions);
    this._originalSizes = new Float32Array(sizes);

    // Geometry
    this._geometry = new THREE.BufferGeometry();
    this._geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    this._geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    this._geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

    // Material — use per-particle size via custom shader or max size
    const texture = createParticleTexture();
    const material = new THREE.PointsMaterial({
      size: CONFIG.particleSize,
      map: texture,
      vertexColors: true,
      transparent: true,
      opacity: 1.0,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });

    // Points mesh
    this._points = new THREE.Points(this._geometry, material);
    this._scene.add(this._points);

    // Ambient glow halo — larger transparent particles around the sphere
    this._initGlowHalo();

    console.log(`[Sphere] Initialized: ${count} particles + glow halo`);
  }

  /**
   * Initialize ambient glow halo around the sphere.
   * @private
   */
  _initGlowHalo() {
    const glowPositions = [];
    const glowColors = [];
    const glowColor = new THREE.Color(CONFIG.glowColor);

    for (let i = 0; i < CONFIG.glowParticleCount; i++) {
      // Random positions in a shell around the sphere
      const phi = Math.acos(2 * Math.random() - 1);
      const theta = Math.random() * Math.PI * 2;
      const r = CONFIG.glowRadius + (Math.random() - 0.5) * 30;

      glowPositions.push(
        r * Math.sin(phi) * Math.cos(theta),
        r * Math.sin(phi) * Math.sin(theta),
        r * Math.cos(phi)
      );
      glowColors.push(glowColor.r, glowColor.g, glowColor.b);
    }

    const glowGeo = new THREE.BufferGeometry();
    glowGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(glowPositions), 3));
    glowGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(glowColors), 3));

    const glowMat = new THREE.PointsMaterial({
      size: CONFIG.glowParticleSize,
      map: createGlowTexture(),
      vertexColors: true,
      transparent: true,
      opacity: CONFIG.glowOpacity,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });

    this._glowPoints = new THREE.Points(glowGeo, glowMat);
    this._scene.add(this._glowPoints);
  }

  /**
   * Animation loop.
   * @private
   */
  _animate() {
    if (!this._running) return;

    this._animationId = requestAnimationFrame(() => this._animate());

    // Rotate the sphere on two axes for interesting motion
    if (this._points) {
      this._points.rotation.y += this._rotationSpeed;
      this._points.rotation.x += this._rotationSpeed * 0.4;
    }

    // Breathing/pulse animation — subtle scale oscillation
    this._breathePhase += CONFIG.breatheSpeed;
    if (this._points) {
      const scale = 1 + Math.sin(this._breathePhase) * CONFIG.breatheAmplitude;
      this._points.scale.setScalar(scale);
    }

    // State-responsive rotation speed
    switch (this._state) {
      case 'listening':
        this._rotationSpeed += (0.006 - this._rotationSpeed) * 0.05;
        break;
      case 'thinking':
        this._rotationSpeed += (0.012 - this._rotationSpeed) * 0.05;
        break;
      case 'speaking':
        this._rotationSpeed += (0.004 - this._rotationSpeed) * 0.05;
        break;
      default: // idle
        this._rotationSpeed += (CONFIG.rotationSpeed - this._rotationSpeed) * 0.05;
    }

    // Counter-rotate glow halo slowly for depth
    if (this._glowPoints) {
      this._glowPoints.rotation.y -= this._rotationSpeed * 0.3;
      this._glowPoints.rotation.x += this._rotationSpeed * 0.1;
    }

    // Update plugins (scatter, state animations, etc.)
    for (const plugin of this._plugins) {
      plugin.update();
    }

    this._renderer.render(this._scene, this._camera);
  }

  /**
   * Set the sphere's animation state.
   * @param {'idle'|'listening'|'thinking'|'speaking'} state
   */
  setState(state) {
    this._state = state;
    console.log(`[Sphere] State → ${state}`);
  }

  /**
   * Set up mouse/touch interaction for the sphere.
   * @private
   */
  _setupInteraction() {
    const canvas = this._renderer.domElement;

    canvas.addEventListener('mousemove', (e) => {
      const rect = canvas.getBoundingClientRect();
      this._mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      this._mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    });

    canvas.addEventListener('click', (e) => {
      const rect = canvas.getBoundingClientRect();
      this._mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      this._mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      this._raycaster.setFromCamera(this._mouse, this._camera);
      const intersects = this._raycaster.intersectObject(this._points);

      if (intersects.length > 0) {
        // Flash the clicked particle region
        const idx = intersects[0].index;
        this._flashParticle(idx);
      }
    });
  }

  /**
   * Flash a particle at the given index (temporary brightness boost).
   * @param {number} index
   * @private
   */
  _flashParticle(index) {
    const colorAttr = this._geometry.getAttribute('color');
    if (!colorAttr) return;

    // Store original color
    const origR = colorAttr.getX(index);
    const origG = colorAttr.getY(index);
    const origB = colorAttr.getZ(index);

    // Set to white
    colorAttr.setXYZ(index, 1, 1, 1);
    colorAttr.needsUpdate = true;

    // Restore after 300ms
    setTimeout(() => {
      colorAttr.setXYZ(index, origR, origG, origB);
      colorAttr.needsUpdate = true;
    }, 300);
  }
}

// Export
export { ParticleSphere, CONFIG as SPHERE_CONFIG };

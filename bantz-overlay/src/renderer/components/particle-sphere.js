/**
 * Bantz Overlay — Particle Cube Component
 *
 * A rotating cube of cyan dot particles rendered with Three.js.
 * Particles are distributed along the edges and faces of the cube,
 * creating a wireframe-holographic look.
 *
 * Architecture:
 * - Uses Three.js Points with BufferGeometry
 * - Cube edge + face distribution for holographic wireframe
 * - Particles are small circular sprites (cyan #00e5ff)
 *
 * @module particle-cube
 */

import * as THREE from '../vendor/three.min.js';

// ─── Configuration ──────────────────────────────────────────────
const CONFIG = {
  edgeParticles: 30,       // particles per edge (12 edges × 30 = 360)
  faceParticles: 80,       // particles per face (6 faces × 80 = 480)
  cubeSize: 80,            // half-size of cube
  particleSize: 3.0,
  color: 0x00e5ff,         // Cyan
  colorDim: 0x00aacc,      // Dimmer cyan for faces
  colorEdge: 0x66ffff,     // Bright cyan for edges
  rotationSpeed: 0.003,    // radians per frame (idle) — dual axis
  cameraDistance: 240,
  glowColor: 0x00e5ff,
  glowParticleCount: 100,
  glowRadius: 130,
  glowParticleSize: 5.0,
  glowOpacity: 0.12,
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
 * Generate cube points — particles distributed along edges and faces.
 *
 * @returns {{ positions: Float32Array, colors: Float32Array, count: number }}
 */
function generateCubePoints() {
  const positions = [];
  const colors = [];
  const edgeColor = new THREE.Color(CONFIG.colorEdge);
  const faceColor = new THREE.Color(CONFIG.colorDim);
  const s = CONFIG.cubeSize;

  // Cube vertices
  const verts = [
    [-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s],
    [-s, -s, s],  [s, -s, s],  [s, s, s],  [-s, s, s],
  ];

  // 12 edges (pairs of vertex indices)
  const edges = [
    [0,1],[1,2],[2,3],[3,0],  // back face
    [4,5],[5,6],[6,7],[7,4],  // front face
    [0,4],[1,5],[2,6],[3,7],  // connecting edges
  ];

  // Edge particles — bright, along wireframe
  for (const [a, b] of edges) {
    const va = verts[a], vb = verts[b];
    for (let i = 0; i < CONFIG.edgeParticles; i++) {
      const t = i / (CONFIG.edgeParticles - 1);
      positions.push(
        va[0] + (vb[0] - va[0]) * t,
        va[1] + (vb[1] - va[1]) * t,
        va[2] + (vb[2] - va[2]) * t
      );
      colors.push(edgeColor.r, edgeColor.g, edgeColor.b);
    }
  }

  // Face particles — dimmer, scattered on each face
  const faces = [
    { normal: [0,0,-1], right: [1,0,0], up: [0,1,0] },  // back
    { normal: [0,0,1],  right: [1,0,0], up: [0,1,0] },   // front
    { normal: [-1,0,0], right: [0,0,1], up: [0,1,0] },   // left
    { normal: [1,0,0],  right: [0,0,1], up: [0,1,0] },   // right
    { normal: [0,1,0],  right: [1,0,0], up: [0,0,1] },   // top
    { normal: [0,-1,0], right: [1,0,0], up: [0,0,1] },   // bottom
  ];

  for (const face of faces) {
    const center = face.normal.map(n => n * s);
    for (let i = 0; i < CONFIG.faceParticles; i++) {
      const u = (Math.random() - 0.5) * 2 * s * 0.9; // slightly inset from edge
      const v = (Math.random() - 0.5) * 2 * s * 0.9;
      positions.push(
        center[0] + face.right[0] * u + face.up[0] * v,
        center[1] + face.right[1] * u + face.up[1] * v,
        center[2] + face.right[2] * u + face.up[2] * v
      );
      // Subtle random brightness variation
      const dim = 0.5 + Math.random() * 0.3;
      colors.push(faceColor.r * dim, faceColor.g * dim, faceColor.b * dim);
    }
  }

  return {
    positions: new Float32Array(positions),
    colors: new Float32Array(colors),
    count: positions.length / 3,
  };
}

/**
 * Particle Cube — main component class.
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
    const { positions, colors, count } = generateCubePoints();

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
      opacity: 1.0,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });

    // Points mesh
    this._points = new THREE.Points(this._geometry, material);
    this._scene.add(this._points);

    // Ambient glow halo — larger transparent particles around the cube
    this._initGlowHalo();

    console.log(`[Cube] Initialized: ${count} particles + glow halo`);
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

    // Rotate the cube on two axes for interesting motion
    if (this._points) {
      this._points.rotation.y += this._rotationSpeed;
      this._points.rotation.x += this._rotationSpeed * 0.4;
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
}

// Export
export { ParticleSphere, CONFIG as SPHERE_CONFIG };

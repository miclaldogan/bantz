/**
 * Bantz Overlay HUD — Renderer
 *
 * Handles:
 * - Mouse interaction zones (enable/disable click-through)
 * - Connection status display
 * - Daemon message routing (placeholder for future panels)
 * - Particle sphere initialization
 */

import { ParticleSphere } from './components/particle-sphere.js';
import { ParticleScatter } from './components/particle-scatter.js';
import { SphereStateAnimator } from './components/sphere-state.js';

// ─── DOM References ───────────────────────────────────────────
const hudPanel = document.getElementById('hud-panel');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const typewriterText = document.getElementById('typewriter-text');
const sphereContainer = document.getElementById('sphere-container');

// ─── Particle Sphere ───────────────────────────────────────────
let sphere = null;
let stateAnimator = null;

function initSphere() {
  if (!sphereContainer) {
    console.warn('[Overlay] sphere-container not found');
    return;
  }
  sphere = new ParticleSphere(sphereContainer);

  // Attach scatter/dust interaction plugin
  const scatter = new ParticleScatter(sphere, sphereContainer);
  sphere.addPlugin(scatter);

  // Attach state animator plugin
  stateAnimator = new SphereStateAnimator(sphere);
  sphere.addPlugin(stateAnimator);

  sphere.start();

  // Expose for debugging and external access
  window.bantzSphere = sphere;
  window.bantzScatter = scatter;
  window.bantzStateAnimator = stateAnimator;

  // Handle window resize
  window.addEventListener('resize', () => {
    if (sphere) sphere.resize();
  });
}

// ─── News Feed Panel ───────────────────────────────────────────
let newsFeed = null;
let newsImagePopup = null;

function initNewsFeed() {
  if (!window.NewsFeedPanel) {
    console.warn('[Overlay] NewsFeedPanel not loaded');
    return;
  }
  newsFeed = new window.NewsFeedPanel(hudPanel);
  newsFeed.mount();
  newsFeed.show();
  window.bantzNewsFeed = newsFeed;

  // Image popup
  if (window.NewsImagePopup) {
    newsImagePopup = new window.NewsImagePopup(hudPanel);
    window.bantzNewsImagePopup = newsImagePopup;
  }

  console.log('[Overlay] News feed initialized');
}

// ─── Mouse Interaction Zones ──────────────────────────────────
// When the mouse enters the HUD panel, we enable mouse events
// so the user can interact with panels/sphere. When it leaves,
// we disable them so clicks pass through to desktop windows.

hudPanel.addEventListener('mouseenter', () => {
  window.overlayAPI.enableMouse();
});

hudPanel.addEventListener('mouseleave', () => {
  window.overlayAPI.disableMouse();
});

// ─── Connection Status ────────────────────────────────────────
let connectionState = 'disconnected'; // 'connected' | 'connecting' | 'disconnected'

function updateConnectionStatus(state) {
  connectionState = state;
  statusDot.className = 'status-dot';

  switch (state) {
    case 'connected':
      statusDot.classList.add('connected');
      statusText.textContent = 'Daemon connected';
      break;
    case 'connecting':
      statusDot.classList.add('connecting');
      statusText.textContent = 'Connecting...';
      break;
    case 'disconnected':
    default:
      statusText.textContent = 'Disconnected';
      break;
  }
}

// Start as connecting
updateConnectionStatus('connecting');

// ─── Daemon Connection State ──────────────────────────────────
// Listen for connection state changes from the IPC client.
if (window.overlayAPI && window.overlayAPI.onDaemonConnectionState) {
  window.overlayAPI.onDaemonConnectionState((state) => {
    updateConnectionStatus(state);
  });
}

// ─── Daemon Message Handler ───────────────────────────────────
// Future issues (#1405-#1410) will add real handlers here.
// For now, just log and update connection status on first message.

if (window.overlayAPI && window.overlayAPI.onDaemonMessage) {
  window.overlayAPI.onDaemonMessage((message) => {
    if (connectionState !== 'connected') {
      updateConnectionStatus('connected');
    }

    // Route message by type
    switch (message.type) {
      case 'state':
        handleStateMessage(message);
        break;
      case 'action':
        handleActionMessage(message);
        break;
      case 'briefing_start':
      case 'briefing_card':
      case 'briefing_end':
        handleBriefingMessage(message);
        break;
      case 'ping':
        // Respond with pong via main process
        window.overlayAPI.sendDaemonEvent({ type: 'pong', ts: Date.now() });
        break;
      default:
        console.log('[Overlay] Unknown message type:', message.type);
    }
  });
}

// ─── Message Handlers (stubs) ─────────────────────────────────

function handleStateMessage(msg) {
  // Update sphere state animation based on assistant state
  if (stateAnimator && msg.state) {
    stateAnimator.setState(msg.state);
  }
  console.log('[Overlay] State:', msg.state);
}

function handleActionMessage(msg) {
  // Will be implemented in #1401+ (panel actions)
  console.log('[Overlay] Action:', msg.action_type);
}

function handleBriefingMessage(msg) {
  switch (msg.type) {
    case 'briefing_card':
      // Route news cards to the news feed panel
      if (msg.category === 'news' && newsFeed) {
        const articleId = newsFeed.addArticle({
          title: msg.title || msg.headline,
          source: msg.source,
          summary: msg.summary || msg.body,
          id: msg.id,
          ts: msg.ts,
        });
        // If the assistant is currently speaking about this article
        if (msg.active) {
          newsFeed.highlightArticle(articleId);
        }
        // Show image popup if article has an image
        if (msg.image_url && newsImagePopup) {
          newsImagePopup.show({
            image_url: msg.image_url,
            title: msg.title || msg.headline,
            source: msg.source,
            url: msg.url,
          });
        }
      }
      break;
    case 'briefing_start':
      console.log('[Overlay] Briefing started');
      break;
    case 'briefing_end':
      console.log('[Overlay] Briefing ended');
      break;
  }
}

// ─── Visibility Change ────────────────────────────────────────
if (window.overlayAPI && window.overlayAPI.onVisibilityChange) {
  window.overlayAPI.onVisibilityChange((visible) => {
    document.body.style.opacity = visible ? '1' : '0';
  });
}

// ─── Init Log ─────────────────────────────────────────────────
console.log('[Overlay] Renderer initialized');
window.overlayAPI.getDisplayInfo().then((info) => {
  console.log(`[Overlay] Display: ${info.width}x${info.height} @${info.scaleFactor}x`);
});

// ─── Initialize Particle Sphere ─────────────────────────────
initSphere();

// ─── Initialize News Feed ───────────────────────────────────
initNewsFeed();

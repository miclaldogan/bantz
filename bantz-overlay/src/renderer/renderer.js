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

// ─── Panel Layout Engine ──────────────────────────────────────────
let layoutEngine = null;

function initLayoutEngine() {
  if (!window.PanelLayoutEngine) {
    console.warn('[Overlay] PanelLayoutEngine not loaded');
    return;
  }
  layoutEngine = new window.PanelLayoutEngine(hudPanel);
  window.bantzLayout = layoutEngine;
  console.log('[Overlay] Panel layout engine initialized');
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

  // Register with layout engine
  if (layoutEngine) layoutEngine.register('news-feed', newsFeed, 'right');

  // Image popup
  if (window.NewsImagePopup) {
    newsImagePopup = new window.NewsImagePopup(hudPanel);
    window.bantzNewsImagePopup = newsImagePopup;
  }

  console.log('[Overlay] News feed initialized');
}

// ─── Daily Tasks Panel ─────────────────────────────────────────
let dailyTasks = null;

function initDailyTasks() {
  if (!window.DailyTasksPanel) {
    console.warn('[Overlay] DailyTasksPanel not loaded');
    return;
  }
  dailyTasks = new window.DailyTasksPanel(hudPanel);
  dailyTasks.mount();
  dailyTasks.show();
  window.bantzDailyTasks = dailyTasks;

  // Register with layout engine
  if (layoutEngine) layoutEngine.register('daily-tasks', dailyTasks, 'left');

  console.log('[Overlay] Daily tasks initialized');
}

// ─── System Status Panel ───────────────────────────────────────
let systemStatus = null;

function initSystemStatus() {
  if (!window.SystemStatusPanel) {
    console.warn('[Overlay] SystemStatusPanel not loaded');
    return;
  }
  systemStatus = new window.SystemStatusPanel(hudPanel);
  systemStatus.mount();
  systemStatus.show();
  window.bantzSystemStatus = systemStatus;

  // Register with layout engine
  if (layoutEngine) layoutEngine.register('system-status', systemStatus, 'bottom-left');

  console.log('[Overlay] System status initialized');
}

// ─── Typewriter Speech Output ─────────────────────────────────
let typewriter = null;

function initTypewriter() {
  const typewriterContainer = document.getElementById('typewriter-output');
  if (!typewriterContainer || !window.TypewriterOutput) {
    console.warn('[Overlay] TypewriterOutput not available');
    return;
  }
  typewriter = new window.TypewriterOutput(typewriterContainer);
  window.bantzTypewriter = typewriter;
  console.log('[Overlay] Typewriter initialized');
}

// ─── Glitch Effects ───────────────────────────────────────────
let glitchEffects = null;

function initGlitchEffects() {
  if (!window.GlitchEffects) {
    console.warn('[Overlay] GlitchEffects not loaded');
    return;
  }
  glitchEffects = new window.GlitchEffects(hudPanel);
  window.bantzGlitchEffects = glitchEffects;
  console.log('[Overlay] Glitch effects initialized');
}

// ─── Panel Transitions ───────────────────────────────────────────
let panelTransitions = null;
let previousState = 'idle';

function initPanelTransitions() {
  if (!window.PanelTransitions) {
    console.warn('[Overlay] PanelTransitions not loaded');
    return;
  }
  panelTransitions = new window.PanelTransitions(hudPanel);
  window.bantzTransitions = panelTransitions;
  console.log('[Overlay] Panel transitions initialized');
}

// ─── Reasoning Chain Display ─────────────────────────────────
let reasoningChain = null;

function initReasoningChain() {
  const reasoningContainer = document.getElementById('reasoning-chain');
  if (!reasoningContainer || !window.ReasoningChain) {
    console.warn('[Overlay] ReasoningChain not available');
    return;
  }
  reasoningChain = new window.ReasoningChain(reasoningContainer);
  window.bantzReasoningChain = reasoningChain;
  console.log('[Overlay] Reasoning chain initialized');
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
    // Choreograph state transition animations
    if (panelTransitions && previousState !== msg.state) {
      panelTransitions.choreographStateChange(previousState, msg.state, {
        stateAnimator,
        typewriter,
        reasoningChain,
        glitchEffects,
      });
    }
    previousState = msg.state;

    stateAnimator.setState(msg.state);

    // Trigger glitch effects on state transitions
    if (glitchEffects) {
      if (msg.state === 'wake') {
        glitchEffects.triggerWakeFlicker();
        glitchEffects.triggerChromatic('normal');
      } else if (msg.state === 'thinking') {
        glitchEffects.triggerChromatic('intense');
      } else if (msg.state === 'listening' || msg.state === 'speaking') {
        glitchEffects.triggerChromatic('normal');
      }
    }
  }

  // Handle speech tokens for typewriter
  if (typewriter) {
    if (msg.speech_token) {
      typewriter.addToken(msg.speech_token);
    }
    if (msg.speech_start) {
      // End reasoning when speech begins
      if (reasoningChain) reasoningChain.end();
      typewriter.beginSpeech();
    }
    if (msg.speech_end) {
      typewriter.endSpeech();
    }
  }

  // Handle reasoning tokens
  if (reasoningChain) {
    if (msg.reasoning_token) {
      reasoningChain.addToken(msg.reasoning_token);
    }
    if (msg.reasoning_start) {
      reasoningChain.begin();
    }
    if (msg.reasoning_end) {
      reasoningChain.end();
    }
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
      // Route calendar cards to daily tasks panel
      if (msg.category === 'calendar' && dailyTasks) {
        dailyTasks.addEvent({
          title: msg.title,
          start: msg.start,
          end: msg.end,
          all_day: msg.all_day,
          id: msg.id,
        });
      }
      // Route task cards
      if (msg.category === 'task' && dailyTasks) {
        dailyTasks.addTask({
          title: msg.title,
          completed: msg.completed,
          id: msg.id,
        });
      }
      // Route weather cards to system status panel
      if (msg.category === 'weather' && systemStatus) {
        systemStatus.setWeather({
          temperature: msg.temperature,
          condition: msg.condition,
          humidity: msg.humidity,
          wind_speed: msg.wind_speed,
        });
      }
      // Route system metrics
      if (msg.category === 'system' && systemStatus) {
        systemStatus.setSystemMetrics({
          cpu: msg.cpu,
          ram: msg.ram,
          disk: msg.disk,
          uptime_seconds: msg.uptime_seconds,
        });
      }
      break;
    case 'briefing_start':
      console.log('[Overlay] Briefing started');
      // Play boot sequence animation
      if (panelTransitions) {
        panelTransitions.playBootSequence(
          {
            'daily-tasks': dailyTasks,
            'news-feed': newsFeed,
            'system-status': systemStatus,
          },
          sphere
        );
      }
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

// ─── Initialize Panel Layout Engine ─────────────────────────
initLayoutEngine();

// ─── Initialize News Feed ───────────────────────────────────
initNewsFeed();

// ─── Initialize Daily Tasks ─────────────────────────────────
initDailyTasks();

// ─── Initialize System Status ───────────────────────────────
initSystemStatus();

// ─── Initialize Typewriter ─────────────────────────────────
initTypewriter();

// ─── Initialize Glitch Effects ──────────────────────────────
initGlitchEffects();

// ─── Initialize Panel Transitions ───────────────────────────
initPanelTransitions();

// ─── Initialize Reasoning Chain ─────────────────────────────
initReasoningChain();

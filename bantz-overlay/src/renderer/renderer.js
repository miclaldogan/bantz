/**
 * Bantz Overlay HUD — Renderer
 *
 * Handles:
 * - Mouse interaction zones (enable/disable click-through)
 * - Connection status display
 * - Daemon message routing (placeholder for future panels)
 * - Particle sphere initialization
 */

console.log('[Overlay] renderer.js: module loading...');

import { ParticleSphere } from './components/particle-sphere.js';
import { ParticleScatter } from './components/particle-scatter.js';
import { SphereStateAnimator } from './components/sphere-state.js';

console.log('[Overlay] renderer.js: imports complete');

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

// ─── Clock Panel ──────────────────────────────────────────────
let clockPanel = null;

function initClockPanel() {
  if (!window.ClockPanel) {
    console.warn('[Overlay] ClockPanel not loaded');
    return;
  }
  clockPanel = new window.ClockPanel(hudPanel);
  clockPanel.mount();
  clockPanel.show();
  window.bantzClock = clockPanel;

  // Register with layout engine
  if (layoutEngine) layoutEngine.register('clock', clockPanel, 'bottom-right');

  console.log('[Overlay] Clock panel initialized');
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

// ─── TTS Voice Sync ───────────────────────────────────────────
let ttsSync = null;

function initTTSSync() {
  if (!window.TTSVoiceSync || !typewriter) {
    console.warn('[Overlay] TTSVoiceSync or typewriter not available');
    return;
  }
  ttsSync = new window.TTSVoiceSync(typewriter, hudPanel);
  window.bantzTTSSync = ttsSync;
  console.log('[Overlay] TTS voice sync initialized');
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
// Electron's setIgnoreMouseEvents(true, { forward: true }) makes the
// window click-through but still forwards mousemove to the renderer.
// We track mousemove on document to detect when cursor is over
// interactive content, then toggle click-through accordingly.
//
// mouseenter/mouseleave are unreliable with setIgnoreMouseEvents
// on X11, so we use mousemove + elementFromPoint instead.

let _mouseEnabled = false;

document.addEventListener('mousemove', (e) => {
  // Check what's under the cursor
  const el = document.elementFromPoint(e.clientX, e.clientY);
  if (!el) {
    if (_mouseEnabled) {
      window.overlayAPI.disableMouse();
      _mouseEnabled = false;
    }
    return;
  }

  // Check if cursor is over any interactive element
  const isInteractive = !!(
    el.closest('.hud-panel') ||
    el.closest('.terminal-panel') ||
    el.closest('.news-tooltip') ||
    el.closest('.phone-call-overlay') ||
    el.closest('.news-popup')
  );

  if (isInteractive && !_mouseEnabled) {
    window.overlayAPI.enableMouse();
    _mouseEnabled = true;
  } else if (!isInteractive && _mouseEnabled) {
    window.overlayAPI.disableMouse();
    _mouseEnabled = false;
  }
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

// ─── IPC Reconnection Logic ──────────────────────────────────
let reconnectTimer = null;
let briefingInProgress = false;
const RECONNECT_INTERVAL = 2000; // retry every 2s

function startReconnect() {
  if (reconnectTimer) return;
  updateConnectionStatus('connecting');
  reconnectTimer = setInterval(() => {
    if (connectionState === 'connected') {
      clearInterval(reconnectTimer);
      reconnectTimer = null;
      return;
    }
    console.log('[Overlay] Retrying IPC connection...');
    if (window.overlayAPI && window.overlayAPI.reconnect) {
      window.overlayAPI.reconnect();
    }
  }, RECONNECT_INTERVAL);
}

// ─── First-Boot & Absence Detection ──────────────────────────
const LAST_SEEN_KEY = 'bantz_last_seen_ts';
const ABSENCE_THRESHOLD = 24 * 60 * 60 * 1000; // 24 hours in ms

function checkFirstBootOrAbsence() {
  const lastSeen = localStorage.getItem(LAST_SEEN_KEY);
  const now = Date.now();

  // Update last seen
  localStorage.setItem(LAST_SEEN_KEY, String(now));

  if (!lastSeen) {
    // First boot ever
    console.log('[Overlay] First boot detected — welcome animation');
    if (typewriter) {
      typewriter.beginSpeech();
      typewriter.addToken('Merhaba! ');
      typewriter.addToken('Ben Bantz, ');
      typewriter.addToken('kişisel AI asistanınız. ');
      typewriter.addToken('Hazırım.');
      setTimeout(() => typewriter.endSpeech(), 3000);
    }
    return 'first-boot';
  }

  const elapsed = now - parseInt(lastSeen, 10);
  if (elapsed > ABSENCE_THRESHOLD) {
    // Long absence
    const hours = Math.floor(elapsed / (60 * 60 * 1000));
    console.log(`[Overlay] Absence detected: ${hours}h`);
    if (typewriter) {
      typewriter.beginSpeech();
      typewriter.addToken('Uzun zamandır görüşemedik! ');
      typewriter.addToken('Sizi tekrar görmek güzel.');
      setTimeout(() => typewriter.endSpeech(), 3000);
    }
    return 'absence';
  }

  return 'normal';
}

// ─── Daemon Connection State ──────────────────────────────────
// Listen for connection state changes from the IPC client.
if (window.overlayAPI && window.overlayAPI.onDaemonConnectionState) {
  window.overlayAPI.onDaemonConnectionState((state) => {
    updateConnectionStatus(state);

    if (state === 'disconnected') {
      // If disconnected mid-briefing, show fallback
      if (briefingInProgress) {
        briefingInProgress = false;
        console.warn('[Overlay] IPC lost during briefing — fallback state');
        if (typewriter) {
          typewriter.beginSpeech();
          typewriter.addToken('Bağlantı kesildi. Tekrar bağlanıyorum...');
          setTimeout(() => typewriter.endSpeech(), 2000);
        }
      }
      // Start reconnection attempts
      startReconnect();
    }
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
      case 'event':
        // Handle daemon events (phone calls, etc.)
        handleDaemonEvent(message);
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
      if (ttsSync) ttsSync.trackToken(msg.speech_token);
    }
    if (msg.speech_start) {
      // End reasoning when speech begins
      if (reasoningChain) reasoningChain.end();
      typewriter.beginSpeech();
      if (ttsSync) ttsSync.onTTSStart();
    }
    if (msg.speech_end) {
      typewriter.endSpeech();
      if (ttsSync) ttsSync.onTTSEnd();
    }
  }

  // Handle TTS word boundary events
  if (ttsSync && msg.tts_word_boundary) {
    ttsSync.onWordBoundary(msg.tts_word_boundary);
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

function handleDaemonEvent(msg) {
  const event = msg.event;
  const data = msg.data || {};

  switch (event) {
    case 'phone:incoming':
      if (phoneCallOverlay) {
        phoneCallOverlay.showIncoming({
          caller_name: data.caller_name || 'Bilinmeyen',
          caller_number: data.caller_number || '',
          caller_photo: data.caller_photo || null,
        });
      }
      break;
    case 'phone:ended':
      if (phoneCallOverlay) {
        phoneCallOverlay.callEnded(data.duration_seconds || 0);
      }
      break;
    default:
      console.log('[Overlay] Daemon event:', event, data);
  }
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
      briefingInProgress = true;
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
      console.log('[Overlay] Briefing ended — panels persist');
      briefingInProgress = false;
      // Panels stay visible (persistent mode)
      // Transition sphere to idle
      if (stateAnimator) stateAnimator.setState('idle');
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

// ─── Initialize Clock Panel ─────────────────────────────────
initClockPanel();

// ─── Initialize Typewriter ─────────────────────────────────
initTypewriter();

// ─── Initialize Glitch Effects ──────────────────────────────
initGlitchEffects();

// ─── Initialize Panel Transitions ───────────────────────────
initPanelTransitions();

// ─── Initialize TTS Sync ───────────────────────────────────
initTTSSync();

// ─── Check First Boot / Absence ─────────────────────────────
checkFirstBootOrAbsence();

// ─── Initialize Reasoning Chain ─────────────────────────────
initReasoningChain();

// ─── Initialize Phone Call Overlay ──────────────────────────
let phoneCallOverlay = null;

function initPhoneCallOverlay() {
  if (!window.PhoneCallOverlay) {
    console.warn('[Overlay] PhoneCallOverlay not loaded');
    return;
  }
  phoneCallOverlay = new window.PhoneCallOverlay();
  phoneCallOverlay.mount(document.body);
  window.bantzPhoneCall = phoneCallOverlay;
  console.log('[Overlay] Phone call overlay initialized');
}

initPhoneCallOverlay();

// ─── Diagnostic Summary ─────────────────────────────────────
console.log('[Overlay] ═══ INIT SUMMARY ═══');
console.log('[Overlay]   sphere:', !!sphere);
console.log('[Overlay]   layoutEngine:', !!layoutEngine);
console.log('[Overlay]   newsFeed:', !!newsFeed);
console.log('[Overlay]   dailyTasks:', !!dailyTasks);
console.log('[Overlay]   systemStatus:', !!systemStatus);
console.log('[Overlay]   clockPanel:', !!clockPanel);
console.log('[Overlay]   typewriter:', !!typewriter);
console.log('[Overlay]   glitchEffects:', !!glitchEffects);
console.log('[Overlay]   panelTransitions:', !!panelTransitions);
console.log('[Overlay]   ttsSync:', !!ttsSync);
console.log('[Overlay]   reasoningChain:', !!reasoningChain);
console.log('[Overlay]   phoneCallOverlay:', !!phoneCallOverlay);
console.log('[Overlay]   hudPanel:', !!hudPanel);
console.log('[Overlay]   sphereContainer:', !!sphereContainer);
console.log('[Overlay] ═══════════════════');

// ─── Tray Commands ──────────────────────────────────────────
if (window.overlayAPI) {
  // Effect intensity from tray
  if (window.overlayAPI.onEffectIntensity) {
    window.overlayAPI.onEffectIntensity((level) => {
      if (glitchEffects) {
        if (level === 'off') {
          glitchEffects.setEnabled(false);
        } else {
          glitchEffects.setEnabled(true);
          glitchEffects.setIntensity(level);
        }
      }
      console.log('[Overlay] Effect intensity:', level);
    });
  }

  // Animation speed from tray
  if (window.overlayAPI.onAnimationSpeed) {
    window.overlayAPI.onAnimationSpeed((speed) => {
      if (panelTransitions) panelTransitions.setSpeed(speed);
      console.log('[Overlay] Animation speed:', speed);
    });
  }

  // Panel toggle from tray
  if (window.overlayAPI.onTogglePanel) {
    window.overlayAPI.onTogglePanel(({ panelId, visible }) => {
      if (layoutEngine) {
        if (visible) {
          layoutEngine.show(panelId);
        } else {
          layoutEngine.hide(panelId);
        }
      }
      console.log('[Overlay] Panel toggle:', panelId, visible);
    });
  }
}

// ─── Demo Mode ──────────────────────────────────────────────
// Auto-starts with mock data if no briefing data within 3s
let demoMode = null;

function initDemoMode() {
  if (!window.BantzDemoMode) {
    console.warn('[Overlay] DemoMode not loaded');
    return;
  }
  demoMode = new window.BantzDemoMode();
  window.bantzDemo = demoMode;

  // Schedule auto-start if no briefing data arrives within 3s
  // (works regardless of daemon connection state)
  demoMode.scheduleAutoStart(3000);

  // Cancel demo auto-start only when real briefing data arrives
  // The briefing_start handler above will cancel if needed

  console.log('[Overlay] Demo mode ready (auto-start in 3s if no briefing data)');
}

initDemoMode();

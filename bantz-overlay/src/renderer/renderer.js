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
const bootLogEl = document.getElementById('boot-log');
const bootLayer = document.getElementById('boot-layer');

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

// ─── Unified Inbox Panel ───────────────────────────────────────
let inboxPanel = null;

function initInboxPanel() {
  if (!window.InboxPanel) {
    console.warn('[Overlay] InboxPanel not loaded');
    return;
  }
  inboxPanel = new window.InboxPanel(hudPanel);
  inboxPanel.mount();
  inboxPanel.show();
  window.bantzInbox = inboxPanel;

  // Register with layout engine
  if (layoutEngine) layoutEngine.register('inbox', inboxPanel, 'left');

  console.log('[Overlay] Inbox panel initialized');
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

// ─── Once-per-session system alert flags ─────────────────────
const _sysAlerted = { cpu: false, ram: false, disk: false };

// ─── Boot Sequence ────────────────────────────────────────────
const bootLines = [];

function setPhase(phase) {
  document.body.classList.remove('phase-boot', 'phase-transition', 'phase-live');
  document.body.classList.add(phase);
}

function pushBootLog(line) {
  if (!bootLogEl || !line) return;
  bootLines.push(`> ${line}`);
  if (bootLines.length > 120) bootLines.shift();
  bootLogEl.textContent = bootLines.join('\n');
  // Auto-scroll to latest entry
  requestAnimationFrame(() => {
    bootLogEl.scrollTop = bootLogEl.scrollHeight;
  });
}

function startBootSequence() {
  if (!bootLayer) return;
  setPhase('phase-boot');

  const initial = [
    '[ 0.000000] Bantz kernel v6.8.0-bantz SMP PREEMPT_DYNAMIC',
    '[ 0.001024] CPU: 12c/24t @ 4.7GHz  |  RAM: 32768 MB DDR5',
    '[ 0.002341] GPU: NVIDIA RTX 4060 VRAM 8192 MB',
    '[ 0.003456] NET: eth0 UP 192.168.1.47/24 MTU 1500',
    '[ 0.004567] ipc: initializing bantz overlay transport...',
    '[ 0.005678] skills: loading (news, calendar, gmail, weather)',
    '[ 0.006789] overlay: hardware-accelerated rendering OK',
  ];
  initial.forEach(pushBootLog);

  // Rapid hacker lines scrolling
  const hackerLines = [
    '[ 0.012345] ACPI: RSDP 0x00000000000F0490 000024 (v02 BOCHS )',
    '[ 0.023456] PCI: Using configuration type 1 for base access',
    '[ 0.034567] VFS: Mounted root filesystem (ext4) read-write',
    '[ 0.045678] BIOS-e820: [mem 0x0000000000000000-0x000000000009fbff] usable',
    '[ 0.056789] initrd loaded at 0x1000000 (size: 45.2 MB)',
    '[ 0.067890] libata: version 3.00 — SATA link up 6.0 Gbps',
    '[ 0.078901] usb: xhci_hcd USB 3.2 SuperSpeed 20 Gbps',
    '[ 0.089012] input: AT Translated Set 2 keyboard as /dev/input/event0',
    '[ 0.100123] EFI: getvar ExitBootServiceCount failed (0x8000000000000002)',
    '[ 0.111234] pci 0000:01:00.0 [10de:2882] type 00 class 0x030200',
    '[ 0.122345] Loaded kernel module: nvidia-drm    v560.35.03',
    '[ 0.133456] NVRM: loading NVIDIA UNIX x86_64 Kernel Module 560.35.03',
    '[ 0.144567] PM: hibernation: Registered platform driver pcie_port',
    '[ 0.155678] NET: Registered PF_INET6 protocol family',
    '[ 0.166789] ip6_tables: (C) 2000-2006 Netfilter Core Team',
    '[ 0.177890] ip_tables: (C) 2000-2006 Netfilter Core Team',
    '[ OK ] Started System Logging Service.',
    '[ OK ] Reached target Basic System.',
    '[ OK ] Started D-Bus System Message Bus.',
    '[ OK ] Started Network Manager.',
    '[ OK ] Reached target Network.',
    '[ OK ] Started Avahi mDNS/DNS-SD Daemon.',
    '[ OK ] Started Neural Network Interface Daemon.',
    '[ OK ] Started Bantz LLM Core Service.',
    '[ OK ] Started PulseAudio Sound System.',
    '[ OK ] Reached target Sound Card.',
    '[ OK ] Reached target Graphical Interface.',
    'bantz: loading config from ~/.config/bantz/config.yaml',
    'graph: autolinker v2.1.0 — connecting to graph.db',
    'graph: SQLite WAL mode enabled — nodes:4 edges:2',
    'ipc: socket /home/.local/share/bantz/ipc/overlay.sock',
    'ipc: listening for daemon connection...',
    'mem: heap 256 MB / 32768 MB allocated',
    'llm: router  qwen2.5-coder:7b ✓',
    'llm: final   gemini-2.0-flash ✓',
    'skills: 76 tools registered and verified',
    'calendar: OAuth token valid (expires in 89 days)',
    'gmail: IMAP connection established (STARTTLS)',
    'weather: OpenMeteo API endpoint responsive',
    'news: RSS feeds indexed (15 articles ready)',
    'vision: OpenCV 4.9 — initialized',
    'voice: Whisper STT model v3 loaded',
    'audio: PulseAudio pulse:0 @ 48000 Hz stereo',
    'overlay: all subsystems operational',
    '> BANTZ OVERLAY v0.3 — READY',
  ];

  let hackerIdx = 0;
  const hackerInterval = setInterval(() => {
    if (hackerIdx < hackerLines.length) {
      pushBootLog(hackerLines[hackerIdx++]);
    } else {
      clearInterval(hackerInterval);
    }
  }, 85);

  setTimeout(() => {
    clearInterval(hackerInterval);
    setPhase('phase-transition');
  }, 3800);
  setTimeout(() => {
    setPhase('phase-live');
    setTimeout(() => {
      if (bootLayer) bootLayer.classList.add('hidden');
    }, 400);
  }, 4500);
}

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
    el.closest('.news-popup') ||
    el.closest('.text-input-container')
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
      pushBootLog('bantz: daemon connected');
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
let briefingMailCards = [];
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

// ─── Phone Call Overlay (early declaration) ──────────────────
// Declared here so handleDaemonEvent can reference it; initialized later.
let phoneCallOverlay = null;

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
        Promise.resolve(handleBriefingMessage(message)).catch((err) => {
          console.warn('[Overlay] briefing handler failed:', err);
        });
        break;
      case 'ping':
        // Respond with pong via main process
        window.overlayAPI.sendDaemonEvent({ type: 'pong', ts: Date.now() });
        break;
      case 'event':
        // Handle daemon events (phone calls, etc.)
        handleDaemonEvent(message);
        break;
      case 'voice_state':
        // Handle voice pipeline state changes (Issue #1440)
        handleVoiceStateMessage(message);
        break;
      case 'response':
        // Handle text command response from daemon
        handleResponseMessage(message);
        break;
      default:
        console.log('[Overlay] Unknown message type:', message.type);
    }
  });
}

// ─── Message Handlers (stubs) ─────────────────────────────────

function handleResponseMessage(msg) {
  // Display daemon's response to user's text command
  const text = msg.text || '';
  console.log('[Overlay] Response from daemon:', text.substring(0, 100));
  if (typewriter && text) {
    typewriter.clear();
    typewriter.type(text);
  }
}

function handleStateMessage(msg) {
  if (msg.state) pushBootLog(`state: ${msg.state}`);

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
  const action = msg.action || msg.action_type;

  switch (action) {
    case 'preview':
      // Show short text preview under main state (e.g. tool name being called)
      if (typewriter) {
        typewriter.showPreview(msg.text || '', msg.duration_ms || 1200);
      }
      break;

    case 'cursor_dot':
      // Show a dot/ring at the given screen coordinate
      if (glitchEffects && msg.x != null && msg.y != null) {
        glitchEffects.showCursorDot(msg.x, msg.y, msg.duration_ms || 800);
      }
      break;

    case 'highlight':
      // Highlight a rectangular screen region
      if (glitchEffects && msg.rect_x != null) {
        glitchEffects.showHighlight(
          msg.rect_x, msg.rect_y, msg.rect_w, msg.rect_h,
          msg.duration_ms || 1200
        );
      }
      break;

    default:
      console.log('[Overlay] Unknown action:', action);
  }
}

// ─── Voice State Handler (Issue #1440) ────────────────────────
function handleVoiceStateMessage(msg) {
  const voiceState = msg.state;
  if (!voiceState) return;

  // Map voice state to sphere state (same enum: idle, wake, listening, thinking, speaking)
  if (stateAnimator) {
    stateAnimator.setState(voiceState);
  }

  // Trigger glitch effects on voice state transitions
  if (glitchEffects) {
    if (voiceState === 'wake') {
      glitchEffects.triggerWakeFlicker();
      glitchEffects.triggerChromatic('normal');
    } else if (voiceState === 'thinking') {
      glitchEffects.triggerChromatic('intense');
    } else if (voiceState === 'listening' || voiceState === 'speaking') {
      glitchEffects.triggerChromatic('normal');
    }
  }

  // Choreograph panel transitions
  if (panelTransitions && previousState !== voiceState) {
    panelTransitions.choreographStateChange(previousState, voiceState, {
      stateAnimator,
      typewriter,
      reasoningChain,
      glitchEffects,
    });
    previousState = voiceState;
  }

  // Log wake word data if present
  if (msg.data && msg.data.wake_word) {
    console.log(`[Voice] Wake word: ${msg.data.wake_word} (${msg.data.confidence})`);
  }

  console.log('[Voice] State:', voiceState, msg.trigger || '');
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

async function handleBriefingMessage(msg) {
  switch (msg.type) {
    case 'briefing_card':
      // Route news cards to the news feed panel
      if (msg.category === 'news' && newsFeed) {
        const articleLink = msg.url || msg.link || '';
        const articleId = newsFeed.addArticle({
          title: msg.title || msg.headline,
          source: msg.source,
          summary: msg.summary || msg.body,
          link: articleLink,
          id: msg.id,
          ts: msg.ts,
        });
        // If the assistant is currently speaking about this article
        if (msg.active) {
          newsFeed.highlightArticle(articleId);
        }
        // Show image popup spread (up to 3) with OG-image fallback.
        if (newsImagePopup) {
          const imageCandidates = [
            msg.image_url,
            msg.image,
            msg.thumbnail_url,
            ...(Array.isArray(msg.image_urls) ? msg.image_urls : []),
          ].filter(Boolean);

          if (imageCandidates.length === 0 && articleLink && window.overlayAPI?.getArticleImage) {
            try {
              const resolved = await window.overlayAPI.getArticleImage(articleLink);
              if (resolved) imageCandidates.push(resolved);
            } catch (e) {
              console.warn('[Overlay] getArticleImage failed:', e);
            }
          }

          if (imageCandidates.length > 0) {
            const uniqueUrls = Array.from(new Set(imageCandidates)).slice(0, 3);
            newsImagePopup.show({
              image_urls: uniqueUrls,
              image_url: uniqueUrls[0],
              title: msg.title || msg.headline,
              source: msg.source,
              url: articleLink,
            });
          }
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
      // Also route calendar to inbox panel
      if (msg.category === 'calendar' && inboxPanel) {
        inboxPanel.setCalendarEvents([{
          title: msg.title,
          start: msg.start,
          end: msg.end,
          all_day: msg.all_day,
          id: msg.id,
        }]);
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
        // Also route critical system alerts to inbox panel (once per session)
        if (inboxPanel) {
          if (msg.cpu > 90 && !_sysAlerted.cpu) {
            _sysAlerted.cpu = true;
            inboxPanel.addSystemNotification(`CPU usage critical: ${msg.cpu}%`);
          }
          if (msg.ram > 90 && !_sysAlerted.ram) {
            _sysAlerted.ram = true;
            inboxPanel.addSystemNotification(`RAM usage critical: ${msg.ram}%`);
          }
          if (msg.disk > 85 && !_sysAlerted.disk) {
            _sysAlerted.disk = true;
            inboxPanel.addSystemNotification(`Disk usage high: ${msg.disk}% — consider cleanup`);
          }
        }
      }
      // Route mail cards to inbox panel
      if (msg.category === 'mail' && inboxPanel) {
        // Accumulate mail cards; setMailMessages replaces all mail items so we
        // collect them in briefingMailCards and flush once (or per card for live feel).
        briefingMailCards.push({
          from: msg.from || msg.sender,
          subject: msg.subject || msg.title,
          snippet: msg.snippet || msg.body || msg.summary,
          ts: msg.ts,
          date: msg.ts,
          id: msg.id,
          unread: !!msg.is_unread,
        });
        inboxPanel.setMailMessages(briefingMailCards);
      }
      break;
    case 'briefing_start':
      console.log('[Overlay] Briefing started');
      briefingInProgress = true;
      // Reset mail card accumulator for fresh briefing
      briefingMailCards = [];

      // Cancel demo mode auto-start — real data is arriving
      if (demoMode) demoMode.cancelAutoStart();

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
startBootSequence();
pushBootLog('renderer: module initialized');
window.overlayAPI.getDisplayInfo().then((info) => {
  console.log(`[Overlay] Display: ${info.width}x${info.height} @${info.scaleFactor}x`);
  pushBootLog(`display: ${info.width}x${info.height} @${info.scaleFactor}x`);
});

// ─── Initialize Particle Sphere ─────────────────────────────
initSphere();

// ─── Initialize Panel Layout Engine ─────────────────────────
initLayoutEngine();

// ─── Initialize News Feed ───────────────────────────────────
initNewsFeed();

// ─── Initialize Daily Tasks ─────────────────────────────────
initDailyTasks();

// ─── Initialize System Status (disabled — blocks chat text) ───
// initSystemStatus();

// ─── Initialize Inbox Panel ─────────────────────────────────
initInboxPanel();

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

// ─── Classroom Dialog (Issue #1467) ────────────────────────
let classroomDialog = null;
let googleAuthScopeIndicator = null;

function initClassroomDialog() {
  if (!window.ClassroomDialog) {
    console.warn('[Overlay] ClassroomDialog not loaded');
    return;
  }
  classroomDialog = new window.ClassroomDialog();
  classroomDialog.mount(hudPanel);
  window.bantzClassroomDialog = classroomDialog;
  console.log('[Overlay] Classroom dialog initialized');
}

function initGoogleAuthScopeIndicator() {
  if (!window.GoogleAuthScopeIndicator) {
    console.warn('[Overlay] GoogleAuthScopeIndicator not loaded');
    return;
  }
  googleAuthScopeIndicator = new window.GoogleAuthScopeIndicator();
  googleAuthScopeIndicator.mount(hudPanel);
  window.bantzAuthScopeIndicator = googleAuthScopeIndicator;
  console.log('[Overlay] Google auth scope indicator initialized');
}

// ─── Initialize Phone Call Overlay ──────────────────────────

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

// ─── Initialize Classroom Dialog ───────────────────────────
initClassroomDialog();

// ─── Initialize Google Auth Scope Indicator ─────────────────
initGoogleAuthScopeIndicator();

// ─── Initialize Floating Text Input ─────────────────────────
let textInput = null;
let _textInputRetries = 0;

function initTextInput() {
  const Cls = window.FloatingTextInput;
  if (!Cls) {
    if (_textInputRetries < 8) {
      _textInputRetries++;
      setTimeout(initTextInput, 250);  // retry up to 2 seconds
    } else {
      console.warn('[Overlay] FloatingTextInput not loaded after retries');
    }
    return;
  }
  try {
    textInput = new Cls();
    textInput.mount(document.body);
    textInput.onSend((text) => {
      // Echo to typewriter
      if (typewriter && typewriter.clear && typewriter.type) {
        typewriter.clear();
        typewriter.type(`> ${text}`);
      }
      // Send to daemon
      if (window.overlayAPI && window.overlayAPI.sendCommand) {
        window.overlayAPI.sendCommand(text);
      }
      console.log('[Overlay] Text command sent:', text.substring(0, 80));
    });
    window.bantzTextInput = textInput;
    console.log('[Overlay] Floating text input initialized ✓');
  } catch (e) {
    console.warn('[Overlay] FloatingTextInput init error:', e);
  }
}

initTextInput();

// ─── Diagnostic Summary ─────────────────────────────────────
console.log('[Overlay] ═══ INIT SUMMARY ═══');
console.log('[Overlay]   sphere:', !!sphere);
console.log('[Overlay]   layoutEngine:', !!layoutEngine);
console.log('[Overlay]   newsFeed:', !!newsFeed);
console.log('[Overlay]   dailyTasks:', !!dailyTasks);
console.log('[Overlay]   systemStatus:', !!systemStatus);
console.log('[Overlay]   inboxPanel:', !!inboxPanel);
console.log('[Overlay]   clockPanel:', !!clockPanel);
console.log('[Overlay]   typewriter:', !!typewriter);
console.log('[Overlay]   glitchEffects:', !!glitchEffects);
console.log('[Overlay]   panelTransitions:', !!panelTransitions);
console.log('[Overlay]   ttsSync:', !!ttsSync);
console.log('[Overlay]   reasoningChain:', !!reasoningChain);
console.log('[Overlay]   phoneCallOverlay:', !!phoneCallOverlay);
console.log('[Overlay]   textInput:', !!textInput);
console.log('[Overlay]   classroomDialog:', !!classroomDialog);
console.log('[Overlay]   googleAuthScopeIndicator:', !!googleAuthScopeIndicator);
console.log('[Overlay]   hudPanel:', !!hudPanel);
console.log('[Overlay]   sphereContainer:', !!sphereContainer);
console.log('[Overlay] ═══════════════════');

// ─── Fallback Data Loader ───────────────────────────────────
// If no briefing arrives within 5s, fetch data directly via Electron IPC
// (weather, system metrics, news). This ensures panels aren't empty
// when the daemon briefing flow doesn't fire.
const FALLBACK_DATA_TIMEOUT = 5000;

setTimeout(async () => {
  if (briefingInProgress) return; // briefing is active, no need

  const api = window.overlayAPI;
  if (!api) return;

  console.log('[Overlay] No briefing received — loading fallback data...');

  // Weather
  if (systemStatus && api.getWeather) {
    try {
      const weather = await api.getWeather();
      if (weather) systemStatus.setWeather(weather);
    } catch (e) {
      console.warn('[Overlay] Fallback weather fetch failed:', e);
    }
  }

  // System metrics
  if (systemStatus && api.getSystemMetrics) {
    try {
      const metrics = await api.getSystemMetrics();
      if (metrics) systemStatus.setSystemMetrics(metrics);
    } catch (e) {
      console.warn('[Overlay] Fallback metrics fetch failed:', e);
    }
  }

  // News feed
  if (newsFeed && api.getNewsFeed) {
    try {
      const articles = await api.getNewsFeed();
      if (articles && Array.isArray(articles)) {
        articles.forEach(article => newsFeed.addArticle(article));
      }
    } catch (e) {
      console.warn('[Overlay] Fallback news fetch failed:', e);
    }
  }
}, FALLBACK_DATA_TIMEOUT);

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

pushBootLog('overlay: live UI ready');

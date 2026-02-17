/**
 * Bantz Overlay HUD — Renderer
 *
 * Handles:
 * - Mouse interaction zones (enable/disable click-through)
 * - Connection status display
 * - Daemon message routing (placeholder for future panels)
 */

(function () {
  'use strict';

  // ─── DOM References ───────────────────────────────────────────
  const hudPanel = document.getElementById('hud-panel');
  const statusDot = document.getElementById('status-dot');
  const statusText = document.getElementById('status-text');
  const typewriterText = document.getElementById('typewriter-text');

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

  // ─── Daemon Message Handler ───────────────────────────────────
  // Future issues (#1399, #1405-#1410) will add real handlers here.
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
    // Will be implemented in #1404 (sphere state), #1409 (typewriter)
    console.log('[Overlay] State:', msg.state);
  }

  function handleActionMessage(msg) {
    // Will be implemented in #1401+ (panel actions)
    console.log('[Overlay] Action:', msg.action_type);
  }

  function handleBriefingMessage(msg) {
    // Will be implemented in #1405-#1407 (content panels), #1414 (integration)
    console.log('[Overlay] Briefing:', msg.type);
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
})();

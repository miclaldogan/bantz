/**
 * Bantz Overlay — System Tray Integration (#1416)
 *
 * Provides a system tray icon with:
 * - Left-click: toggle overlay visibility
 * - Right-click: context menu with panel/effect controls
 * - Connection status indicator (green/yellow/red dot via icon swap)
 * - Keyboard shortcut info
 */

const { Tray, Menu, nativeImage, Notification } = require('electron');
const path = require('path');

// ── Tray Icon Paths ──────────────────────────────────────────────
const ICON_PATH = path.join(__dirname, '../../assets/tray-icon.svg');

/**
 * Create and manage the system tray.
 *
 * @param {object} opts
 * @param {Function} opts.onToggleOverlay  — Toggle overlay visibility
 * @param {Function} opts.onQuit           — Quit the app
 * @param {Function} opts.getVisibility    — () => boolean
 * @param {Function} opts.getConnectionState — () => 'connected'|'connecting'|'disconnected'
 * @param {Function} [opts.onEffectIntensity] — (level) => void
 * @param {Function} [opts.onAnimationSpeed]  — (speed) => void
 * @param {Function} [opts.onTogglePanel]     — (panelId) => void
 * @returns {Tray}
 */
function createTray(opts) {
  const icon = nativeImage.createFromPath(ICON_PATH);
  // Resize for tray (Linux typically uses 22x22 or 24x24)
  const resized = icon.resize({ width: 22, height: 22 });

  const tray = new Tray(resized);
  tray.setToolTip('Bantz Overlay — Super+Shift+B ile aç/kapat');

  // Left-click: toggle overlay
  tray.on('click', () => {
    if (opts.onToggleOverlay) opts.onToggleOverlay();
    updateContextMenu(tray, opts);
  });

  // Build and set the initial context menu
  updateContextMenu(tray, opts);

  // Show first-boot notification (once)
  showFirstBootNotification();

  console.log('[Tray] System tray created');
  return tray;
}

/**
 * Build the context menu based on current state.
 *
 * @param {Tray} tray
 * @param {object} opts
 */
function updateContextMenu(tray, opts) {
  const isVisible = opts.getVisibility ? opts.getVisibility() : true;
  const connState = opts.getConnectionState ? opts.getConnectionState() : 'disconnected';

  const connLabel = connState === 'connected'
    ? 'Bağlantı: Bağlı ✓'
    : connState === 'connecting'
      ? 'Bağlantı: Bağlanıyor ⟳'
      : 'Bağlantı: Bağlı Değil ✗';

  const template = [
    {
      label: isVisible ? 'Overlay Gizle' : 'Overlay Göster',
      click: () => {
        if (opts.onToggleOverlay) opts.onToggleOverlay();
        updateContextMenu(tray, opts);
      },
    },
    { type: 'separator' },
    {
      label: 'Paneller',
      submenu: [
        {
          label: 'Haber Akışı',
          type: 'checkbox',
          checked: true,
          click: (item) => { if (opts.onTogglePanel) opts.onTogglePanel('news-feed', item.checked); },
        },
        {
          label: 'Günlük Ajanda',
          type: 'checkbox',
          checked: true,
          click: (item) => { if (opts.onTogglePanel) opts.onTogglePanel('daily-tasks', item.checked); },
        },
        {
          label: 'Sistem Durumu',
          type: 'checkbox',
          checked: true,
          click: (item) => { if (opts.onTogglePanel) opts.onTogglePanel('system-status', item.checked); },
        },
      ],
    },
    {
      label: 'Efektler',
      submenu: [
        {
          label: 'Hafif',
          type: 'radio',
          checked: false,
          click: () => { if (opts.onEffectIntensity) opts.onEffectIntensity('subtle'); },
        },
        {
          label: 'Normal',
          type: 'radio',
          checked: true,
          click: () => { if (opts.onEffectIntensity) opts.onEffectIntensity('moderate'); },
        },
        {
          label: 'Yoğun',
          type: 'radio',
          checked: false,
          click: () => { if (opts.onEffectIntensity) opts.onEffectIntensity('intense'); },
        },
        { type: 'separator' },
        {
          label: 'Efektler Kapalı',
          type: 'radio',
          checked: false,
          click: () => { if (opts.onEffectIntensity) opts.onEffectIntensity('off'); },
        },
      ],
    },
    {
      label: 'Animasyon Hızı',
      submenu: [
        {
          label: '0.5x (Yavaş)',
          type: 'radio',
          checked: false,
          click: () => { if (opts.onAnimationSpeed) opts.onAnimationSpeed(0.5); },
        },
        {
          label: '1x (Normal)',
          type: 'radio',
          checked: true,
          click: () => { if (opts.onAnimationSpeed) opts.onAnimationSpeed(1); },
        },
        {
          label: '2x (Hızlı)',
          type: 'radio',
          checked: false,
          click: () => { if (opts.onAnimationSpeed) opts.onAnimationSpeed(2); },
        },
      ],
    },
    { type: 'separator' },
    {
      label: connLabel,
      enabled: false,
    },
    {
      label: 'Kısayol: Super+Shift+B',
      enabled: false,
    },
    { type: 'separator' },
    {
      label: "Bantz Overlay'i Kapat",
      click: () => {
        if (opts.onQuit) opts.onQuit();
      },
    },
  ];

  const contextMenu = Menu.buildFromTemplate(template);
  tray.setContextMenu(contextMenu);
}

/**
 * Show a one-time notification on first launch.
 */
function showFirstBootNotification() {
  // Use a simple flag — in production, persist to disk
  if (!global._bantzTrayNotified) {
    global._bantzTrayNotified = true;

    if (Notification.isSupported()) {
      const notification = new Notification({
        title: 'Bantz Overlay',
        body: 'Bantz Overlay aktif. Super+Shift+B ile aç/kapat.',
        icon: ICON_PATH,
        silent: true,
      });
      notification.show();
    }
  }
}

/**
 * Update tray tooltip with connection state.
 *
 * @param {Tray} tray
 * @param {string} state — 'connected' | 'connecting' | 'disconnected'
 */
function updateTrayConnectionState(tray, state) {
  const stateLabels = {
    connected: '● Bağlı',
    connecting: '○ Bağlanıyor...',
    disconnected: '✗ Bağlı Değil',
  };
  tray.setToolTip(`Bantz Overlay — ${stateLabels[state] || state}`);
}

module.exports = {
  createTray,
  updateContextMenu,
  updateTrayConnectionState,
};

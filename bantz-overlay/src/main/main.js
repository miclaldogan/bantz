/**
 * Bantz Overlay HUD — Main Process
 *
 * Creates a transparent, frameless, always-on-top Electron window
 * that renders the overlay HUD on the Linux desktop.
 *
 * Key features:
 * - Transparent background (rgba, no chrome)
 * - Always on top of other windows
 * - Click-through for areas without content
 * - Fullscreen-sized, positioned across the entire display
 * - Keyboard shortcut to toggle visibility (Super+Shift+B)
 */

const { app, BrowserWindow, globalShortcut, screen, ipcMain } = require('electron');
const path = require('path');
const { IPCClient, ConnectionState } = require('./ipc-client');
const { createTray, updateContextMenu, updateTrayConnectionState } = require('./tray');

let overlayWindow = null;
let tray = null;

/** Whether the overlay is currently visible. */
let isVisible = true;

/** IPC client instance for daemon communication. */
const ipcClient = new IPCClient({
  retryIntervalMs: 2000,
  maxRetries: 0, // retry forever
});

/**
 * Detect the compositor: X11 or Wayland.
 * Transparency support differs between the two.
 */
function detectDisplayServer() {
  const waylandDisplay = process.env.WAYLAND_DISPLAY;
  const xdgSession = (process.env.XDG_SESSION_TYPE || '').toLowerCase();
  if (waylandDisplay || xdgSession === 'wayland') {
    return 'wayland';
  }
  return 'x11';
}

/**
 * Create the overlay BrowserWindow.
 *
 * The window spans the entire primary display, is frameless,
 * transparent, always on top, and skips the taskbar / pager.
 */
function createOverlayWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;
  const displayServer = detectDisplayServer();

  console.log(`[Overlay] Display server: ${displayServer}`);
  console.log(`[Overlay] Work area: ${width}x${height}`);

  overlayWindow = new BrowserWindow({
    // Span the full work area
    x: 0,
    y: 0,
    width,
    height,

    // Frameless & transparent
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',

    // Always on top, skip taskbar / pager
    alwaysOnTop: true,
    skipTaskbar: true,

    // Resizable=false, not movable by user
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,

    // Don't show until ready
    show: false,

    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false, // required for net module access via preload
    },

    // Linux-specific: set window type to dock/toolbar so WMs treat it as overlay
    type: 'toolbar',
  });

  // Wayland-specific: Electron uses ozone on Wayland; additional flags
  // are handled via command-line switches below (app.commandLine).

  // Enable click-through on fully transparent regions
  overlayWindow.setIgnoreMouseEvents(true, { forward: true });

  // Load the overlay renderer
  overlayWindow.loadFile(path.join(__dirname, '../renderer/index.html'));

  // Show when ready to paint (avoids white flash)
  overlayWindow.once('ready-to-show', () => {
    overlayWindow.show();
    isVisible = true;
    console.log('[Overlay] Window ready and visible');
  });

  // Prevent the window from being closed by WM close button
  overlayWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      overlayWindow.hide();
      isVisible = false;
    }
  });

  overlayWindow.on('closed', () => {
    overlayWindow = null;
  });

  // Open DevTools in development mode (detached so overlay stays clean)
  if (process.env.NODE_ENV === 'development') {
    overlayWindow.webContents.openDevTools({ mode: 'detach' });
  }
}

/**
 * Toggle overlay visibility — bound to Super+Shift+B.
 */
function toggleOverlay() {
  if (!overlayWindow) return;

  if (isVisible) {
    overlayWindow.hide();
    isVisible = false;
    console.log('[Overlay] Hidden');
  } else {
    overlayWindow.show();
    isVisible = true;
    console.log('[Overlay] Shown');
  }
}

// ─── IPC: Renderer ↔ Main ───────────────────────────────────────────

/**
 * The renderer calls this to enable/disable mouse event forwarding.
 * When the cursor is over an interactive element (panel, sphere),
 * we stop ignoring mouse events so the user can click/hover.
 */
ipcMain.on('overlay:set-ignore-mouse', (_event, ignore) => {
  if (overlayWindow) {
    if (ignore) {
      overlayWindow.setIgnoreMouseEvents(true, { forward: true });
    } else {
      overlayWindow.setIgnoreMouseEvents(false);
    }
  }
});

/**
 * Renderer requests the current display dimensions.
 */
ipcMain.handle('overlay:get-display-info', () => {
  const primary = screen.getPrimaryDisplay();
  return {
    width: primary.workAreaSize.width,
    height: primary.workAreaSize.height,
    scaleFactor: primary.scaleFactor,
  };
});

/**
 * Renderer sends an event to the daemon.
 */
ipcMain.on('daemon:event', (_event, msg) => {
  ipcClient.send(msg);
});

/**
 * Renderer requests IPC reconnection.
 */
ipcMain.on('daemon:reconnect', () => {
  console.log('[Main] Reconnect requested by renderer');
  ipcClient.connect();
});

// ─── IPC: Daemon Socket ─────────────────────────────────────────────

/**
 * Start the IPC client and wire it to the renderer.
 */
function startIPCClient() {
  // Forward daemon messages to renderer
  ipcClient.on('message', (msg) => {
    if (overlayWindow && overlayWindow.webContents) {
      overlayWindow.webContents.send('daemon:message', msg);
    }
  });

  // Forward connection state to renderer
  ipcClient.on('state-change', (state) => {
    if (overlayWindow && overlayWindow.webContents) {
      overlayWindow.webContents.send('daemon:connection-state', state);
    }
    // Update tray tooltip
    if (tray) updateTrayConnectionState(tray, state);
    console.log(`[Main] IPC state: ${state}`);
  });

  ipcClient.on('error', (err) => {
    // Only log non-routine errors
    if (err.code !== 'ENOENT' && err.code !== 'ECONNREFUSED') {
      console.error('[Main] IPC error:', err.message);
    }
  });

  ipcClient.connect();
  console.log('[Main] IPC client started');
}

// ─── App Lifecycle ──────────────────────────────────────────────────

// Chromium flags for transparency on Linux
app.commandLine.appendSwitch('enable-transparent-visuals');
app.commandLine.appendSwitch('disable-gpu-compositing');

// On Wayland, Electron >= 28 uses Ozone; ensure correct platform
if (detectDisplayServer() === 'wayland') {
  app.commandLine.appendSwitch('ozone-platform', 'wayland');
}

app.whenReady().then(() => {
  createOverlayWindow();
  startIPCClient();

  // Create system tray
  tray = createTray({
    onToggleOverlay: toggleOverlay,
    onQuit: () => {
      app.isQuitting = true;
      app.quit();
    },
    getVisibility: () => isVisible,
    getConnectionState: () => ipcClient.state || 'disconnected',
    onEffectIntensity: (level) => {
      if (overlayWindow && overlayWindow.webContents) {
        overlayWindow.webContents.send('tray:effect-intensity', level);
      }
    },
    onAnimationSpeed: (speed) => {
      if (overlayWindow && overlayWindow.webContents) {
        overlayWindow.webContents.send('tray:animation-speed', speed);
      }
    },
    onTogglePanel: (panelId, visible) => {
      if (overlayWindow && overlayWindow.webContents) {
        overlayWindow.webContents.send('tray:toggle-panel', { panelId, visible });
      }
    },
  });

  // Register global toggle shortcut
  const registered = globalShortcut.register('Super+Shift+B', toggleOverlay);
  if (registered) {
    console.log('[Overlay] Toggle shortcut registered: Super+Shift+B');
  } else {
    console.warn('[Overlay] Failed to register toggle shortcut');
  }
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
  app.quit();
});

// Mark quitting so the close handler doesn't prevent exit
app.on('before-quit', () => {
  app.isQuitting = true;
  ipcClient.disconnect();
});

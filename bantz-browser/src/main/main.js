/**
 * Bantz Browser - Main Process
 * Electron main entry point
 */

const { app, BrowserWindow, ipcMain, session } = require('electron');
const path = require('path');
const net = require('net');
const fs = require('fs');

// Persistent profile path
const PROFILE_PATH = path.join(
  process.env.XDG_DATA_HOME || path.join(process.env.HOME, '.local/share'),
  'bantz',
  'browser_profile'
);

// Core daemon socket
const SOCKET_PATH = '/tmp/bantz_sessions/default.sock';

let mainWindow = null;

// Connection state
let coreConnected = false;
let connectionCheckInterval = null;

/**
 * Create the main browser window
 */
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 800,
    minHeight: 600,
    title: 'Bantz Browser',
    icon: path.join(__dirname, '../assets/icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      webviewTag: true,  // Enable webview for browser content
      partition: 'persist:bantz'  // Persistent session
    }
  });

  // Load the browser UI
  mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));

  // CRITICAL: Block ALL new window requests from main window
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    // Send URL to renderer to handle in webview
    mainWindow.webContents.send('navigate-to-url', url);
    return { action: 'deny' };  // Block new window
  });

  // Open DevTools in development
  if (process.env.NODE_ENV === 'development') {
    mainWindow.webContents.openDevTools();
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

/**
 * Check if Core daemon socket exists
 */
function checkCoreAvailable() {
  return fs.existsSync(SOCKET_PATH);
}

/**
 * Send command to Core daemon (request-response model)
 * Each command opens a new connection, sends request, gets response, closes
 */
function sendToCore(command, timeout = 30000) {
  return new Promise((resolve) => {
    // Check if socket file exists
    if (!checkCoreAvailable()) {
      coreConnected = false;
      notifyConnectionStatus(false);
      resolve({ ok: false, text: 'Bantz Core çalışmıyor. Daemon başlatın.' });
      return;
    }

    const client = new net.Socket();
    let responseData = '';
    let resolved = false;

    // Timeout handler
    const timeoutId = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        client.destroy();
        resolve({ ok: false, text: 'Komut zaman aşımına uğradı' });
      }
    }, timeout);

    client.connect(SOCKET_PATH, () => {
      // Connected - send command
      client.write(JSON.stringify({ command }));
    });

    client.on('data', (data) => {
      responseData += data.toString();
      // Try to parse complete JSON response
      try {
        const response = JSON.parse(responseData);
        if (!resolved) {
          resolved = true;
          clearTimeout(timeoutId);
          client.destroy();
          coreConnected = true;
          notifyConnectionStatus(true);
          resolve(response);
        }
      } catch (e) {
        // Incomplete JSON, wait for more data
      }
    });

    client.on('error', (err) => {
      if (!resolved) {
        resolved = true;
        clearTimeout(timeoutId);
        coreConnected = false;
        notifyConnectionStatus(false);
        resolve({ ok: false, text: `Bağlantı hatası: ${err.message}` });
      }
    });

    client.on('close', () => {
      // Normal close after response - don't log anything
    });
  });
}

/**
 * Notify renderer about connection status change
 */
function notifyConnectionStatus(connected) {
  if (mainWindow && mainWindow.webContents) {
    mainWindow.webContents.send('core:status', connected);
  }
}

/**
 * Periodic connection check (every 5 seconds)
 */
function startConnectionCheck() {
  // Initial check
  const available = checkCoreAvailable();
  coreConnected = available;
  
  // Periodic check
  connectionCheckInterval = setInterval(async () => {
    const wasConnected = coreConnected;
    const nowAvailable = checkCoreAvailable();
    
    if (nowAvailable && !wasConnected) {
      // Socket appeared - verify with status check
      const response = await sendToCore('__status__', 2000);
      coreConnected = response.ok;
    } else if (!nowAvailable && wasConnected) {
      coreConnected = false;
    }
    
    if (wasConnected !== coreConnected) {
      notifyConnectionStatus(coreConnected);
      console.log(`[Core] Status: ${coreConnected ? 'Connected' : 'Disconnected'}`);
    }
  }, 5000);
}

// IPC Handlers - Communication between renderer and main process

// Send command to Bantz Core
ipcMain.handle('bantz:command', async (event, command) => {
  return await sendToCore(command);
});

// Navigate webview
ipcMain.handle('browser:navigate', async (event, url) => {
  if (mainWindow) {
    mainWindow.webContents.send('browser:navigate', url);
  }
  return { ok: true };
});

// Get page info from webview
ipcMain.handle('browser:getPageInfo', async (event) => {
  // This will be handled by the webview's preload script
  return { ok: true };
});

// App lifecycle
app.whenReady().then(async () => {
  // Global safety: deny ALL new-window/popup creation (including webviews)
  app.on('web-contents-created', (_e, contents) => {
    try {
      contents.setWindowOpenHandler((details) => {
        try {
          console.log('[POPUP BLOCKED]', details.url, 'disposition=', details.disposition);
        } catch (_) {}

        if (mainWindow && mainWindow.webContents && details && details.url) {
          mainWindow.webContents.send('navigate-to-url', details.url);
        }
        return { action: 'deny' };
      });
    } catch (_) {
      // ignore
    }

    // Extra guard for older events
    try {
      contents.on('new-window', (e, url) => {
        try {
          console.log('[NEW-WINDOW EVENT]', url);
        } catch (_) {}
        e.preventDefault();
        if (mainWindow && mainWindow.webContents && url) {
          mainWindow.webContents.send('navigate-to-url', url);
        }
      });
    } catch (_) {
      // ignore
    }
  });

  // Set persistent session
  const ses = session.fromPartition('persist:bantz');
  
  // Start connection status checker
  startConnectionCheck();
  console.log('[Core] Connection checker started');

  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Cleanup on exit
app.on('before-quit', () => {
  if (connectionCheckInterval) {
    clearInterval(connectionCheckInterval);
  }
});

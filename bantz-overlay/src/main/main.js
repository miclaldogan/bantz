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

const { app, BrowserWindow, globalShortcut, screen, ipcMain, protocol, net } = require('electron');
const path = require('path');
const fs = require('fs');
const { IPCClient, ConnectionState } = require('./ipc-client');
const { createTray, updateContextMenu, updateTrayConnectionState } = require('./tray');

// Register custom protocol for ES module support (must be before app.ready)
protocol.registerSchemesAsPrivileged([{
  scheme: 'app',
  privileges: {
    standard: true,
    secure: true,
    supportFetchAPI: true,
    corsEnabled: true,
  }
}]);

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

  // Load the overlay renderer via custom protocol (enables ES modules)
  overlayWindow.loadURL('app://renderer/index.html');

  // Show when ready to paint (avoids white flash)
  // Forward renderer console to main process stdout
  overlayWindow.webContents.on('console-message', (event) => {
    const msg = event.message || '';
    const lvl = event.level ?? 1;
    const prefix = ['V', 'I', 'W', 'E'][lvl] || 'I';
    console.log(`[R:${prefix}] ${msg}`);
  });

  // Debug: check renderer state after load
  overlayWindow.webContents.on('did-finish-load', () => {
    console.log('[Main] did-finish-load fired');
    overlayWindow.webContents.executeJavaScript(`
      JSON.stringify({
        overlayAPI: typeof window.overlayAPI,
        TerminalPanel: typeof window.TerminalPanel,
        NewsFeedPanel: typeof window.NewsFeedPanel,
        DailyTasksPanel: typeof window.DailyTasksPanel,
        GlitchEffects: typeof window.GlitchEffects,
        PanelLayoutEngine: typeof window.PanelLayoutEngine,
        hudPanel: !!document.getElementById('hud-panel'),
        sphereContainer: !!document.getElementById('sphere-container'),
        panelCount: document.querySelectorAll('.terminal-panel').length,
        canvasCount: document.querySelectorAll('canvas').length,
      })
    `).then(r => console.log('[Main] Renderer state:', r)).catch(e => console.error('[Main] JS exec failed:', e));
  });

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

// ─── IPC: System Metrics ────────────────────────────────────────────
const os = require('os');

/**
 * Get real system metrics (CPU, RAM, Disk, Uptime).
 */
ipcMain.handle('system:get-metrics', async () => {
  try {
    // CPU usage: measure over 500ms
    const cpus1 = os.cpus();
    await new Promise(r => setTimeout(r, 500));
    const cpus2 = os.cpus();

    let totalIdle = 0, totalTick = 0;
    for (let i = 0; i < cpus2.length; i++) {
      const c1 = cpus1[i].times;
      const c2 = cpus2[i].times;
      const idle = c2.idle - c1.idle;
      const total = (c2.user - c1.user) + (c2.nice - c1.nice) +
                    (c2.sys - c1.sys) + (c2.irq - c1.irq) + idle;
      totalIdle += idle;
      totalTick += total;
    }
    const cpuPercent = Math.round((1 - totalIdle / totalTick) * 100);

    // RAM
    const totalMem = os.totalmem();
    const freeMem = os.freemem();
    const ramPercent = Math.round(((totalMem - freeMem) / totalMem) * 100);

    // Disk — use df command on Linux
    let diskPercent = 0;
    try {
      const { execSync } = require('child_process');
      const dfOutput = execSync('df / --output=pcent | tail -1', { encoding: 'utf8' });
      diskPercent = parseInt(dfOutput.trim().replace('%', ''), 10) || 0;
    } catch { diskPercent = 0; }

    // Uptime
    const uptimeSeconds = Math.floor(os.uptime());

    return { cpu: cpuPercent, ram: ramPercent, disk: diskPercent, uptime_seconds: uptimeSeconds };
  } catch (err) {
    console.error('[Main] System metrics error:', err.message);
    return { cpu: 0, ram: 0, disk: 0, uptime_seconds: 0 };
  }
});

// ─── IPC: Open External URL ─────────────────────────────────────

/**
 * Open a URL in the user's default browser.
 */
ipcMain.handle('shell:open-external', async (_event, url) => {
  if (!url || typeof url !== 'string') return false;
  // Basic URL validation
  if (!url.startsWith('http://') && !url.startsWith('https://')) return false;
  try {
    const { shell } = require('electron');
    await shell.openExternal(url);
    console.log(`[Main] Opened external: ${url.slice(0, 80)}`);
    return true;
  } catch (err) {
    console.error('[Main] Failed to open URL:', err.message);
    return false;
  }
});

/**
 * Get weather data from wttr.in (free, no API key required).
 * Location priority: BANTZ_WEATHER_LOCATION → BANTZ_LOCATION → BANTZ_DEFAULT_LOCATION → "Corum"
 */
ipcMain.handle('system:get-weather', async () => {
  try {
    const { net } = require('electron');

    // Read location from bantz env file if not in process.env
    let location = process.env.BANTZ_WEATHER_LOCATION
      || process.env.BANTZ_LOCATION
      || process.env.BANTZ_DEFAULT_LOCATION
      || '';

    if (!location) {
      try {
        const fs = require('fs');
        const path = require('path');
        const envPath = path.join(require('os').homedir(), '.config', 'bantz', 'env');
        if (fs.existsSync(envPath)) {
          const envContent = fs.readFileSync(envPath, 'utf8');
          for (const line of envContent.split('\n')) {
            const trimmed = line.trim();
            if (trimmed.startsWith('#') || !trimmed.includes('=')) continue;
            const [key, ...rest] = trimmed.split('=');
            const val = rest.join('=').trim();
            if ((key.trim() === 'BANTZ_WEATHER_LOCATION' || key.trim() === 'BANTZ_LOCATION' || key.trim() === 'BANTZ_DEFAULT_LOCATION') && val) {
              location = val;
              break;
            }
          }
        }
      } catch {}
    }

    // Final fallback
    if (!location) location = 'Corum';

    console.log(`[Main] Weather location: ${location}`);
    return new Promise((resolve) => {
      const request = net.request(`https://wttr.in/${encodeURIComponent(location)}?format=j1`);
      let body = '';
      request.on('response', (response) => {
        response.on('data', (chunk) => { body += chunk.toString(); });
        response.on('end', () => {
          try {
            const data = JSON.parse(body);
            const current = data.current_condition?.[0] || {};
            const area = data.nearest_area?.[0] || {};
            resolve({
              temperature: parseInt(current.temp_C, 10) || 0,
              feelsLike: parseInt(current.FeelsLikeC, 10) || 0,
              condition: (current.weatherDesc?.[0]?.value || 'unknown').toLowerCase(),
              humidity: parseInt(current.humidity, 10) || 0,
              wind_speed: parseInt(current.windspeedKmph, 10) || 0,
              windDir: current.winddir16Point || '',
              location: area.areaName?.[0]?.value || 'Unknown',
              country: area.country?.[0]?.value || '',
              uvIndex: parseInt(current.uvIndex, 10) || 0,
              visibility: parseInt(current.visibility, 10) || 0,
            });
          } catch (e) {
            console.error('[Main] Weather parse error:', e.message);
            resolve(null);
          }
        });
      });
      request.on('error', (err) => {
        console.error('[Main] Weather fetch error:', err.message);
        resolve(null);
      });
      request.end();
    });
  } catch (err) {
    console.error('[Main] Weather error:', err.message);
    return null;
  }
});

// ─── IPC: News RSS Feed ─────────────────────────────────────────────

const NEWS_RSS_FEEDS = [
  { url: 'https://www.trthaber.com/sondakika_articles.rss', source: 'TRT Haber' },
  { url: 'https://feeds.bbci.co.uk/news/technology/rss.xml', source: 'BBC Tech' },
  { url: 'https://hnrss.org/newest?count=5', source: 'Hacker News' },
];

/**
 * Fetch and parse a single RSS feed, return array of articles.
 */
function fetchRSSFeed(feedUrl, sourceName) {
  return new Promise((resolve) => {
    try {
      const request = net.request(feedUrl);
      let body = '';

      request.on('response', (response) => {
        response.on('data', (chunk) => { body += chunk.toString(); });
        response.on('end', () => {
          try {
            const articles = parseRSSXML(body, sourceName);
            resolve(articles);
          } catch {
            resolve([]);
          }
        });
      });

      request.on('error', () => resolve([]));
      request.end();

      // Timeout after 8s
      setTimeout(() => resolve([]), 8000);
    } catch {
      resolve([]);
    }
  });
}

/**
 * Simple XML RSS parser — extracts <item> elements.
 * No external dependency needed.
 */
function parseRSSXML(xml, sourceName) {
  const articles = [];
  // Match <item>...</item> blocks
  const itemRegex = /<item[^>]*>([\s\S]*?)<\/item>/gi;
  let match;

  while ((match = itemRegex.exec(xml)) !== null && articles.length < 8) {
    const block = match[1];
    const title = extractTag(block, 'title');
    const description = extractTag(block, 'description');
    const link = extractTag(block, 'link');
    const pubDate = extractTag(block, 'pubDate');

    if (title) {
      articles.push({
        title: decodeHTMLEntities(title),
        source: sourceName,
        summary: description ? decodeHTMLEntities(description).replace(/<[^>]+>/g, '').slice(0, 200) : '',
        link: link || '',
        pubDate: pubDate || new Date().toISOString(),
      });
    }
  }

  return articles;
}

function extractTag(xml, tagName) {
  // Handle CDATA sections
  const cdataRegex = new RegExp(`<${tagName}[^>]*><!\\[CDATA\\[([\\s\\S]*?)\\]\\]><\\/${tagName}>`, 'i');
  const cdataMatch = cdataRegex.exec(xml);
  if (cdataMatch) return cdataMatch[1].trim();

  const regex = new RegExp(`<${tagName}[^>]*>([\\s\\S]*?)<\\/${tagName}>`, 'i');
  const m = regex.exec(xml);
  return m ? m[1].trim() : '';
}

function decodeHTMLEntities(str) {
  return str
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'");
}

ipcMain.handle('news:get-feed', async () => {
  try {
    console.log('[Main] Fetching RSS news feeds...');
    const feedPromises = NEWS_RSS_FEEDS.map(f => fetchRSSFeed(f.url, f.source));
    const results = await Promise.all(feedPromises);

    // Flatten all feeds and sort by pubDate (newest first)
    const allArticles = results.flat();
    allArticles.sort((a, b) => {
      const dateA = new Date(a.pubDate || 0);
      const dateB = new Date(b.pubDate || 0);
      return dateB - dateA;
    });

    // Return top 15 articles
    const top = allArticles.slice(0, 15);
    console.log(`[Main] Fetched ${top.length} news articles from ${results.filter(r => r.length > 0).length} feeds`);
    return top;
  } catch (err) {
    console.error('[Main] News fetch error:', err.message);
    return null;
  }
});

// ─── IPC: Article Image Scraper ─────────────────────────────────────

/**
 * Fetch Open Graph image from a URL for news article preview.
 */
ipcMain.handle('news:get-article-image', async (_event, url) => {
  if (!url) return null;
  try {
    return new Promise((resolve) => {
      const request = net.request(url);
      let body = '';

      request.on('response', (response) => {
        // Only process HTML
        const ct = response.headers['content-type'] || '';
        if (!ct.includes('text/html') && body.length === 0) {
          // Try to read anyway
        }
        response.on('data', (chunk) => {
          body += chunk.toString();
          // Stop after 50KB — we just need the <head>
          if (body.length > 50000) request.abort();
        });
        response.on('end', () => {
          // Extract og:image
          const ogMatch = body.match(/<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)["']/i)
            || body.match(/<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image["']/i);
          if (ogMatch) {
            resolve(ogMatch[1]);
          } else {
            // Try twitter:image
            const twMatch = body.match(/<meta[^>]+name=["']twitter:image["'][^>]+content=["']([^"']+)["']/i);
            resolve(twMatch ? twMatch[1] : null);
          }
        });
      });

      request.on('error', () => resolve(null));
      request.end();

      // Timeout
      setTimeout(() => resolve(null), 5000);
    });
  } catch {
    return null;
  }
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
    // Only log non-routine errors (suppress flood)
    if (err.code !== 'ENOENT' && err.code !== 'ECONNREFUSED' && err.code !== 'ECONNRESET') {
      console.error('[Main] IPC error:', err.message);
    }
  });

  // Delay IPC connect to let renderer init settle
  setTimeout(() => {
    ipcClient.connect();
    console.log('[Main] IPC client started');
  }, 3000);
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
  // Register the 'app' protocol handler to serve local files
  // This enables ES module imports to work correctly
  const rendererPath = path.join(__dirname, '../renderer');
  protocol.handle('app', (request) => {
    const url = new URL(request.url);
    // Resolve file path from the renderer directory
    let filePath = path.join(rendererPath, decodeURIComponent(url.pathname));
    
    // Determine MIME type
    const ext = path.extname(filePath).toLowerCase();
    const mimeTypes = {
      '.html': 'text/html',
      '.js': 'application/javascript',
      '.css': 'text/css',
      '.json': 'application/json',
      '.png': 'image/png',
      '.svg': 'image/svg+xml',
      '.woff': 'font/woff',
      '.woff2': 'font/woff2',
    };
    const mimeType = mimeTypes[ext] || 'application/octet-stream';
    
    try {
      const data = fs.readFileSync(filePath);
      return new Response(data, {
        headers: { 'Content-Type': mimeType },
      });
    } catch (err) {
      console.error(`[Protocol] File not found: ${filePath}`);
      return new Response('Not Found', { status: 404 });
    }
  });

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

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
    console.log(`[Main] Opened external: ${sanitizeLogValue(url).slice(0, 80)}`);
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

    // Sanitize location: allow only safe city-name characters (letters, digits,
    // spaces, commas, dots, hyphens, Turkish chars). Prevents request forgery
    // via malicious env values. (CodeQL: js/file-access-to-http)
    location = location.replace(/[^a-zA-Z\u00e7\u00c7\u011f\u011e\u0131\u0130\u00f6\u00d6\u015f\u015e\u00fc\u00dc0-9\s,.\-]/g, '').trim().slice(0, 100) || 'Corum';

    console.log(`[Main] Weather location: ${sanitizeLogValue(location)}`);
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
        console.error('[Main] Weather fetch error:', sanitizeLogValue(err.message));
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
        summary: description ? stripHtmlTags(decodeHTMLEntities(description)).slice(0, 200) : '',
        link: link || '',
        pubDate: pubDate || new Date().toISOString(),
      });
    }
  }

  return articles;
}

/**
 * Iteratively strip all HTML tags to prevent incomplete sanitization.
 * A single-pass replace can leave tags like '<scr<a>ipt>' intact.
 */
function stripHtmlTags(str) {
  let prev;
  do {
    prev = str;
    str = str.replace(/<[^>]+>/g, '');
  } while (str !== prev);
  return str;
}

/**
 * Sanitize a value before logging to prevent log injection
 * (newlines, control characters that could forge log entries).
 */
function sanitizeLogValue(val) {
  if (val == null) return '';
  return String(val).replace(/[\r\n\t]/g, ' ').slice(0, 500);
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
  // Decode &amp; LAST to prevent double-unescaping:
  // e.g. '&amp;lt;' → '&lt;' → '<' would be a double-unescape bug.
  return str
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, '&');
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

  // Forward user text commands from renderer → daemon
  ipcMain.on('daemon:command', (_event, text) => {
    console.log(`[Main] Forwarding command to daemon: ${text.substring(0, 80)}`);
    ipcClient.send({ type: 'command', text });
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

// ─── First-Run Auth Detection ───────────────────────────────────────

/**
 * Check for required auth tokens on first run.
 * If Google or GitHub auth is missing, guide user through setup.
 */
async function checkFirstRunAuth() {
  const os = require('os');
  const { execSync, exec } = require('child_process');
  const homedir = os.homedir();
  const results = { google: false, github: false, needsSetup: false };

  // 1. Check Google OAuth tokens
  const googleTokenPaths = [
    path.join(homedir, '.config', 'bantz', 'google', 'token.json'),
    path.join(homedir, '.config', 'bantz', 'google', 'gmail_token.json'),
    path.join(homedir, '.config', 'bantz', 'google', 'google_unified_token.json'),
  ];

  const hasGoogleToken = googleTokenPaths.some(p => {
    try { return fs.existsSync(p) && fs.statSync(p).size > 10; } catch { return false; }
  });
  results.google = hasGoogleToken;

  // 2. Check GitHub CLI auth
  try {
    execSync('gh auth status', { stdio: 'pipe', timeout: 5000 });
    results.github = true;
  } catch {
    results.github = false;
  }

  // 3. Check Google client_secret exists
  const clientSecretPath = path.join(homedir, '.config', 'bantz', 'google', 'client_secret.json');
  const hasClientSecret = fs.existsSync(clientSecretPath);

  console.log(`[Auth] Google: ${results.google ? '✓' : '✗'}, GitHub: ${results.github ? '✓' : '✗'}, ClientSecret: ${hasClientSecret ? '✓' : '✗'}`);

  // If any auth is missing, notify renderer and trigger setup
  if (!results.google || !results.github) {
    results.needsSetup = true;

    // Notify renderer about auth status (for UI indicator)
    if (overlayWindow && overlayWindow.webContents) {
      overlayWindow.webContents.send('auth:status', results);
    }

    // Run Google OAuth if missing and client_secret exists
    if (!results.google && hasClientSecret) {
      console.log('[Auth] Google auth missing — launching consent flow...');
      try {
        // Find project root (2 levels up from main.js)
        const projectRoot = path.resolve(__dirname, '..', '..', '..');
        const venvPython = path.join(projectRoot, '..', '.venv', 'bin', 'python3');
        const sysPython = 'python3';
        const pythonCmd = fs.existsSync(venvPython) ? venvPython : sysPython;

        // Run the consent wizard non-interactively for calendar + gmail
        exec(
          `${pythonCmd} -c "
from bantz.connectors.google.auth_manager import get_auth_manager, setup_auth_manager
setup_auth_manager()
mgr = get_auth_manager()
mgr.ensure_scope('calendar')
mgr.ensure_scope('gmail')
print('AUTH_OK')
"`,
          { cwd: projectRoot, timeout: 120000, env: { ...process.env, PYTHONPATH: path.join(projectRoot, 'src') } },
          (err, stdout, stderr) => {
            if (err) {
              console.error('[Auth] Google consent failed:', err.message);
            } else if (stdout.includes('AUTH_OK')) {
              console.log('[Auth] Google auth completed successfully');
              results.google = true;
              if (overlayWindow && overlayWindow.webContents) {
                overlayWindow.webContents.send('auth:status', { ...results, google: true });
              }
            }
          }
        );
      } catch (e) {
        console.error('[Auth] Google auth launch error:', e.message);
      }
    }

    // Run GitHub auth if missing
    if (!results.github) {
      console.log('[Auth] GitHub auth missing — launching gh auth login...');
      try {
        exec('gh auth login --web -p ssh', { timeout: 120000 }, (err, stdout) => {
          if (err) {
            console.error('[Auth] GitHub auth failed:', err.message);
          } else {
            console.log('[Auth] GitHub auth completed');
            results.github = true;
            if (overlayWindow && overlayWindow.webContents) {
              overlayWindow.webContents.send('auth:status', { ...results, github: true });
            }
          }
        });
      } catch (e) {
        console.error('[Auth] GitHub auth launch error:', e.message);
      }
    }
  } else {
    console.log('[Auth] All auth tokens present — skipping setup');
  }

  return results;
}

// ─── Environment Loading ────────────────────────────────────────────

/**
 * Load environment variables from config/.env if not already set.
 */
function loadEnvFile() {
  const projectRoot = path.resolve(__dirname, '..', '..', '..');
  const envPath = path.join(projectRoot, 'config', '.env');

  if (!fs.existsSync(envPath)) {
    console.log('[Env] No config/.env found, using system environment');
    return;
  }

  try {
    const lines = fs.readFileSync(envPath, 'utf8').split('\n');
    let loaded = 0;
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const eqIdx = trimmed.indexOf('=');
      if (eqIdx <= 0) continue;
      const key = trimmed.substring(0, eqIdx).trim();
      const val = trimmed.substring(eqIdx + 1).trim();
      // Don't override existing env vars
      if (!process.env[key]) {
        process.env[key] = val;
        loaded++;
      }
    }
    console.log(`[Env] Loaded ${loaded} vars from config/.env`);
  } catch (e) {
    console.warn('[Env] Failed to load .env:', e.message);
  }
}

// Chromium flags for transparency on Linux
app.commandLine.appendSwitch('enable-transparent-visuals');
app.commandLine.appendSwitch('disable-gpu-compositing');

// On Wayland, Electron >= 28 uses Ozone; ensure correct platform
if (detectDisplayServer() === 'wayland') {
  app.commandLine.appendSwitch('ozone-platform', 'wayland');
}

app.whenReady().then(async () => {
  // Load environment from config/.env
  loadEnvFile();

  // Register the 'app' protocol handler to serve local files
  // This enables ES module imports to work correctly
  const rendererPath = path.join(__dirname, '../renderer');
  protocol.handle('app', (request) => {
    const url = new URL(request.url);
    // Resolve file path from the renderer directory
    let filePath = path.join(rendererPath, decodeURIComponent(url.pathname));

    // Prevent path traversal: resolved path must stay within rendererPath
    const resolved = path.resolve(filePath);
    if (!resolved.startsWith(path.resolve(rendererPath))) {
      console.error('[Protocol] Path traversal blocked');
      return new Response('Forbidden', { status: 403 });
    }
    filePath = resolved;

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
      console.error(`[Protocol] File not found: ${sanitizeLogValue(filePath)}`);
      return new Response('Not Found', { status: 404 });
    }
  });

  createOverlayWindow();
  startIPCClient();

  // Check first-run auth (non-blocking — runs in background)
  checkFirstRunAuth().catch(e => console.warn('[Auth] Check failed:', e.message));

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


// ─── IPC: GitHub Activity Feed ──────────────────────────────────────

/**
 * Fetch GitHub activity feed using the GitHub Events API and Notifications API.
 * Uses GITHUB_TOKEN from environment for authenticated requests.
 * Falls back to `gh` CLI token if available.
 */

const GITHUB_OWNER = process.env.GITHUB_OWNER || '';
const GITHUB_REPOS = (process.env.GITHUB_REPOS || '').split(',').map(s => s.trim()).filter(Boolean);

function getGitHubToken() {
  // Prefer explicit env var
  if (process.env.GITHUB_TOKEN) return process.env.GITHUB_TOKEN;

  // Try reading gh CLI config
  try {
    const os = require('os');
    const path = require('path');
    const fs = require('fs');
    const hostsPath = path.join(os.homedir(), '.config', 'gh', 'hosts.yml');
    if (fs.existsSync(hostsPath)) {
      const hostsContent = fs.readFileSync(hostsPath, 'utf8');
      // Simple YAML parse for oauth_token
      const match = hostsContent.match(/oauth_token:\s*(.+)/);
      if (match) return match[1].trim();
    }
  } catch (e) {
    // Ignore
  }
  return null;
}

function githubFetch(urlPath) {
  return new Promise((resolve, reject) => {
    const { net } = require('electron');
    const token = getGitHubToken();
    const url = urlPath.startsWith('https://') ? urlPath : 'https://api.github.com' + urlPath;

    const request = net.request({
      url,
      method: 'GET',
    });

    request.setHeader('Accept', 'application/vnd.github.v3+json');
    request.setHeader('User-Agent', 'Bantz-Overlay/1.0');
    if (token) {
      request.setHeader('Authorization', 'Bearer ' + token);
    }

    let body = '';

    request.on('response', (response) => {
      if (response.statusCode !== 200) {
        reject(new Error('GitHub API ' + response.statusCode));
        return;
      }
      response.on('data', (chunk) => { body += chunk.toString(); });
      response.on('end', () => {
        try {
          resolve(JSON.parse(body));
        } catch (e) {
          reject(new Error('JSON parse error'));
        }
      });
    });

    request.on('error', reject);
    request.end();
  });
}

ipcMain.handle('github:get-feed', async () => {
  const token = getGitHubToken();
  if (!token) {
    console.warn('[Main] No GitHub token available — skipping feed');
    return { events: [], unreadCount: 0 };
  }

  try {
    console.log('[Main] Fetching GitHub activity feed...');

    const results = { events: [], unreadCount: 0 };

    // 1. Fetch user's received events (activity from repos they watch)
    try {
      const events = await githubFetch('/users/' + (GITHUB_OWNER || 'miclaldogan') + '/received_events?per_page=30');
      if (Array.isArray(events)) {
        for (const ev of events) {
          const mapped = mapGitHubEvent(ev);
          if (mapped) results.events.push(mapped);
        }
      }
    } catch (e) {
      console.warn('[Main] GitHub events fetch failed:', sanitizeLogValue(e.message));
    }

    // 2. Fetch notifications
    try {
      const notifications = await githubFetch('/notifications?per_page=20');
      if (Array.isArray(notifications)) {
        results.unreadCount = notifications.filter(n => n.unread).length;
        for (const notif of notifications.slice(0, 10)) {
          results.events.push({
            type: 'notification',
            repo: notif.repository?.full_name || '',
            title: notif.subject?.title || 'Notification',
            actor: '',
            url: notif.subject?.url
              ? notif.subject.url.replace('api.github.com/repos', 'github.com').replace('/pulls/', '/pull/')
              : '',
            ts: notif.updated_at || notif.last_read_at || new Date().toISOString(),
            id: 'notif-' + notif.id,
          });
        }
      }
    } catch (e) {
      console.warn('[Main] GitHub notifications fetch failed:', sanitizeLogValue(e.message));
    }

    // 3. If specific repos configured, fetch their events
    for (const repo of GITHUB_REPOS.slice(0, 3)) {
      try {
        const repoEvents = await githubFetch('/repos/' + repo + '/events?per_page=10');
        if (Array.isArray(repoEvents)) {
          for (const ev of repoEvents) {
            const mapped = mapGitHubEvent(ev);
            if (mapped) results.events.push(mapped);
          }
        }
      } catch (e) {
        console.warn('[Main] GitHub repo events failed for ' + sanitizeLogValue(repo) + ':', sanitizeLogValue(e.message));
      }
    }

    // Sort by timestamp (newest first) and deduplicate
    const seen = new Set();
    results.events = results.events
      .filter(e => {
        if (seen.has(e.id)) return false;
        seen.add(e.id);
        return true;
      })
      .sort((a, b) => new Date(b.ts) - new Date(a.ts))
      .slice(0, 40);

    console.log('[Main] GitHub feed: ' + sanitizeLogValue(results.events.length) + ' events, ' + sanitizeLogValue(results.unreadCount) + ' unread');
    return results;
  } catch (err) {
    console.error('[Main] GitHub feed error:', err.message);
    return { events: [], unreadCount: 0 };
  }
});

/**
 * Map a GitHub API event to our internal format.
 */
function mapGitHubEvent(ev) {
  if (!ev || !ev.type) return null;

  const repo = ev.repo?.name || '';
  const actor = ev.actor?.login || '';
  const ts = ev.created_at || new Date().toISOString();
  const id = ev.id ? 'ev-' + ev.id : 'ev-' + Date.now();
  const payload = ev.payload || {};

  switch (ev.type) {
    case 'PushEvent':
      return {
        type: 'push',
        repo,
        title: (payload.commits && payload.commits.length > 0)
          ? payload.commits[0].message.split('\n')[0]
          : 'Push',
        actor,
        url: 'https://github.com/' + repo + '/commits/' + (payload.head || 'main'),
        ts,
        id,
        branch: (payload.ref || '').replace('refs/heads/', ''),
      };

    case 'PullRequestEvent':
      return {
        type: 'pull_request',
        repo,
        title: payload.pull_request?.title || 'Pull Request',
        actor,
        url: payload.pull_request?.html_url || 'https://github.com/' + repo,
        ts,
        id,
        number: payload.pull_request?.number,
      };

    case 'IssuesEvent':
      return {
        type: 'issue',
        repo,
        title: payload.issue?.title || 'Issue',
        actor,
        url: payload.issue?.html_url || 'https://github.com/' + repo,
        ts,
        id,
        number: payload.issue?.number,
      };

    case 'IssueCommentEvent':
    case 'PullRequestReviewCommentEvent':
    case 'CommitCommentEvent':
      return {
        type: 'comment',
        repo,
        title: payload.comment?.body?.substring(0, 80) || 'Comment',
        actor,
        url: payload.comment?.html_url || 'https://github.com/' + repo,
        ts,
        id,
      };

    case 'PullRequestReviewEvent':
      return {
        type: 'review',
        repo,
        title: 'Review on ' + (payload.pull_request?.title || 'PR'),
        actor,
        url: payload.review?.html_url || 'https://github.com/' + repo,
        ts,
        id,
      };

    case 'ReleaseEvent':
      return {
        type: 'release',
        repo,
        title: payload.release?.name || payload.release?.tag_name || 'Release',
        actor,
        url: payload.release?.html_url || 'https://github.com/' + repo,
        ts,
        id,
      };

    case 'WatchEvent':
      return {
        type: 'star',
        repo,
        title: 'Starred ' + repo,
        actor,
        url: 'https://github.com/' + repo,
        ts,
        id,
      };

    case 'ForkEvent':
      return {
        type: 'fork',
        repo,
        title: 'Forked to ' + (payload.forkee?.full_name || ''),
        actor,
        url: payload.forkee?.html_url || 'https://github.com/' + repo,
        ts,
        id,
      };

    case 'CreateEvent':
      return {
        type: 'push',
        repo,
        title: 'Created ' + (payload.ref_type || 'ref') + ' ' + (payload.ref || ''),
        actor,
        url: 'https://github.com/' + repo,
        ts,
        id,
        branch: payload.ref || '',
      };

    default:
      return {
        type: 'default',
        repo,
        title: ev.type.replace(/Event$/, ''),
        actor,
        url: 'https://github.com/' + repo,
        ts,
        id,
      };
  }
}

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

/**
 * Bantz Overlay HUD — Preload Script
 *
 * Secure bridge between the overlay renderer and the main process.
 * Exposes a minimal API surface via contextBridge.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('overlayAPI', {
  // ─── Mouse Interaction ──────────────────────────────────────────
  /**
   * Tell the main process to stop ignoring mouse events (interactive region).
   */
  enableMouse: () => ipcRenderer.send('overlay:set-ignore-mouse', false),

  /**
   * Tell the main process to resume ignoring mouse events (transparent region).
   */
  disableMouse: () => ipcRenderer.send('overlay:set-ignore-mouse', true),

  // ─── Display Info ───────────────────────────────────────────────
  /**
   * Get the primary display size and scale factor.
   * @returns {Promise<{width: number, height: number, scaleFactor: number}>}
   */
  getDisplayInfo: () => ipcRenderer.invoke('overlay:get-display-info'),

  // ─── IPC Bridge (daemon messages) ──────────────────────────────
  /**
   * Register a callback for IPC messages from the daemon.
   * Removes any previously registered listener to prevent memory leaks.
   * @param {(message: object) => void} callback
   */
  onDaemonMessage: (callback) => {
    ipcRenderer.removeAllListeners('daemon:message');
    ipcRenderer.on('daemon:message', (_event, message) => callback(message));
  },

  /**
   * Send an event message to the daemon (via main process).
   * @param {object} event
   */
  sendDaemonEvent: (event) => ipcRenderer.send('daemon:event', event),

  /**
   * Send a text command to the daemon for processing.
   * @param {string} text - The user's text input
   */
  sendCommand: (text) => ipcRenderer.send('daemon:command', text),

  /**
   * Register a callback for daemon connection state changes.
   * State: 'connected' | 'connecting' | 'disconnected'
   * @param {(state: string) => void} callback
   */
  onDaemonConnectionState: (callback) => {
    ipcRenderer.removeAllListeners('daemon:connection-state');
    ipcRenderer.on('daemon:connection-state', (_event, state) => callback(state));
  },

  // ─── Lifecycle ─────────────────────────────────────────────────
  /**
   * Listen for overlay visibility changes.
   * @param {(visible: boolean) => void} callback
   */
  onVisibilityChange: (callback) => {
    ipcRenderer.removeAllListeners('overlay:visibility');
    ipcRenderer.on('overlay:visibility', (_event, visible) => callback(visible));
  },

  // ─── Tray Commands ────────────────────────────────────────────
  /**
   * Listen for effect intensity changes from system tray.
   * @param {(level: string) => void} callback
   */
  onEffectIntensity: (callback) => {
    ipcRenderer.removeAllListeners('tray:effect-intensity');
    ipcRenderer.on('tray:effect-intensity', (_event, level) => callback(level));
  },

  /**
   * Listen for animation speed changes from system tray.
   * @param {(speed: number) => void} callback
   */
  onAnimationSpeed: (callback) => {
    ipcRenderer.removeAllListeners('tray:animation-speed');
    ipcRenderer.on('tray:animation-speed', (_event, speed) => callback(speed));
  },

  /**
   * Listen for panel toggle commands from system tray.
   * @param {(data: {panelId: string, visible: boolean}) => void} callback
   */
  onTogglePanel: (callback) => {
    ipcRenderer.removeAllListeners('tray:toggle-panel');
    ipcRenderer.on('tray:toggle-panel', (_event, data) => callback(data));
  },

  /**
   * Request IPC reconnection.
   */
  reconnect: () => ipcRenderer.send('daemon:reconnect'),

  // ─── Auth Status ──────────────────────────────────────────────
  /**
   * Listen for auth status updates (first-run detection).
   * @param {(status: {google: boolean, github: boolean, needsSetup: boolean}) => void} callback
   */
  onAuthStatus: (callback) => {
    ipcRenderer.removeAllListeners('auth:status');
    ipcRenderer.on('auth:status', (_event, status) => callback(status));
  },

  /**
   * Get current Google + GitHub auth status synchronously.
   * @returns {Promise<{google: boolean, github: boolean, hasClientSecret: boolean, needsSetup: boolean}>}
   */
  getAuthStatus: () => ipcRenderer.invoke('auth:get-status'),

  /**
   * Trigger Google OAuth flow for given services.
   * @param {string[]} [scopes] - e.g. ['calendar', 'gmail', 'classroom']. Defaults to all.
   * @returns {Promise<{success: boolean, scopes?: string[], error?: string}>}
   */
  requestGoogleOAuth: (scopes) => ipcRenderer.invoke('auth:request-google-oauth', scopes),

  /**
   * Open a Google Classroom enrollment link in the default browser.
   * @param {string} enrollmentCode - The Classroom course enrollment code.
   * @returns {Promise<boolean>}
   */
  openClassroomEnrollment: (enrollmentCode) => ipcRenderer.invoke('classroom:open-enrollment', enrollmentCode),

  // ─── System Data ─────────────────────────────────────────────
  /**
   * Get real system metrics (CPU, RAM, Disk, Uptime).
   * @returns {Promise<{cpu: number, ram: number, disk: number, uptime_seconds: number}>}
   */
  getSystemMetrics: () => ipcRenderer.invoke('system:get-metrics'),

  /**
   * Get weather data from wttr.in (IP-based location).
   * @returns {Promise<{temperature: number, condition: string, humidity: number, wind_speed: number, location: string}|null>}
   */
  getWeather: () => ipcRenderer.invoke('system:get-weather'),

  /**
   * Get news articles from RSS feeds.
   * @returns {Promise<Array<{title: string, source: string, summary: string, link: string, pubDate: string}>|null>}
   */
  getNewsFeed: () => ipcRenderer.invoke('news:get-feed'),

  /**
   * Fetch OG image URL from a news article page.
   * @param {string} url - Article URL
   * @returns {Promise<string|null>} Image URL or null
   */
  getArticleImage: (url) => ipcRenderer.invoke('news:get-article-image', url),

  /**
   * Open a URL in the user's default browser.
   * @param {string} url - URL to open
   * @returns {Promise<boolean>}
   */
  openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),
});

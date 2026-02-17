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
   * @param {(message: object) => void} callback
   */
  onDaemonMessage: (callback) => {
    ipcRenderer.on('daemon:message', (_event, message) => callback(message));
  },

  /**
   * Send an event message to the daemon (via main process).
   * @param {object} event
   */
  sendDaemonEvent: (event) => ipcRenderer.send('daemon:event', event),

  // ─── Lifecycle ─────────────────────────────────────────────────
  /**
   * Listen for overlay visibility changes.
   * @param {(visible: boolean) => void} callback
   */
  onVisibilityChange: (callback) => {
    ipcRenderer.on('overlay:visibility', (_event, visible) => callback(visible));
  },
});

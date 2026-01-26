/**
 * Bantz Browser - Preload Script
 * Secure bridge between renderer and main process
 */

const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods to renderer
contextBridge.exposeInMainWorld('bantz', {
  // Send command to Bantz Core
  sendCommand: (command) => ipcRenderer.invoke('bantz:command', command),
  
  // Browser navigation
  navigate: (url) => ipcRenderer.invoke('browser:navigate', url),
  
  // Get page info
  getPageInfo: () => ipcRenderer.invoke('browser:getPageInfo'),
  
  // Listen for navigation events
  onNavigate: (callback) => {
    ipcRenderer.on('browser:navigate', (event, url) => callback(url));
  },
  
  // Listen for page updates
  onPageUpdate: (callback) => {
    ipcRenderer.on('browser:pageUpdate', (event, info) => callback(info));
  },
  
  // Listen for Core connection status changes
  onCoreStatus: (callback) => {
    ipcRenderer.on('core:status', (event, connected) => callback(connected));
  },
  
  // Listen for URL navigation requests (from blocked popups)
  onNavigateToUrl: (callback) => {
    ipcRenderer.on('navigate-to-url', (event, url) => callback(url));
  }
});

// Expose webview helpers
contextBridge.exposeInMainWorld('webviewBridge', {
  // Execute script in webview
  executeScript: (script) => ipcRenderer.invoke('webview:executeScript', script),
  
  // Get DOM elements
  scanPage: () => ipcRenderer.invoke('webview:scanPage')
});

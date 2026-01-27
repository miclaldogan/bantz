/**
 * Bantz Browser Extension v2 - Background Service Worker
 * Handles native messaging, tab management, and coordination
 */

// ========================================================================
// Native Messaging
// ========================================================================

const NATIVE_HOST_NAME = 'bantz_native';

class NativeMessaging {
  constructor() {
    this.port = null;
    this.connected = false;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectDelay = 2000;
    this.messageQueue = [];
    this.pendingRequests = new Map();
    this.requestIdCounter = 0;
  }

  connect() {
    if (this.connected) return;

    try {
      console.log('[Bantz] Connecting to native host...');
      
      // Firefox uses browser.runtime, Chrome uses chrome.runtime
      const runtime = typeof browser !== 'undefined' ? browser.runtime : chrome.runtime;
      
      this.port = runtime.connectNative(NATIVE_HOST_NAME);

      this.port.onMessage.addListener((message) => {
        this.handleMessage(message);
      });

      this.port.onDisconnect.addListener(() => {
        this.handleDisconnect();
      });

      this.connected = true;
      this.reconnectAttempts = 0;
      console.log('[Bantz] Native host connected');

      // Send queued messages
      this.flushQueue();

      // Notify state change
      this.broadcastState();

    } catch (error) {
      console.error('[Bantz] Failed to connect to native host:', error);
      this.scheduleReconnect();
    }
  }

  disconnect() {
    if (this.port) {
      this.port.disconnect();
      this.port = null;
    }
    this.connected = false;
    this.broadcastState();
  }

  handleMessage(message) {
    console.log('[Bantz] Native message received:', message.type || 'unknown');

    // Check for response to pending request
    if (message.requestId && this.pendingRequests.has(message.requestId)) {
      const { resolve, reject } = this.pendingRequests.get(message.requestId);
      this.pendingRequests.delete(message.requestId);

      if (message.error) {
        reject(new Error(message.error));
      } else {
        resolve(message.data || message);
      }
      return;
    }

    // Handle different message types
    switch (message.type) {
      case 'command':
        this.handleCommand(message);
        break;

      case 'state_update':
        this.broadcastToTabs({ type: 'bantz:state', data: message.data });
        break;

      case 'overlay':
        this.sendToActiveTab({ type: 'overlay', ...message });
        break;

      case 'speak':
        // TTS handled by native side
        break;

      default:
        console.log('[Bantz] Unknown native message type:', message.type);
    }
  }

  handleDisconnect() {
    const error = typeof browser !== 'undefined' 
      ? browser.runtime.lastError 
      : chrome.runtime.lastError;
    
    console.log('[Bantz] Native host disconnected:', error?.message || 'unknown');
    this.connected = false;
    this.port = null;
    
    // Notify tabs
    this.broadcastState();

    // Try to reconnect
    this.scheduleReconnect();
  }

  scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.log('[Bantz] Max reconnect attempts reached');
      return;
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
    
    console.log(`[Bantz] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    
    setTimeout(() => {
      this.connect();
    }, delay);
  }

  send(message) {
    if (!this.connected || !this.port) {
      this.messageQueue.push(message);
      this.connect();
      return Promise.reject(new Error('Not connected'));
    }

    try {
      this.port.postMessage(message);
      return Promise.resolve();
    } catch (error) {
      console.error('[Bantz] Error sending message:', error);
      return Promise.reject(error);
    }
  }

  sendRequest(message, timeout = 10000) {
    return new Promise((resolve, reject) => {
      const requestId = ++this.requestIdCounter;
      message.requestId = requestId;

      this.pendingRequests.set(requestId, { resolve, reject });

      // Timeout
      setTimeout(() => {
        if (this.pendingRequests.has(requestId)) {
          this.pendingRequests.delete(requestId);
          reject(new Error('Request timeout'));
        }
      }, timeout);

      this.send(message).catch(reject);
    });
  }

  flushQueue() {
    while (this.messageQueue.length > 0) {
      const message = this.messageQueue.shift();
      this.send(message);
    }
  }

  broadcastState() {
    const state = {
      type: 'bantz:connection',
      connected: this.connected,
    };
    this.broadcastToTabs(state);
  }

  async handleCommand(message) {
    const { command, params, tabId } = message;

    try {
      let result;

      switch (command) {
        case 'scan':
          result = await this.sendToTab(tabId, { type: 'scan', ...params });
          break;

        case 'click':
          result = await this.sendToTab(tabId, { type: 'click', ...params });
          break;

        case 'type':
          result = await this.sendToTab(tabId, { type: 'type', ...params });
          break;

        case 'scroll':
          result = await this.sendToTab(tabId, { type: 'scroll', ...params });
          break;

        case 'detect_forms':
          result = await this.sendToTab(tabId, { type: 'detect_forms' });
          break;

        case 'extract_content':
          result = await this.sendToTab(tabId, { type: 'extract_content', ...params });
          break;

        case 'navigate':
          await this.navigate(params.url, tabId);
          result = { success: true };
          break;

        case 'screenshot':
          result = await this.captureScreenshot(tabId);
          break;

        case 'fill_form':
          result = await this.sendToTab(tabId, { type: 'fill_form', ...params });
          break;

        case 'get_tabs':
          result = await this.getTabs();
          break;

        default:
          result = { error: 'Unknown command' };
      }

      // Send result back to native
      this.send({
        type: 'command_result',
        requestId: message.requestId,
        command,
        data: result,
      });

    } catch (error) {
      this.send({
        type: 'command_result',
        requestId: message.requestId,
        command,
        error: error.message,
      });
    }
  }

  // Tab messaging helpers
  async sendToTab(tabId, message) {
    const targetTabId = tabId || await this.getActiveTabId();
    
    const tabs = typeof browser !== 'undefined' ? browser.tabs : chrome.tabs;
    return new Promise((resolve, reject) => {
      tabs.sendMessage(targetTabId, message, (response) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else {
          resolve(response);
        }
      });
    });
  }

  async sendToActiveTab(message) {
    const tabId = await this.getActiveTabId();
    return this.sendToTab(tabId, message);
  }

  async broadcastToTabs(message) {
    const tabs = typeof browser !== 'undefined' ? browser.tabs : chrome.tabs;
    const allTabs = await tabs.query({});
    
    for (const tab of allTabs) {
      try {
        tabs.sendMessage(tab.id, message);
      } catch (e) {
        // Tab may not have content script
      }
    }
  }

  async getActiveTabId() {
    const tabs = typeof browser !== 'undefined' ? browser.tabs : chrome.tabs;
    const [tab] = await tabs.query({ active: true, currentWindow: true });
    return tab?.id;
  }

  async navigate(url, tabId) {
    const tabs = typeof browser !== 'undefined' ? browser.tabs : chrome.tabs;
    const targetTabId = tabId || await this.getActiveTabId();

    // Ensure URL has protocol
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://' + url;
    }

    await tabs.update(targetTabId, { url });
  }

  async captureScreenshot(tabId) {
    const tabs = typeof browser !== 'undefined' ? browser.tabs : chrome.tabs;
    const targetTabId = tabId || await this.getActiveTabId();

    // Get active tab's window
    const tab = await tabs.get(targetTabId);
    
    const imageData = await new Promise((resolve, reject) => {
      chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' }, (dataUrl) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else {
          resolve(dataUrl);
        }
      });
    });

    return {
      success: true,
      data: imageData,
      timestamp: Date.now(),
    };
  }

  async getTabs() {
    const tabs = typeof browser !== 'undefined' ? browser.tabs : chrome.tabs;
    const allTabs = await tabs.query({});
    
    return allTabs.map(tab => ({
      id: tab.id,
      title: tab.title,
      url: tab.url,
      active: tab.active,
      windowId: tab.windowId,
    }));
  }
}

// ========================================================================
// State Management
// ========================================================================

const state = {
  connected: false,
  overlayEnabled: true,
  currentProfile: null,
  lastError: null,
};

// ========================================================================
// Message Handlers
// ========================================================================

const nativeMessaging = new NativeMessaging();

// Handle messages from content scripts
const runtime = typeof browser !== 'undefined' ? browser.runtime : chrome.runtime;

runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log('[Bantz] Message from content:', message.type);

  switch (message.type) {
    case 'content_ready':
      console.log('[Bantz] Content script ready:', sender.tab?.id);
      
      // Send current state
      sendResponse({ 
        connected: nativeMessaging.connected,
        overlayEnabled: state.overlayEnabled,
      });

      // Notify native
      nativeMessaging.send({
        type: 'tab_ready',
        tabId: sender.tab?.id,
        url: sender.tab?.url,
      });
      break;

    case 'dom_changed':
      // Forward to native if interested
      nativeMessaging.send({
        type: 'dom_changed',
        tabId: sender.tab?.id,
        url: message.url,
      });
      break;

    case 'capture_screenshot':
      nativeMessaging.captureScreenshot(sender.tab?.id)
        .then(result => sendResponse(result))
        .catch(err => sendResponse({ error: err.message }));
      return true; // Async

    case 'get_state':
      sendResponse({
        connected: nativeMessaging.connected,
        overlayEnabled: state.overlayEnabled,
        profile: state.currentProfile,
      });
      break;

    case 'forward_to_native':
      nativeMessaging.send(message.payload);
      sendResponse({ sent: true });
      break;

    default:
      sendResponse({ error: 'Unknown message type' });
  }

  return false;
});

// Handle popup messages
runtime.onConnect.addListener((port) => {
  if (port.name === 'popup') {
    console.log('[Bantz] Popup connected');

    port.onMessage.addListener((message) => {
      switch (message.type) {
        case 'get_state':
          port.postMessage({
            type: 'state',
            connected: nativeMessaging.connected,
            overlayEnabled: state.overlayEnabled,
          });
          break;

        case 'toggle_overlay':
          state.overlayEnabled = !state.overlayEnabled;
          nativeMessaging.broadcastToTabs({
            type: 'overlay',
            action: state.overlayEnabled ? 'show' : 'hide',
          });
          port.postMessage({
            type: 'state',
            overlayEnabled: state.overlayEnabled,
          });
          break;

        case 'reconnect':
          nativeMessaging.reconnectAttempts = 0;
          nativeMessaging.connect();
          break;
      }
    });
  }
});

// ========================================================================
// Tab Events
// ========================================================================

const tabs = typeof browser !== 'undefined' ? browser.tabs : chrome.tabs;

tabs.onActivated.addListener(async (activeInfo) => {
  const tab = await tabs.get(activeInfo.tabId);
  
  nativeMessaging.send({
    type: 'tab_activated',
    tabId: activeInfo.tabId,
    url: tab.url,
    title: tab.title,
  });
});

tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete') {
    nativeMessaging.send({
      type: 'tab_loaded',
      tabId: tabId,
      url: tab.url,
      title: tab.title,
    });
  }
});

// ========================================================================
// Badge/Icon Management
// ========================================================================

function updateBadge(connected) {
  const action = typeof browser !== 'undefined' ? browser.action : chrome.action;
  
  if (connected) {
    action.setBadgeText({ text: '✓' });
    action.setBadgeBackgroundColor({ color: '#4CAF50' });
  } else {
    action.setBadgeText({ text: '!' });
    action.setBadgeBackgroundColor({ color: '#F44336' });
  }
}

// ========================================================================
// Initialization
// ========================================================================

console.log('[Bantz] Background service worker v2 starting...');

// Connect to native host on startup
nativeMessaging.connect();

// Update badge based on connection
setInterval(() => {
  updateBadge(nativeMessaging.connected);
}, 1000);

console.log('[Bantz] Background service worker v2 ready');

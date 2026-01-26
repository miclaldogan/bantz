/**
 * Bantz Firefox Extension - Background Script
 * Handles WebSocket connection to Bantz daemon
 */

// WebSocket connection to Bantz daemon
let socket = null;
let connected = false;
let reconnectTimeout = null;
const WS_URL = 'ws://localhost:9876';

// Connection state
const state = {
  connected: false,
  lastError: null,
  overlayEnabled: true,
  currentProfile: null,
};

/**
 * Connect to Bantz daemon WebSocket server
 */
function connect() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    return;
  }

  try {
    socket = new WebSocket(WS_URL);

    socket.onopen = () => {
      console.log('[Bantz] WebSocket connected');
      state.connected = true;
      state.lastError = null;
      updateBadge(true);
      
      // Notify all tabs
      broadcastToTabs({ type: 'bantz:connected' });
    };

    socket.onclose = (event) => {
      console.log('[Bantz] WebSocket disconnected:', event.code, event.reason);
      state.connected = false;
      updateBadge(false);
      
      // Schedule reconnect
      if (!reconnectTimeout) {
        reconnectTimeout = setTimeout(() => {
          reconnectTimeout = null;
          connect();
        }, 3000);
      }
    };

    socket.onerror = (error) => {
      console.error('[Bantz] WebSocket error:', error);
      state.lastError = 'Bağlantı hatası';
    };

    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        handleDaemonMessage(message);
      } catch (e) {
        console.error('[Bantz] Invalid message:', e);
      }
    };
  } catch (e) {
    console.error('[Bantz] Connection failed:', e);
    state.lastError = e.message;
  }
}

/**
 * Send message to daemon
 */
function sendToDaemon(message) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message));
    return true;
  }
  return false;
}

/**
 * Handle incoming messages from daemon
 */
function handleDaemonMessage(message) {
  console.log('[Bantz] Received:', message);
  
  switch (message.type) {
    case 'scan':
      // Request scan from active tab
      sendToActiveTab({ type: 'bantz:scan' });
      break;
      
    case 'click':
      // Click element by index
      sendToActiveTab({ 
        type: 'bantz:click', 
        index: message.index,
        text: message.text 
      });
      break;
      
    case 'scroll':
      sendToActiveTab({ 
        type: 'bantz:scroll', 
        direction: message.direction,
        amount: message.amount || 500 
      });
      break;
      
    case 'type':
      sendToActiveTab({ 
        type: 'bantz:type', 
        text: message.text,
        index: message.index 
      });
      break;
      
    case 'navigate':
      browser.tabs.update({ url: message.url });
      break;
      
    case 'overlay':
      // Toggle overlay visibility
      sendToActiveTab({ 
        type: 'bantz:overlay', 
        enabled: message.enabled 
      });
      state.overlayEnabled = message.enabled;
      break;
      
    case 'profile':
      // Apply site profile
      state.currentProfile = message.profile;
      sendToActiveTab({ 
        type: 'bantz:profile', 
        profile: message.profile 
      });
      break;
      
    default:
      console.log('[Bantz] Unknown message type:', message.type);
  }
}

/**
 * Send message to active tab's content script
 */
async function sendToActiveTab(message) {
  try {
    const tabs = await browser.tabs.query({ active: true, currentWindow: true });
    if (tabs[0]) {
      browser.tabs.sendMessage(tabs[0].id, message);
    }
  } catch (e) {
    console.error('[Bantz] Failed to send to tab:', e);
  }
}

/**
 * Broadcast message to all tabs
 */
async function broadcastToTabs(message) {
  try {
    const tabs = await browser.tabs.query({});
    for (const tab of tabs) {
      try {
        browser.tabs.sendMessage(tab.id, message);
      } catch (e) {
        // Tab might not have content script loaded
      }
    }
  } catch (e) {
    console.error('[Bantz] Broadcast failed:', e);
  }
}

/**
 * Update extension badge to show connection status
 */
function updateBadge(isConnected) {
  browser.browserAction.setBadgeText({ 
    text: isConnected ? '✓' : '!' 
  });
  browser.browserAction.setBadgeBackgroundColor({ 
    color: isConnected ? '#10b981' : '#ef4444' 
  });
}

/**
 * Listen for messages from content scripts
 */
browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log('[Bantz] From content:', message);
  
  switch (message.type) {
    case 'bantz:scan_result':
      // Forward scan results to daemon
      sendToDaemon({
        type: 'scan_result',
        elements: message.elements,
        url: sender.tab?.url,
        title: sender.tab?.title,
      });
      break;
      
    case 'bantz:click_result':
      sendToDaemon({
        type: 'click_result',
        success: message.success,
        message: message.message,
      });
      break;
      
    case 'bantz:get_status':
      sendResponse({
        connected: state.connected,
        overlayEnabled: state.overlayEnabled,
        currentProfile: state.currentProfile,
      });
      break;
      
    default:
      // Forward other messages to daemon
      sendToDaemon(message);
  }
  
  return true; // Keep channel open for async response
});

/**
 * Listen for tab updates to apply profiles and auto-scan
 */
browser.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url) {
    // Skip internal pages
    if (tab.url.startsWith('about:') || tab.url.startsWith('moz-extension:')) {
      return;
    }
    
    console.log('[Bantz] Tab loaded:', tab.url);
    
    // Auto-scan page when loaded
    setTimeout(() => {
      browser.tabs.sendMessage(tabId, { type: 'bantz:scan' }).catch(() => {});
    }, 1000);
    
    // Notify daemon about page change
    if (state.connected) {
      sendToDaemon({
        type: 'page_loaded',
        url: tab.url,
        title: tab.title,
      });
    }
    
    // Check if we should apply a site profile
    checkSiteProfile(tab.url, tabId);
  }
});

/**
 * Listen for tab activation (switching tabs)
 */
browser.tabs.onActivated.addListener(async (activeInfo) => {
  try {
    const tab = await browser.tabs.get(activeInfo.tabId);
    if (tab.url && !tab.url.startsWith('about:')) {
      console.log('[Bantz] Tab activated:', tab.url);
      
      // Auto-scan active tab
      setTimeout(() => {
        browser.tabs.sendMessage(activeInfo.tabId, { type: 'bantz:scan' }).catch(() => {});
      }, 500);
      
      // Notify daemon
      if (state.connected) {
        sendToDaemon({
          type: 'tab_activated',
          url: tab.url,
          title: tab.title,
        });
      }
    }
  } catch (e) {
    console.error('[Bantz] Tab activation error:', e);
  }
});

/**
 * Check and apply site profile based on URL
 */
async function checkSiteProfile(url, tabId) {
  // Site profiles are stored in extension storage
  const { profiles } = await browser.storage.local.get('profiles');
  if (!profiles) return;
  
  for (const [domain, profile] of Object.entries(profiles)) {
    if (url.includes(domain)) {
      browser.tabs.sendMessage(tabId, {
        type: 'bantz:profile',
        profile: profile,
      });
      state.currentProfile = profile;
      
      // Notify daemon about profile activation
      sendToDaemon({
        type: 'profile_activated',
        domain: domain,
        profile: profile,
      });
      break;
    }
  }
}

// Initialize
connect();
console.log('[Bantz] Extension initialized');

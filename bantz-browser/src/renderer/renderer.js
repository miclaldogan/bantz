/**
 * Bantz Browser - Renderer Process
 * Handles UI interactions and communication with main process
 */

// DOM Elements
const webview = document.getElementById('webview');
const urlBar = document.getElementById('url-bar');
const btnBack = document.getElementById('btn-back');
const btnForward = document.getElementById('btn-forward');
const btnReload = document.getElementById('btn-reload');
const btnGo = document.getElementById('btn-go');
const btnPanelToggle = document.getElementById('btn-panel-toggle');
const bantzPanel = document.getElementById('bantz-panel');
const outputArea = document.getElementById('output-area');
const commandInput = document.getElementById('command-input');
const btnSend = document.getElementById('btn-send');
const quickBtns = document.querySelectorAll('.quick-btn');
const coreStatus = document.getElementById('core-status');
const loadingBar = document.getElementById('loading-bar');

// Proactive inbox UI
const inboxBadge = document.getElementById('inbox-badge');
const inboxPanel = document.getElementById('inbox-panel');
const inboxList = document.getElementById('inbox-list');
const btnInboxClear = document.getElementById('btn-inbox-clear');

// HUD elements
const hudTitle = document.getElementById('hud-title');
const hudMode = document.getElementById('hud-mode');
const hudPending = document.getElementById('hud-pending');
const hudPendingContainer = document.getElementById('hud-pending-container');
const statusLeft = document.getElementById('status-left');
const statusUrl = document.getElementById('status-url');

// State
let currentMode = 'browse';
let scanCache = [];
let scanOffset = 0;
let commandHistory = [];
let historyIndex = -1;
let pendingConfirmation = null; // { action: 'click'|'type', element: {...}, text?: string }

// Auto behavior (navigation)
let autoScanOnNav = true;
let overlayAutoOnNav = true;
let autoScanTimer = null;
let autoScanToken = 0;

// Proactive inbox state
let inboxItems = [];
let lastSeenInboxId = 0;
let inboxPollTimer = null;

// Risky keywords that require confirmation
const RISKY_KEYWORDS = [
  'gönder', 'paylaş', 'post', 'ödeme', 'öde', 'satın al', 'sil', 'delete',
  'submit', 'pay', 'send', 'share', 'purchase', 'buy', 'remove', 'confirm',
  'onayla', 'kaldır', 'yayınla', 'publish'
];

/**
 * Normalize Turkish characters for fuzzy matching
 */
function normalizeTurkish(str) {
  return str
    .toLowerCase()
    .replace(/ı/g, 'i')
    .replace(/İ/g, 'i')
    .replace(/ğ/g, 'g')
    .replace(/Ğ/g, 'g')
    .replace(/ü/g, 'u')
    .replace(/Ü/g, 'u')
    .replace(/ş/g, 's')
    .replace(/Ş/g, 's')
    .replace(/ö/g, 'o')
    .replace(/Ö/g, 'o')
    .replace(/ç/g, 'c')
    .replace(/Ç/g, 'c')
    .replace(/[''"]/g, '')
    .trim();
}

/**
 * Check if element text contains risky keywords
 */
function isRiskyElement(text) {
  const normalized = normalizeTurkish(text);
  return RISKY_KEYWORDS.some(keyword => normalized.includes(normalizeTurkish(keyword)));
}

/**
 * Initialize the browser
 */
function init() {
  setupWebviewEvents();
  setupNavigationEvents();
  setupPanelEvents();
  setupKeyboardShortcuts();
  setupCoreStatusListener();
  setupPopupInterceptor();
  checkCoreConnection();
  setupProactiveInbox();
  
  // Focus command input
  commandInput.focus();
}

/**
 * Proactive Inbox (non-blocking)
 */
function setupProactiveInbox() {
  // Toast element
  let toast = document.getElementById('proactive-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'proactive-toast';
    toast.className = 'proactive-toast hidden';
    toast.textContent = '';
    document.body.appendChild(toast);
  }

  let toastTimer = null;
  function showToast(text) {
    toast.textContent = `🔔 ${text}`;
    toast.classList.remove('hidden');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.add('hidden'), 3500);
  }

  function renderInbox() {
    const unread = inboxItems.filter(x => !x.read).length;

    const hasItems = inboxItems.length > 0;
    inboxBadge.textContent = `Inbox (${unread})`;
    inboxBadge.classList.toggle('hidden', !hasItems);
    inboxPanel.classList.toggle('hidden', !hasItems);

    inboxList.innerHTML = '';
    inboxItems.slice().reverse().forEach(item => {
      const row = document.createElement('div');
      row.className = 'inbox-item';
      row.dataset.inboxId = String(item.id ?? '');

      const dot = document.createElement('div');
      dot.className = 'inbox-dot' + (item.read ? ' read' : '');

      const text = document.createElement('div');
      text.className = 'inbox-text';
      text.textContent = item.text || '';

      row.appendChild(dot);
      row.appendChild(text);

      row.addEventListener('click', async () => {
        const id = Number(row.dataset.inboxId || 0);
        if (!id) return;
        try {
          const res = await window.bantz.sendCommand(`__inbox_mark__ ${id}`);
          if (res && res.ok) {
            // Optimistic local update
            const match = inboxItems.find(x => Number(x.id || 0) === id);
            if (match) match.read = true;
            renderInbox();
          }
        } catch (_) {
          // ignore
        }
      });

      inboxList.appendChild(row);
    });
  }

  async function pollInbox() {
    try {
      const res = await window.bantz.sendCommand('__inbox__');
      if (!res || !res.ok) return;
      const items = Array.isArray(res.inbox) ? res.inbox : [];
      inboxItems = items;

      // toast for new items
      const maxId = items.reduce((m, x) => Math.max(m, Number(x.id || 0)), 0);
      if (maxId > lastSeenInboxId) {
        const newest = items.find(x => Number(x.id || 0) === maxId);
        if (newest && newest.text) showToast(newest.text);
        lastSeenInboxId = maxId;
      }

      renderInbox();
    } catch (_) {
      // ignore
    }
  }

  btnInboxClear.addEventListener('click', async () => {
    try {
      await window.bantz.sendCommand('__inbox_clear__');
      inboxItems = [];
      lastSeenInboxId = 0;
      renderInbox();
    } catch (_) {}
  });

  // Poll every 3 seconds
  pollInbox();
  inboxPollTimer = setInterval(pollInbox, 3000);
}

/**
 * Listen for Core connection status changes from main process
 */
function setupCoreStatusListener() {
  window.bantz.onCoreStatus((connected) => {
    updateCoreStatus(connected);
  });
}

/**
 * Intercept popup URLs from main process and navigate in webview
 */
function setupPopupInterceptor() {
  window.bantz.onNavigateToUrl((url) => {
    addMessage(`🔗 Popup yakalandı, aynı pencerede açılıyor: ${url}`, 'system');
    webview.src = url;
  });
}

/**
 * Update Core connection status UI
 */
function updateCoreStatus(connected) {
  if (connected) {
    coreStatus.classList.remove('disconnected', 'connecting');
    coreStatus.title = 'Core bağlı';
  } else {
    coreStatus.classList.add('disconnected');
    coreStatus.classList.remove('connecting');
    coreStatus.title = 'Core bağlı değil';
  }
}

/**
 * Setup webview events
 */
function setupWebviewEvents() {
  function scheduleAutoScan(reason) {
    if (!autoScanOnNav) return;
    autoScanToken += 1;
    const token = autoScanToken;

    if (autoScanTimer) clearTimeout(autoScanTimer);
    autoScanTimer = setTimeout(async () => {
      if (token !== autoScanToken) return;
      try {
        // Reset scan cache on navigation
        scanCache = [];
        scanOffset = 0;

        // Keep overlay on across navigations (silently)
        if (overlayAutoOnNav) {
          try {
            await injectOverlaySystem();
            const result = await webview.executeJavaScript(`
              window.BantzOverlay ? window.BantzOverlay.toggle(true) : { active: false, count: 0 }
            `);
            overlayActive = !!(result && result.active);
            if (overlayActive) {
              await syncScanCacheWithOverlay();
            }
          } catch (_) {
            // ignore overlay errors; scanPage() will still work
          }
        }

        await scanPage();
      } catch (e) {
        addMessage(`⚠️ Otomatik tarama hata (${reason}): ${e && e.message ? e.message : e}`, 'error');
      }
    }, 250);
  }

  webview.addEventListener('did-start-loading', () => {
    loadingBar.classList.remove('hidden');
    statusLeft.textContent = 'Yükleniyor...';
  });

  webview.addEventListener('did-stop-loading', () => {
    loadingBar.classList.add('hidden');
    statusLeft.textContent = 'Hazır';
  });
  
  // Inject overlay system when page loads and re-enable if it was active
  webview.addEventListener('did-finish-load', async () => {
    await injectOverlaySystem();
    // If overlay was active, re-enable it on new page
    if (overlayActive) {
      try {
        await webview.executeJavaScript(`
          window.BantzOverlay ? window.BantzOverlay.toggle(true) : null
        `);
        await syncScanCacheWithOverlay();
      } catch (err) {
        console.error('Overlay re-enable failed:', err);
      }
    }

    scheduleAutoScan('finish-load');
  });

  webview.addEventListener('dom-ready', () => {
    scheduleAutoScan('dom-ready');
  });

  webview.addEventListener('did-navigate', (e) => {
    urlBar.value = e.url;
    updateNavigationButtons();
    updateHUD();
    // Clear scan cache on navigation
    scanCache = [];
    scanOffset = 0;

    scheduleAutoScan('did-navigate');
  });

  webview.addEventListener('did-navigate-in-page', (e) => {
    urlBar.value = e.url;
    updateNavigationButtons();

    scheduleAutoScan('in-page');
  });

  webview.addEventListener('page-title-updated', (e) => {
    hudTitle.textContent = e.title || '-';
    document.title = `${e.title} - Bantz Browser`;
  });

  webview.addEventListener('did-fail-load', (e) => {
    if (e.errorCode !== -3) { // Ignore aborted loads
      addMessage(`Sayfa yüklenemedi: ${e.errorDescription}`, 'error');
    }
  });

  // Update URL on hover
  webview.addEventListener('update-target-url', (e) => {
    statusUrl.textContent = e.url || '';
  });
  
  // CRITICAL: Catch new-window events - open in same webview instead of external browser
  webview.addEventListener('new-window', (e) => {
    e.preventDefault();
    e.stopPropagation();
    // Open the URL in the same webview
    if (e.url && e.url !== 'about:blank') {
      addMessage(`🔗 Popup engellendi, aynı pencerede açılıyor: ${e.url}`, 'system');
      webview.src = e.url;
    }
  });
  
  // Also intercept window.open calls via will-navigate for target=_blank
  webview.addEventListener('will-navigate', (e) => {
    // This is normal navigation, just update URL bar
    urlBar.value = e.url;
  });
}

/**
 * Setup navigation button events
 */
function setupNavigationEvents() {
  btnBack.addEventListener('click', () => {
    if (webview.canGoBack()) webview.goBack();
  });

  btnForward.addEventListener('click', () => {
    if (webview.canGoForward()) webview.goForward();
  });

  btnReload.addEventListener('click', () => {
    webview.reload();
  });

  btnGo.addEventListener('click', navigateToUrl);
  
  urlBar.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') navigateToUrl();
  });
}

/**
 * Navigate to URL in address bar
 */
function navigateToUrl() {
  let url = urlBar.value.trim();
  
  if (!url) return;
  
  // Add protocol if missing
  if (!url.match(/^https?:\/\//)) {
    // Check if it looks like a URL
    if (url.includes('.') && !url.includes(' ')) {
      url = 'https://' + url;
    } else {
      // Treat as search query
      url = `https://duckduckgo.com/?q=${encodeURIComponent(url)}`;
    }
  }
  
  webview.src = url;
}

/**
 * Update navigation button states
 */
function updateNavigationButtons() {
  btnBack.disabled = !webview.canGoBack();
  btnForward.disabled = !webview.canGoForward();
}

/**
 * Setup panel events
 */
function setupPanelEvents() {
  // Toggle panel
  btnPanelToggle.addEventListener('click', () => {
    bantzPanel.classList.toggle('hidden');
    btnPanelToggle.classList.toggle('active');
  });

  // Send command
  btnSend.addEventListener('click', sendCommand);
  commandInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendCommand();
    } else if (e.key === 'ArrowUp') {
      navigateHistory(-1);
    } else if (e.key === 'ArrowDown') {
      navigateHistory(1);
    }
  });

  // Quick action buttons
  quickBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      commandInput.value = btn.dataset.cmd;
      sendCommand();
    });
  });
}

/**
 * Setup keyboard shortcuts
 */
function setupKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // Ctrl+B: Toggle panel
    if (e.ctrlKey && e.key === 'b') {
      e.preventDefault();
      btnPanelToggle.click();
    }
    
    // Ctrl+L: Focus URL bar
    if (e.ctrlKey && e.key === 'l') {
      e.preventDefault();
      urlBar.focus();
      urlBar.select();
    }
    
    // Ctrl+K: Focus command input
    if (e.ctrlKey && e.key === 'k') {
      e.preventDefault();
      commandInput.focus();
    }
    
    // F5: Reload
    if (e.key === 'F5') {
      e.preventDefault();
      webview.reload();
    }
    
    // Alt+Left: Back
    if (e.altKey && e.key === 'ArrowLeft') {
      e.preventDefault();
      if (webview.canGoBack()) webview.goBack();
    }
    
    // Alt+Right: Forward
    if (e.altKey && e.key === 'ArrowRight') {
      e.preventDefault();
      if (webview.canGoForward()) webview.goForward();
    }
    
    // Escape: Focus webview
    if (e.key === 'Escape') {
      webview.focus();
    }
  });
}

/**
 * Send command to Bantz Core
 */
async function sendCommand() {
  const text = commandInput.value.trim();
  if (!text) return;
  
  // Add to history
  commandHistory.push(text);
  historyIndex = commandHistory.length;
  commandInput.value = '';
  
  // Show user message
  addMessage(text, 'user');
  
  // Check for local browser commands first
  const localResult = handleLocalCommand(text);
  if (localResult !== null) {
    // localResult can be:
    // - { text, type } for sync commands with immediate response
    // - 'async' for async commands that handle their own messages
    if (localResult !== 'async' && localResult.text) {
      addMessage(localResult.text, localResult.type || 'system');
    }
    return; // Don't send to Core
  }
  
  // Check Core connection before sending
  const isConnected = !coreStatus.classList.contains('disconnected');
  if (!isConnected) {
    addMessage('⚠️ Core bağlı değil. Sadece tarayıcı komutları çalışır:', 'warning');
    addMessage('💡 Dene: sayfayı tara, instagram aç, aşağı, geri, ara: ...', 'system');
    return;
  }
  
  // Send to Core (only for non-browser commands)
  statusLeft.textContent = 'İşleniyor...';
  
  try {
    // Include page state for context
    const pageState = await getPageState();
    const response = await window.bantz.sendCommand(text);
    
    if (response.ok) {
      addMessage(response.text, 'success');
      
      // Handle special actions from Core
      if (response.action) {
        await handleCoreAction(response.action);
      }
    } else {
      addMessage(response.text || 'Bilinmeyen hata', 'error');
    }
  } catch (err) {
    addMessage(`Hata: ${err.message}`, 'error');
  }
  
  statusLeft.textContent = 'Hazır';
  updateHUD();
}

/**
 * Handle local browser commands
 */
function handleLocalCommand(text) {
  const lower = text.toLowerCase().trim();
  
  // Handle pending confirmation first
  if (pendingConfirmation) {
    if (lower === 'evet' || lower === 'yes' || lower === 'e' || lower === 'ok' || lower === 'tamam') {
      const pending = pendingConfirmation;
      pendingConfirmation = null;
      if (pending.action === 'click') {
        executeClick(pending.element);
      } else if (pending.action === 'type') {
        executeType(pending.element, pending.text);
      }
      return 'async';
    } else if (lower === 'hayır' || lower === 'no' || lower === 'h' || lower === 'iptal') {
      pendingConfirmation = null;
      return { text: '❌ İşlem iptal edildi.', type: 'system' };
    }
    // If neither yes nor no, cancel and process as new command
    pendingConfirmation = null;
    addMessage('⚠️ Onay bekleniyor, iptal edildi.', 'system');
  }
  
  // Navigation commands
  if (lower === 'geri' || lower === 'geri dön') {
    if (webview.canGoBack()) {
      webview.goBack();
      return { text: '◀️ Geri gidiliyor...', type: 'system' };
    }
    return { text: 'Geri gidecek sayfa yok.', type: 'error' };
  }
  
  if (lower === 'ileri') {
    if (webview.canGoForward()) {
      webview.goForward();
      return { text: '▶️ İleri gidiliyor...', type: 'system' };
    }
    return { text: 'İleri gidecek sayfa yok.', type: 'error' };
  }
  
  if (lower === 'yenile' || lower === 'refresh') {
    webview.reload();
    return { text: '🔄 Sayfa yenileniyor...', type: 'system' };
  }
  
  // Scroll commands
  if (lower === 'aşağı' || lower === 'aşağı kaydır' || lower === 'scroll down') {
    webview.executeJavaScript('window.scrollBy(0, 400)');
    return { text: '⬇️ Aşağı kaydırıldı', type: 'system' };
  }
  
  if (lower === 'yukarı' || lower === 'yukarı kaydır' || lower === 'scroll up') {
    webview.executeJavaScript('window.scrollBy(0, -400)');
    return { text: '⬆️ Yukarı kaydırıldı', type: 'system' };
  }
  
  if (lower === 'en aşağı' || lower === 'sona git') {
    webview.executeJavaScript('window.scrollTo(0, document.body.scrollHeight)');
    return { text: '⬇️ Sayfa sonuna gidildi', type: 'system' };
  }
  
  if (lower === 'en yukarı' || lower === 'başa git') {
    webview.executeJavaScript('window.scrollTo(0, 0)');
    return { text: '⬆️ Sayfa başına gidildi', type: 'system' };
  }
  
  // Overlay commands
  if (lower === 'overlay aç' || lower === 'overlay' || lower === 'numaraları göster' || lower === 'etiketleri göster') {
    toggleOverlay(true);
    return 'async';
  }
  
  if (lower === 'overlay kapat' || lower === 'numaraları kapat' || lower === 'etiketleri kapat' || lower === 'gizle') {
    toggleOverlay(false);
    return 'async';
  }
  
  if (lower === 'overlay yenile' || lower === 'overlay refresh') {
    refreshOverlay();
    return 'async';
  }
  
  if (lower === 'overlay durum' || lower === 'overlay status') {
    showOverlayStatus();
    return 'async';
  }
  
  // Page scan command
  if (lower === 'sayfayı tara' || lower === 'tara' || lower === 'yeniden tara') {
    scanPage();
    return 'async'; // Handled async, don't send to Core
  }
  
  if (lower === 'daha fazla' || lower === 'daha' || lower === 'devam') {
    showMoreScanResults();
    return 'async';
  }
  
  if (lower === 'önceki' || lower === 'geri dön listede') {
    showPreviousScanResults();
    return 'async';
  }
  
  // Detail command
  const detailMatch = lower.match(/^detay\s+(\d+)$/);
  if (detailMatch) {
    showElementDetail(parseInt(detailMatch[1]));
    return 'async';
  }
  
  // Click command - by number: "10'a tıkla", "tıkla 10"
  const clickMatch = lower.match(/^(\d+)['\s]*(ye|ya|e|a)?\s*tıkla$/i) || 
                     lower.match(/^tıkla\s+(\d+)$/i);
  if (clickMatch) {
    clickElement(parseInt(clickMatch[1]));
    return 'async';
  }
  
  // Click command - by text: "Jobs'e tıkla", "Login'e tıkla", "tıkla Jobs"
  const clickTextMatch = lower.match(/^(.+?)['\s]*(ye|ya|e|a|ne)?\s*tıkla$/i) ||
                         lower.match(/^tıkla\s+(.+)$/i);
  if (clickTextMatch) {
    const searchText = clickTextMatch[1].trim();
    // Don't match if it's a number (already handled above)
    if (!/^\d+$/.test(searchText)) {
      clickElementByText(searchText);
      return 'async';
    }
  }
  
  // Type command
  const typeMatch = lower.match(/^(\d+)['\s]*(ye|ya|e|a)?\s*yaz[:\s]+(.+)$/i);
  if (typeMatch) {
    typeInElement(parseInt(typeMatch[1]), typeMatch[3]);
    return 'async';
  }
  
  // URL navigation - "git X" or "aç X"
  if (lower.startsWith('git ') || lower.startsWith('aç ')) {
    const target = text.slice(lower.indexOf(' ') + 1).trim();
    navigateTo(target);
    return 'async';
  }
  
  // Site shortcuts - "X aç" pattern (instagram aç, youtube aç, etc.)
  const siteOpenMatch = lower.match(/^(instagram|youtube|twitter|x|github|google|wikipedia|reddit|linkedin|facebook)\s*aç$/i);
  if (siteOpenMatch) {
    const siteUrls = {
      'instagram': 'https://instagram.com',
      'youtube': 'https://youtube.com',
      'twitter': 'https://twitter.com',
      'x': 'https://x.com',
      'github': 'https://github.com',
      'google': 'https://google.com',
      'wikipedia': 'https://tr.wikipedia.org',
      'reddit': 'https://reddit.com',
      'linkedin': 'https://linkedin.com',
      'facebook': 'https://facebook.com'
    };
    const site = siteOpenMatch[1].toLowerCase();
    addMessage(`🌐 ${site} açılıyor...`, 'system');
    navigateTo(siteUrls[site]);
    return 'async';
  }
  
  // Search commands - "X'da ara: Y" or "X ara: Y"
  const searchMatch = lower.match(/^(google|wikipedia|youtube|duckduckgo|ddg)'?d[ae]\s*ara[:\s]+(.+)$/i) ||
                      lower.match(/^(google|wikipedia|youtube|duckduckgo|ddg)\s*ara[:\s]+(.+)$/i);
  if (searchMatch) {
    const engine = searchMatch[1].toLowerCase();
    const query = searchMatch[2].trim();
    const searchUrls = {
      'google': `https://www.google.com/search?q=${encodeURIComponent(query)}`,
      'wikipedia': `https://tr.wikipedia.org/w/index.php?search=${encodeURIComponent(query)}`,
      'youtube': `https://www.youtube.com/results?search_query=${encodeURIComponent(query)}`,
      'duckduckgo': `https://duckduckgo.com/?q=${encodeURIComponent(query)}`,
      'ddg': `https://duckduckgo.com/?q=${encodeURIComponent(query)}`
    };
    addMessage(`🔍 ${engine}'da aranıyor: "${query}"`, 'system');
    navigateTo(searchUrls[engine]);
    return 'async';
  }
  
  // Generic search - "ara: X" or just a question
  if (lower.startsWith('ara:') || lower.startsWith('ara ')) {
    const query = text.slice(lower.indexOf(' ') + 1).trim() || text.slice(4).trim();
    addMessage(`🔍 Aranıyor: "${query}"`, 'system');
    navigateTo(`https://duckduckgo.com/?q=${encodeURIComponent(query)}`);
    return 'async';
  }
  
  return null; // Not a local command, send to Core
}

// ============================================
// OVERLAY FUNCTIONS
// ============================================

let overlayActive = false;

/**
 * Inject overlay system into webview
 */
async function injectOverlaySystem() {
  try {
    await webview.executeJavaScript(`
      (function() {
        if (window.BantzOverlay) return; // Already injected
        
        window.BantzOverlay = (function() {
          let isActive = false;
          let elementList = [];
          let overlayContainer = null;
          let refreshTimeout = null;
          
          const RISKY_KEYWORDS = ['gönder', 'paylaş', 'post', 'ödeme', 'sil', 'delete', 'submit', 'pay', 'send', 'share', 'purchase', 'buy', 'remove', 'confirm', 'onayla', 'kaldır', 'publish'];
          
          function isRisky(text) {
            if (!text) return false;
            const lower = text.toLowerCase();
            return RISKY_KEYWORDS.some(kw => lower.includes(kw));
          }
          
          function getContainer() {
            if (!overlayContainer || !document.body.contains(overlayContainer)) {
              overlayContainer = document.createElement('div');
              overlayContainer.id = 'bantz-overlay-root';
              overlayContainer.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:2147483647;';
              document.body.appendChild(overlayContainer);
            }
            return overlayContainer;
          }
          
          function scanElements() {
            const selectors = 'a[href], button, input:not([type="hidden"]), textarea, select, [role="button"], [role="link"], [onclick], [tabindex="0"]';
            const elements = document.querySelectorAll(selectors);
            const results = [];
            const vh = window.innerHeight;
            const vw = window.innerWidth;
            
            elements.forEach((el) => {
              const rect = el.getBoundingClientRect();
              if (rect.width < 5 || rect.height < 5) return;
              const style = window.getComputedStyle(el);
              if (style.display === 'none' || style.visibility === 'hidden') return;
              if (rect.bottom < -20 || rect.top > vh + 20) return;
              if (rect.right < -20 || rect.left > vw + 20) return;
              
              const text = el.innerText?.trim()?.slice(0, 50) || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || el.tagName.toLowerCase();
              
              results.push({
                id: results.length + 1,
                element: el,
                text: text,
                type: el.tagName.toLowerCase(),
                href: el.href || '',
                rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height },
                isRisky: isRisky(text)
              });
            });
            
            return results.slice(0, 100);
          }
          
          function createLabel(item) {
            const label = document.createElement('div');
            let top = Math.max(2, item.rect.top);
            let left = Math.max(2, item.rect.left);
            const bgColor = item.isRisky ? '#ff4757' : '#00d9ff';
            const textColor = item.isRisky ? '#fff' : '#000';
            label.style.cssText = 'position:fixed;top:'+top+'px;left:'+left+'px;background:'+bgColor+';color:'+textColor+';padding:2px 5px;font-size:11px;font-weight:bold;font-family:sans-serif;border-radius:4px;box-shadow:0 1px 4px rgba(0,0,0,0.4);z-index:2147483647;pointer-events:none;';
            label.textContent = item.isRisky ? '⚠'+item.id : item.id;
            return label;
          }
          
          function render() {
            const container = getContainer();
            container.innerHTML = '';
            elementList.forEach(item => {
              if (item.rect.top > -20 && item.rect.top < window.innerHeight + 20) {
                container.appendChild(createLabel(item));
              }
            });
          }
          
          function refresh() {
            if (refreshTimeout) return;
            refreshTimeout = setTimeout(() => {
              elementList = scanElements();
              if (isActive) render();
              refreshTimeout = null;
            }, 100);
          }
          
          function toggle(on) {
            if (on === undefined) on = !isActive;
            if (on) {
              isActive = true;
              elementList = scanElements();
              render();
              window.addEventListener('scroll', refresh, { passive: true });
              window.addEventListener('resize', refresh, { passive: true });
            } else {
              isActive = false;
              if (overlayContainer) overlayContainer.innerHTML = '';
              window.removeEventListener('scroll', refresh);
              window.removeEventListener('resize', refresh);
            }
            return { active: isActive, count: elementList.length };
          }
          
          function getElementList() {
            if (elementList.length === 0) elementList = scanElements();
            return elementList.map(e => ({ id: e.id, text: e.text, type: e.type, href: e.href, isRisky: e.isRisky }));
          }
          
          function forceRefresh() {
            elementList = scanElements();
            if (isActive) render();
            return { active: isActive, count: elementList.length };
          }
          
          return { toggle, refresh, forceRefresh, getElementList, getStatus: () => ({ active: isActive, count: elementList.length }), isActive: () => isActive };
        })();
        
        console.log('[Bantz] Overlay system injected');
      })()
    `);
    console.log('Overlay system injected');
  } catch (err) {
    console.error('Overlay injection failed:', err);
  }
}

/**
 * Toggle overlay on/off
 */
async function toggleOverlay(on) {
  try {
    // Make sure overlay is injected first
    await injectOverlaySystem();
    
    const result = await webview.executeJavaScript(`
      window.BantzOverlay ? window.BantzOverlay.toggle(${on}) : { error: 'Overlay not loaded' }
    `);
    
    if (result.error) {
      addMessage(`❌ Overlay hatası: ${result.error}`, 'error');
      return;
    }
    
    overlayActive = result.active;
    
    if (result.active) {
      addMessage(`🏷️ Overlay açıldı! ${result.count} element numaralandırıldı.`, 'success');
      addMessage(`💡 "5'e tıkla" veya "overlay kapat" diyebilirsin.`, 'system');
      
      // Also update scan cache with overlay elements
      await syncScanCacheWithOverlay();
    } else {
      addMessage(`🏷️ Overlay kapatıldı.`, 'system');
    }
  } catch (err) {
    addMessage(`Overlay hatası: ${err.message}`, 'error');
  }
}

/**
 * Refresh overlay
 */
async function refreshOverlay() {
  try {
    const result = await webview.executeJavaScript(`
      window.BantzOverlay ? window.BantzOverlay.forceRefresh() : { error: 'Overlay not loaded' }
    `);
    
    if (result.error) {
      addMessage(`❌ ${result.error}`, 'error');
      return;
    }
    
    addMessage(`🔄 Overlay yenilendi: ${result.count} element`, 'system');
    await syncScanCacheWithOverlay();
  } catch (err) {
    addMessage(`Yenileme hatası: ${err.message}`, 'error');
  }
}

/**
 * Show overlay status
 */
async function showOverlayStatus() {
  try {
    const result = await webview.executeJavaScript(`
      window.BantzOverlay ? window.BantzOverlay.getStatus() : { active: false, count: 0 }
    `);
    
    const status = result.active ? '✅ Açık' : '❌ Kapalı';
    addMessage(`🏷️ Overlay Durumu: ${status}, ${result.count} element`, 'system');
  } catch (err) {
    addMessage(`Durum hatası: ${err.message}`, 'error');
  }
}

/**
 * Sync scan cache with overlay elements
 */
async function syncScanCacheWithOverlay() {
  try {
    const elements = await webview.executeJavaScript(`
      window.BantzOverlay ? window.BantzOverlay.getElementList() : []
    `);
    
    if (elements.length > 0) {
      scanCache = elements;
      scanOffset = 0;
    }
  } catch (err) {
    console.error('Sync error:', err);
  }
}

// ============================================
// SCAN FUNCTIONS
// ============================================

/**
 * Scan page for clickable elements
 */
async function scanPage() {
  addMessage('📋 Sayfa taranıyor...', 'system');
  
  try {
    // Use overlay's element list if available, otherwise scan directly
    let elements = await webview.executeJavaScript(`
      window.BantzOverlay ? window.BantzOverlay.getElementList() : null
    `);
    
    if (!elements) {
      // Fallback to direct scan
      elements = await webview.executeJavaScript(`
        (function() {
          const selectors = 'a, button, input, textarea, select, [role="button"], [role="link"], [onclick], [tabindex="0"]';
          const elements = document.querySelectorAll(selectors);
          const results = [];
          
          elements.forEach((el, idx) => {
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return;
            if (rect.top < 0 || rect.top > window.innerHeight) return;
            
            const text = el.innerText?.trim()?.slice(0, 50) || 
                         el.getAttribute('aria-label') ||
                         el.getAttribute('title') ||
                         el.getAttribute('alt') ||
                         el.getAttribute('placeholder') ||
                         el.value?.slice(0, 50) ||
                         el.tagName.toLowerCase();
            
            const href = el.href || '';
            const type = el.tagName.toLowerCase();
            
            results.push({
              id: results.length + 1,
              text: text,
              type: type,
              href: href,
              ariaLabel: el.getAttribute('aria-label'),
              title: el.getAttribute('title'),
              alt: el.getAttribute('alt')
            });
          });
          
          return results;
        })()
      `);
    }
    
    scanCache = elements;
    scanOffset = 0;
    showScanResults();
  } catch (err) {
    addMessage(`Tarama hatası: ${err.message}`, 'error');
  }
}

/**
 * Show scan results (paginated)
 */
function showScanResults() {
  if (scanCache.length === 0) {
    addMessage('Sayfada tıklanabilir element bulunamadı.', 'system');
    return;
  }
  
  const pageSize = 10;
  const start = scanOffset;
  const end = Math.min(start + pageSize, scanCache.length);
  const items = scanCache.slice(start, end);
  
  let output = `📋 Elementler (${start + 1}-${end} / ${scanCache.length}):\n\n`;
  items.forEach(el => {
    const icon = el.type === 'a' ? '🔗' : el.type === 'button' ? '🔘' : el.type === 'input' ? '📝' : '▪️';
    output += `[${el.id}] ${icon} ${el.text}\n`;
  });
  
  if (end < scanCache.length) {
    output += `\n💡 "daha fazla" yazarak devamını görebilirsin.`;
  }
  
  addMessage(output, 'system');
}

/**
 * Show more scan results
 */
function showMoreScanResults() {
  if (scanCache.length === 0) {
    addMessage('Önce "sayfayı tara" komutunu kullan.', 'error');
    return;
  }
  
  scanOffset += 10;
  if (scanOffset >= scanCache.length) {
    scanOffset = 0;
    addMessage('Liste başına dönüldü.', 'system');
  }
  showScanResults();
}

/**
 * Show previous scan results
 */
function showPreviousScanResults() {
  if (scanCache.length === 0) {
    addMessage('Önce "sayfayı tara" komutunu kullan.', 'error');
    return;
  }
  
  scanOffset -= 10;
  if (scanOffset < 0) {
    scanOffset = Math.max(0, scanCache.length - 10);
    addMessage('Liste sonuna gidildi.', 'system');
  }
  showScanResults();
}

/**
 * Show element detail
 */
function showElementDetail(id) {
  const el = scanCache.find(e => e.id === id);
  if (!el) {
    addMessage(`Element #${id} bulunamadı. Önce "sayfayı tara" komutunu kullan.`, 'error');
    return;
  }
  
  let output = `🔍 Element #${id} Detayı:\n\n`;
  output += `📌 Tip: ${el.type}\n`;
  output += `📝 Metin: ${el.text || '-'}\n`;
  if (el.href) output += `🔗 Link: ${el.href}\n`;
  if (el.ariaLabel) output += `🏷️ Aria-label: ${el.ariaLabel}\n`;
  if (el.title) output += `💬 Title: ${el.title}\n`;
  if (el.alt) output += `🖼️ Alt: ${el.alt}\n`;
  
  addMessage(output, 'system');
}

/**
 * Click element by ID
 */
async function clickElement(id) {
  if (scanCache.length === 0) {
    addMessage(`Sayfa henüz taranmadı. Önce "sayfayı tara" de.`, 'error');
    return;
  }
  
  const el = scanCache.find(e => e.id === id);
  if (!el) {
    addMessage(`Element #${id} bulunamadı (mevcut: 1-${scanCache.length}). Tekrar "sayfayı tara" dene.`, 'error');
    return;
  }
  
  // Check if risky
  if (isRiskyElement(el.text)) {
    pendingConfirmation = { action: 'click', element: el };
    addMessage(`⚠️ DİKKAT: "${el.text}" butonuna tıklamak istiyorsun.`, 'warning');
    addMessage(`Bu işlem geri alınamayabilir. Onaylıyor musun? (evet/hayır)`, 'system');
    return;
  }
  
  await executeClick(el);
}

/**
 * Execute click on element (after confirmation if needed)
 */
async function executeClick(el) {
  addMessage(`🖱️ Element #${el.id}'ye tıklanıyor: "${el.text}"`, 'system');
  
  try {
    // Get the element's href if it's a link (to navigate directly)
    const linkInfo = await webview.executeJavaScript(`
      (function() {
        const selectors = 'a, button, input, textarea, select, [role="button"], [role="link"], [onclick], [tabindex="0"]';
        const elements = document.querySelectorAll(selectors);
        let visibleIdx = 0;
        
        for (let el of elements) {
          const rect = el.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) continue;
          if (rect.top < 0 || rect.top > window.innerHeight) continue;
          
          visibleIdx++;
          if (visibleIdx === ${el.id}) {
            // Check if it's a link or inside a link
            const link = el.tagName === 'A' ? el : el.closest('a');
            if (link && link.href && !link.href.startsWith('javascript:')) {
              return { isLink: true, href: link.href };
            }
            return { isLink: false };
          }
        }
        return { isLink: false };
      })()
    `);
    
    // If it's a link with href, navigate directly (prevents popup issues)
    if (linkInfo.isLink && linkInfo.href) {
      addMessage(`🔗 Link'e gidiliyor: ${linkInfo.href}`, 'system');
      webview.src = linkInfo.href;
      addMessage(`✅ Navigasyon başlatıldı!`, 'success');
      setTimeout(() => { scanCache = []; scanOffset = 0; }, 500);
      return;
    }
    
    // Not a link - do a regular click
    await webview.executeJavaScript(`
      (function() {
        const selectors = 'a, button, input, textarea, select, [role="button"], [role="link"], [onclick], [tabindex="0"]';
        const elements = document.querySelectorAll(selectors);
        let visibleIdx = 0;
        
        for (let el of elements) {
          const rect = el.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) continue;
          if (rect.top < 0 || rect.top > window.innerHeight) continue;
          
          visibleIdx++;
          if (visibleIdx === ${el.id}) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            setTimeout(() => el.click(), 300);
            return true;
          }
        }
        return false;
      })()
    `);
    
    addMessage(`✅ Tıklandı!`, 'success');
    // Clear cache after navigation
    setTimeout(() => { scanCache = []; scanOffset = 0; }, 500);
  } catch (err) {
    addMessage(`Tıklama hatası: ${err.message}`, 'error');
  }
}

/**
 * Calculate fuzzy match score between two strings
 * Higher score = better match
 */
function fuzzyMatchScore(needle, haystack) {
  const n = normalizeTurkish(needle);
  const h = normalizeTurkish(haystack);
  
  // Exact match
  if (h === n) return 100;
  
  // Contains exact phrase
  if (h.includes(n)) return 90;
  if (n.includes(h)) return 85;
  
  // Word-by-word matching
  const needleWords = n.split(/\s+/).filter(w => w.length > 2);
  const haystackWords = h.split(/\s+/).filter(w => w.length > 2);
  
  if (needleWords.length === 0) return 0;
  
  let matchedWords = 0;
  let totalScore = 0;
  
  for (const nWord of needleWords) {
    for (const hWord of haystackWords) {
      if (hWord.includes(nWord) || nWord.includes(hWord)) {
        matchedWords++;
        // Longer word matches score higher
        totalScore += Math.min(nWord.length, hWord.length) * 10;
        break;
      }
    }
  }
  
  // At least 50% of words must match
  const wordMatchRatio = matchedWords / needleWords.length;
  if (wordMatchRatio < 0.5) return 0;
  
  return Math.min(80, totalScore * wordMatchRatio);
}

/**
 * Click element by text (fuzzy matching with Turkish support)
 * Enhanced to better match video titles and other content
 */
async function clickElementByText(searchText) {
  if (scanCache.length === 0) {
    addMessage(`Önce "sayfayı tara" komutunu kullan.`, 'error');
    return;
  }
  
  const normalizedSearch = normalizeTurkish(searchText);
  
  // Score all elements
  const scoredElements = scanCache.map(e => ({
    element: e,
    score: fuzzyMatchScore(searchText, e.text)
  })).filter(se => se.score > 0);
  
  // Sort by score descending
  scoredElements.sort((a, b) => b.score - a.score);
  
  // Filter to only good matches (score > 40)
  const matches = scoredElements.filter(se => se.score >= 40).map(se => se.element);
  
  if (matches.length === 0) {
    // Try a more lenient search - any word matches
    const lenientMatches = scanCache.filter(e => {
      const elementText = normalizeTurkish(e.text);
      return normalizedSearch.split(/\s+/).some(word => 
        word.length > 3 && elementText.includes(word)
      );
    });
    
    if (lenientMatches.length > 0) {
      addMessage(`🔍 Tam eşleşme bulunamadı, ama benzer ${lenientMatches.length} sonuç var:`, 'system');
      lenientMatches.slice(0, 5).forEach(e => {
        addMessage(`  [${e.id}] ${e.text}`, 'system');
      });
      addMessage(`💡 Numara ile seçebilirsin: "${lenientMatches[0].id}'e tıkla"`, 'system');
      return;
    }
    
    addMessage(`"${searchText}" içeren element bulunamadı.`, 'error');
    addMessage(`💡 İpucu: Önce "sayfayı tara" ile mevcut elementleri gör.`, 'system');
    return;
  }
  
  // Single good match or very high score match - proceed directly
  if (matches.length === 1 || scoredElements[0].score >= 85) {
    const el = matches[0];
    
    // Check if risky
    if (isRiskyElement(el.text)) {
      pendingConfirmation = { action: 'click', element: el };
      addMessage(`⚠️ DİKKAT: "${el.text}" butonuna tıklamak istiyorsun.`, 'warning');
      addMessage(`Bu işlem geri alınamayabilir. Onaylıyor musun? (evet/hayır)`, 'system');
      return;
    }
    
    await executeClick(el);
    return;
  }
  
  // Multiple matches - ask user to choose
  addMessage(`🔍 ${matches.length} eşleşme bulundu:`, 'system');
  matches.slice(0, 5).forEach(e => {
    addMessage(`  [${e.id}] ${e.text}`, 'system');
  });
  if (matches.length > 5) {
    addMessage(`  ... ve ${matches.length - 5} tane daha`, 'system');
  }
  addMessage(`💡 Hangisini istiyorsun? Örn: "${matches[0].id}'e tıkla"`, 'system');
}

/**
 * Type in element by ID
 */
async function typeInElement(id, text) {
  const el = scanCache.find(e => e.id === id);
  if (!el) {
    addMessage(`Element #${id} bulunamadı.`, 'error');
    return;
  }
  
  // Check if the text being typed is risky
  if (isRiskyElement(text)) {
    pendingConfirmation = { action: 'type', element: el, text: text };
    addMessage(`⚠️ DİKKAT: "${text}" yazmak istiyorsun.`, 'warning');
    addMessage(`İçerik hassas görünüyor. Onaylıyor musun? (evet/hayır)`, 'system');
    return;
  }
  
  await executeType(el, text);
}

/**
 * Execute type in element (after confirmation if needed)
 */
async function executeType(el, text) {
  addMessage(`⌨️ Element #${el.id}'ye yazılıyor: "${text}"`, 'system');
  
  try {
    await webview.executeJavaScript(`
      (function() {
        const selectors = 'a, button, input, textarea, select, [role="button"], [role="link"], [onclick], [tabindex="0"]';
        const elements = document.querySelectorAll(selectors);
        let visibleIdx = 0;
        
        for (let el of elements) {
          const rect = el.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) continue;
          if (rect.top < 0 || rect.top > window.innerHeight) continue;
          
          visibleIdx++;
          if (visibleIdx === ${el.id}) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            el.focus();
            el.value = ${JSON.stringify(text)};
            el.dispatchEvent(new Event('input', { bubbles: true }));
            return true;
          }
        }
        return false;
      })()
    `);
    
    addMessage(`✅ Yazıldı!`, 'success');
  } catch (err) {
    addMessage(`Yazma hatası: ${err.message}`, 'error');
  }
}

/**
 * Navigate to URL or search
 */
function navigateTo(target) {
  let url = target;
  
  if (!url.match(/^https?:\/\//)) {
    if (url.includes('.') && !url.includes(' ')) {
      url = 'https://' + url;
    } else {
      url = `https://duckduckgo.com/?q=${encodeURIComponent(url)}`;
    }
  }
  
  addMessage(`🌐 Gidiliyor: ${url}`, 'system');
  webview.src = url;
}

/**
 * Get current page state
 */
async function getPageState() {
  try {
    return {
      url: webview.getURL(),
      title: webview.getTitle()
    };
  } catch {
    return { url: '', title: '' };
  }
}

/**
 * Handle actions from Core
 */
async function handleCoreAction(action) {
  switch (action.type) {
    case 'navigate':
      navigateTo(action.url);
      break;
    case 'click':
      await clickElement(action.id);
      break;
    case 'type':
      await typeInElement(action.id, action.text);
      break;
    case 'scan':
      await scanPage();
      break;
  }
}

/**
 * Add message to output area
 */
function addMessage(text, type = 'system') {
  const msg = document.createElement('div');
  msg.className = `message ${type}`;
  
  const icon = document.createElement('span');
  icon.className = 'msg-icon';
  icon.textContent = type === 'user' ? '👤' : type === 'error' ? '❌' : type === 'success' ? '✅' : '🤖';
  
  const content = document.createElement('span');
  content.className = 'msg-text';
  content.textContent = text;
  
  // Handle preformatted text (lists)
  if (text.includes('\n')) {
    const pre = document.createElement('pre');
    pre.textContent = text;
    content.innerHTML = '';
    content.appendChild(pre);
  }
  
  msg.appendChild(icon);
  msg.appendChild(content);
  outputArea.appendChild(msg);
  
  // Scroll to bottom
  outputArea.scrollTop = outputArea.scrollHeight;
}

/**
 * Navigate command history
 */
function navigateHistory(direction) {
  if (commandHistory.length === 0) return;
  
  historyIndex += direction;
  historyIndex = Math.max(0, Math.min(historyIndex, commandHistory.length));
  
  if (historyIndex < commandHistory.length) {
    commandInput.value = commandHistory[historyIndex];
  } else {
    commandInput.value = '';
  }
}

/**
 * Update HUD display
 */
function updateHUD() {
  hudMode.textContent = currentMode;
}

/**
 * Check Core connection status (initial check only)
 */
async function checkCoreConnection() {
  try {
    const response = await window.bantz.sendCommand('__status__');
    updateCoreStatus(response.ok || response.status);
  } catch {
    updateCoreStatus(false);
  }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', init);

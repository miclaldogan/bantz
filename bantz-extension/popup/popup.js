/**
 * Bantz Browser Extension v2 - Popup Script
 */

class BantzPopup {
  constructor() {
    this.port = null;
    this.currentTab = null;
    this.state = {
      connected: false,
      overlayEnabled: true,
    };

    this.init();
  }

  async init() {
    // Get current tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    this.currentTab = tab;

    // Update page info
    this.updatePageInfo();

    // Connect to background
    this.connectToBackground();

    // Set up event listeners
    this.setupEventListeners();

    // Get initial stats
    this.getPageStats();
  }

  connectToBackground() {
    this.port = chrome.runtime.connect({ name: 'popup' });

    this.port.onMessage.addListener((message) => {
      if (message.type === 'state') {
        this.updateState(message);
      }
    });

    // Request initial state
    this.port.postMessage({ type: 'get_state' });
  }

  updateState(state) {
    this.state = { ...this.state, ...state };

    // Update UI
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const overlayToggle = document.getElementById('overlay-toggle');

    if (state.connected) {
      statusDot.classList.remove('disconnected');
      statusDot.classList.add('connected');
      statusText.textContent = 'Bantz\'a bağlı';
    } else {
      statusDot.classList.remove('connected');
      statusDot.classList.add('disconnected');
      statusText.textContent = 'Bağlantı yok';
    }

    if (state.overlayEnabled) {
      overlayToggle.classList.add('active');
    } else {
      overlayToggle.classList.remove('active');
    }
  }

  updatePageInfo() {
    if (!this.currentTab) return;

    const titleEl = document.getElementById('page-title');
    const urlEl = document.getElementById('page-url');

    titleEl.textContent = this.currentTab.title || 'Bilinmeyen Sayfa';
    
    try {
      const url = new URL(this.currentTab.url);
      urlEl.textContent = url.hostname + url.pathname.slice(0, 30);
    } catch {
      urlEl.textContent = this.currentTab.url?.slice(0, 40) || '-';
    }
  }

  async getPageStats() {
    if (!this.currentTab?.id) return;

    try {
      // Get page info from content script
      const response = await chrome.tabs.sendMessage(this.currentTab.id, {
        type: 'get_page_info',
      });

      if (response?.success && response.data) {
        const data = response.data;
        document.getElementById('element-count').textContent = '-';
        document.getElementById('link-count').textContent = data.linkCount || 0;
        document.getElementById('form-count').textContent = data.formCount || 0;
      }
    } catch (e) {
      console.log('Could not get page stats:', e);
    }
  }

  setupEventListeners() {
    // Overlay toggle
    document.getElementById('overlay-toggle').addEventListener('click', () => {
      this.port.postMessage({ type: 'toggle_overlay' });
    });

    // Reconnect button
    document.getElementById('btn-reconnect').addEventListener('click', () => {
      this.port.postMessage({ type: 'reconnect' });
    });

    // Scan button
    document.getElementById('btn-scan').addEventListener('click', async () => {
      await this.scanPage();
    });

    // Forms button
    document.getElementById('btn-forms').addEventListener('click', async () => {
      await this.detectForms();
    });

    // Screenshot button
    document.getElementById('btn-screenshot').addEventListener('click', async () => {
      await this.takeScreenshot();
    });

    // Extract button
    document.getElementById('btn-extract').addEventListener('click', async () => {
      await this.extractContent();
    });

    // Settings button
    document.getElementById('btn-settings').addEventListener('click', () => {
      // Open settings page
      chrome.runtime.openOptionsPage?.() || 
        chrome.tabs.create({ url: 'options.html' });
    });
  }

  async scanPage() {
    if (!this.currentTab?.id) return;

    const btn = document.getElementById('btn-scan');
    btn.innerHTML = '<span class="icon">⏳</span><span>Taranıyor...</span>';

    try {
      const response = await chrome.tabs.sendMessage(this.currentTab.id, {
        type: 'scan',
        maxElements: 50,
      });

      if (response?.success && response.data) {
        document.getElementById('element-count').textContent = response.data.count;
        this.showNotification(`${response.data.count} element bulundu`);
      }
    } catch (e) {
      this.showNotification('Tarama başarısız', 'error');
    }

    btn.innerHTML = '<span class="icon">🔍</span><span>Tara</span>';
  }

  async detectForms() {
    if (!this.currentTab?.id) return;

    const btn = document.getElementById('btn-forms');
    btn.innerHTML = '<span class="icon">⏳</span><span>Arıyor...</span>';

    try {
      const response = await chrome.tabs.sendMessage(this.currentTab.id, {
        type: 'detect_forms',
      });

      if (response?.success && response.data) {
        const count = response.data.count;
        document.getElementById('form-count').textContent = count;

        if (count > 0) {
          const types = response.data.forms.map(f => f.type).join(', ');
          this.showNotification(`${count} form: ${types}`);
        } else {
          this.showNotification('Form bulunamadı');
        }
      }
    } catch (e) {
      this.showNotification('Form tarama başarısız', 'error');
    }

    btn.innerHTML = '<span class="icon">📝</span><span>Formlar</span>';
  }

  async takeScreenshot() {
    const btn = document.getElementById('btn-screenshot');
    btn.innerHTML = '<span class="icon">⏳</span><span>Çekiliyor...</span>';

    try {
      const response = await chrome.runtime.sendMessage({
        type: 'capture_screenshot',
      });

      if (response?.success) {
        // Download the screenshot
        const link = document.createElement('a');
        link.href = response.data;
        link.download = `bantz-screenshot-${Date.now()}.png`;
        link.click();
        
        this.showNotification('Ekran görüntüsü alındı');
      } else {
        throw new Error(response?.error || 'Unknown error');
      }
    } catch (e) {
      this.showNotification('Ekran görüntüsü alınamadı', 'error');
    }

    btn.innerHTML = '<span class="icon">📷</span><span>Ekran Görüntüsü</span>';
  }

  async extractContent() {
    if (!this.currentTab?.id) return;

    const btn = document.getElementById('btn-extract');
    btn.innerHTML = '<span class="icon">⏳</span><span>Çıkarılıyor...</span>';

    try {
      const response = await chrome.tabs.sendMessage(this.currentTab.id, {
        type: 'extract_content',
        maxTextLength: 5000,
      });

      if (response?.success && response.data) {
        // Copy summary to clipboard
        const summary = `Başlık: ${response.data.title}\nURL: ${response.data.url}\n\n${response.data.text.slice(0, 500)}...`;
        
        await navigator.clipboard.writeText(summary);
        this.showNotification('İçerik panoya kopyalandı');
      }
    } catch (e) {
      this.showNotification('İçerik çıkarılamadı', 'error');
    }

    btn.innerHTML = '<span class="icon">📄</span><span>İçerik Çıkar</span>';
  }

  showNotification(message, type = 'success') {
    const statusText = document.getElementById('status-text');
    const originalText = statusText.textContent;
    
    statusText.textContent = message;
    statusText.style.color = type === 'error' ? '#F44336' : '#4CAF50';

    setTimeout(() => {
      statusText.textContent = originalText;
      statusText.style.color = '';
    }, 2000);
  }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  new BantzPopup();
});

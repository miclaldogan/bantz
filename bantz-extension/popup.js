/**
 * Bantz Extension Popup Script
 */

let overlayEnabled = true;

// Get status from background
async function updateStatus() {
  try {
    const status = await browser.runtime.sendMessage({ type: 'bantz:get_status' });
    
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    
    if (status.connected) {
      dot.classList.add('connected');
      text.textContent = 'Bantz Daemon bağlı';
    } else {
      dot.classList.remove('connected');
      text.textContent = 'Bağlantı yok - Daemon çalışıyor mu?';
    }
    
    overlayEnabled = status.overlayEnabled;
    updateToggleButton();
  } catch (e) {
    console.error('Status error:', e);
  }
}

function updateToggleButton() {
  const btn = document.getElementById('btn-toggle');
  btn.textContent = overlayEnabled ? '👁 Overlay Kapat' : '👁 Overlay Aç';
}

// Scan button
document.getElementById('btn-scan').addEventListener('click', async () => {
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
  if (tabs[0]) {
    browser.tabs.sendMessage(tabs[0].id, { type: 'bantz:scan' });
    window.close();
  }
});

// Toggle overlay
document.getElementById('btn-toggle').addEventListener('click', async () => {
  overlayEnabled = !overlayEnabled;
  
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
  if (tabs[0]) {
    browser.tabs.sendMessage(tabs[0].id, { 
      type: 'bantz:overlay', 
      enabled: overlayEnabled 
    });
  }
  
  updateToggleButton();
});

// Initialize
updateStatus();

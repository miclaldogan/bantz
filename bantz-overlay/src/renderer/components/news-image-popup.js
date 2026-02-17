/**
 * Bantz Overlay — News Image Popup
 *
 * Floating terminal panel that shows article images during briefings.
 * Multiple popups can stack, auto-dismiss after 8s, and show
 * error placeholders for failed loads.
 *
 * @module news-image-popup
 */

// ─── Configuration ──────────────────────────────────────────────
const IMAGE_CONFIG = {
  maxConcurrent: 3,
  autoDismissMs: 8000,
  fadeInMs: 400,
  fadeOutMs: 300,
  popupWidth: 280,
  popupHeight: 200,
  captionMaxChars: 60,
  stackOffsetX: 20,     // px offset per stacked popup
  stackOffsetY: 15,
  baseTop: 10,          // % from top of HUD
  baseRight: -140,      // px (overflows right, near news feed)
};

const ERROR_PLACEHOLDER = `
┌──────────────────────┐
│                      │
│  [GÖRSEL YÜKLENEMEDİ]│
│                      │
│      ╳  ╳  ╳         │
│                      │
└──────────────────────┘`.trim();

/**
 * NewsImagePopup — floating image terminal.
 */
class NewsImagePopup {
  /**
   * @param {HTMLElement} parent - The HUD panel to mount popups into
   */
  constructor(parent) {
    this._parent = parent;
    this._popups = [];    // active popup elements
    this._timers = [];    // auto-dismiss timers
  }

  // ─── Public API ───────────────────────────────────────────────

  /**
   * Show an image popup for a news article.
   * @param {{ image_url: string, title?: string, source?: string, url?: string }} article
   */
  show(article) {
    // FIFO: dismiss oldest if at max
    while (this._popups.length >= IMAGE_CONFIG.maxConcurrent) {
      this._dismiss(0);
    }

    const index = this._popups.length;
    const popup = this._createPopup(article, index);
    this._parent.appendChild(popup);
    this._popups.push(popup);

    // Trigger fade-in
    requestAnimationFrame(() => {
      popup.classList.add('news-image-visible');
    });

    // Auto-dismiss timer
    const timer = setTimeout(() => {
      const idx = this._popups.indexOf(popup);
      if (idx !== -1) this._dismiss(idx);
    }, IMAGE_CONFIG.autoDismissMs);
    this._timers.push(timer);

    // Pause auto-dismiss on hover
    popup.addEventListener('mouseenter', () => {
      const idx = this._popups.indexOf(popup);
      if (idx !== -1 && this._timers[idx]) {
        clearTimeout(this._timers[idx]);
        this._timers[idx] = null;
      }
    });

    // Resume auto-dismiss on mouse leave
    popup.addEventListener('mouseleave', () => {
      const idx = this._popups.indexOf(popup);
      if (idx !== -1) {
        this._timers[idx] = setTimeout(() => {
          const i = this._popups.indexOf(popup);
          if (i !== -1) this._dismiss(i);
        }, IMAGE_CONFIG.autoDismissMs);
      }
    });
  }

  /**
   * Dismiss all popups.
   */
  clear() {
    while (this._popups.length > 0) {
      this._dismiss(0);
    }
  }

  /**
   * Clean up.
   */
  dispose() {
    this.clear();
  }

  // ─── Internal ─────────────────────────────────────────────────

  /**
   * Create a popup element.
   * @private
   */
  _createPopup(article, index) {
    const popup = document.createElement('div');
    popup.className = 'news-image-popup terminal-panel';

    // Position with stacking offset
    const offsetX = index * IMAGE_CONFIG.stackOffsetX;
    const offsetY = index * IMAGE_CONFIG.stackOffsetY;
    const rotation = -2 + Math.random() * 5; // -2° to +3°

    popup.style.cssText = `
      position: absolute;
      top: calc(${IMAGE_CONFIG.baseTop}% + ${offsetY}px);
      right: ${IMAGE_CONFIG.baseRight - offsetX}px;
      width: ${IMAGE_CONFIG.popupWidth}px;
      height: ${IMAGE_CONFIG.popupHeight}px;
      transform: scale(0.95) rotate(${rotation}deg);
      opacity: 0;
      transition: opacity ${IMAGE_CONFIG.fadeInMs}ms ease-out,
                  transform ${IMAGE_CONFIG.fadeInMs}ms ease-out;
      z-index: ${50 + index};
      display: flex;
      flex-direction: column;
      overflow: hidden;
    `;

    // Header
    const header = document.createElement('div');
    header.className = 'terminal-header';
    header.innerHTML = `
      <div class="terminal-dots">
        <span class="dot dot-red"></span>
        <span class="dot dot-yellow"></span>
        <span class="dot dot-green"></span>
      </div>
      <span class="terminal-title">> GÖRSEL${article.source ? ' — ' + article.source : ''}</span>
    `;
    popup.appendChild(header);

    // Image container
    const imgContainer = document.createElement('div');
    imgContainer.className = 'news-image-container';
    imgContainer.style.cssText = `
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      background: rgba(0, 10, 20, 0.5);
    `;

    // Skeleton placeholder
    const skeleton = document.createElement('div');
    skeleton.className = 'news-image-skeleton';
    skeleton.textContent = '[ yükleniyor... ]';
    imgContainer.appendChild(skeleton);

    // Load image
    const img = document.createElement('img');
    img.style.cssText = `
      max-width: 100%;
      max-height: 100%;
      object-fit: cover;
      display: none;
      cursor: pointer;
    `;
    img.alt = article.title || 'Haber görseli';
    img.loading = 'lazy';

    img.onload = () => {
      skeleton.style.display = 'none';
      img.style.display = 'block';
    };

    img.onerror = () => {
      skeleton.textContent = ERROR_PLACEHOLDER;
      skeleton.style.whiteSpace = 'pre';
      skeleton.style.fontSize = '0.7em';
      skeleton.style.color = 'rgba(0, 229, 255, 0.4)';
    };

    img.src = article.image_url;

    // Click → open in browser
    if (article.url) {
      img.addEventListener('click', () => {
        if (window.overlayAPI && window.overlayAPI.sendDaemonEvent) {
          window.overlayAPI.sendDaemonEvent({
            type: 'open_url',
            url: article.url,
          });
        }
      });
    }

    imgContainer.appendChild(img);
    popup.appendChild(imgContainer);

    // Caption
    if (article.title) {
      const caption = document.createElement('div');
      caption.className = 'news-image-caption';
      const truncated = article.title.length > IMAGE_CONFIG.captionMaxChars
        ? article.title.slice(0, IMAGE_CONFIG.captionMaxChars) + '…'
        : article.title;
      caption.textContent = truncated;
      popup.appendChild(caption);
    }

    return popup;
  }

  /**
   * Dismiss a popup at the given index.
   * @private
   */
  _dismiss(index) {
    if (index < 0 || index >= this._popups.length) return;

    const popup = this._popups[index];
    const timer = this._timers[index];

    if (timer) clearTimeout(timer);

    // Fade out
    popup.style.opacity = '0';
    popup.style.transform = popup.style.transform.replace(/scale\([^)]+\)/, 'scale(0.9)');

    setTimeout(() => {
      if (popup.parentNode) popup.parentNode.removeChild(popup);
    }, IMAGE_CONFIG.fadeOutMs);

    this._popups.splice(index, 1);
    this._timers.splice(index, 1);

    // Re-position remaining popups
    this._repositionPopups();
  }

  /**
   * Re-position remaining popups after dismissal.
   * @private
   */
  _repositionPopups() {
    this._popups.forEach((popup, i) => {
      const offsetX = i * IMAGE_CONFIG.stackOffsetX;
      const offsetY = i * IMAGE_CONFIG.stackOffsetY;
      popup.style.top = `calc(${IMAGE_CONFIG.baseTop}% + ${offsetY}px)`;
      popup.style.right = `${IMAGE_CONFIG.baseRight - offsetX}px`;
      popup.style.zIndex = `${50 + i}`;
    });
  }
}

// ─── CSS Injection ──────────────────────────────────────────────
(function injectImagePopupStyles() {
  if (document.getElementById('news-image-styles')) return;

  const style = document.createElement('style');
  style.id = 'news-image-styles';
  style.textContent = `
    .news-image-popup {
      pointer-events: auto;
    }

    .news-image-popup.news-image-visible {
      opacity: 1 !important;
      transform: scale(1) rotate(var(--rotation, 0deg)) !important;
    }

    .news-image-skeleton {
      color: rgba(0, 229, 255, 0.3);
      font-family: 'JetBrains Mono', 'Fira Code', monospace;
      font-size: 0.8em;
      text-align: center;
      animation: skeleton-pulse 1.5s ease-in-out infinite;
    }

    @keyframes skeleton-pulse {
      0%, 100% { opacity: 0.3; }
      50% { opacity: 0.8; }
    }

    .news-image-caption {
      padding: 4px 8px;
      font-family: 'JetBrains Mono', 'Fira Code', monospace;
      font-size: 0.75em;
      color: rgba(0, 229, 255, 0.7);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      background: rgba(0, 10, 20, 0.6);
      border-top: 1px solid rgba(0, 229, 255, 0.1);
    }
  `;
  document.head.appendChild(style);
})();

// Expose globally
window.NewsImagePopup = NewsImagePopup;

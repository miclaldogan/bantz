/**
 * Bantz Overlay — News Feed Panel
 *
 * A scrolling terminal panel that displays real-time news articles
 * in monospace format, like a stock ticker / newsreel.
 *
 * Subscribes to IPC briefing_card messages (type=news) and renders
 * articles with timestamps. Auto-scrolls upward, pauses on hover,
 * highlights the active article when the assistant speaks about it.
 *
 * @module news-feed
 */

// ─── Configuration ──────────────────────────────────────────────
const NEWS_CONFIG = {
  maxArticles: 50,           // FIFO limit
  scrollSpeed: 30,           // px/s auto-scroll
  highlightDuration: 3000,   // ms for active article highlight
  tooltipDelay: 400,         // ms before showing tooltip
  panelWidth: 380,
  panelHeight: 480,
};

/**
 * NewsFeedPanel — scrolling news terminal.
 */
class NewsFeedPanel {
  /**
   * @param {HTMLElement} parent - The HUD panel to mount into
   */
  constructor(parent) {
    this._parent = parent;
    this._articles = [];
    this._activeArticleId = null;
    this._isPaused = false;
    this._scrollInterval = null;
    this._tooltipTimeout = null;
    this._tooltip = null;
    this._mounted = false;

    // Use the TerminalPanel base component
    this._panel = new window.TerminalPanel({
      id: 'news-feed',
      title: '> HABER AKIŞI',
      slot: 'right',
      width: NEWS_CONFIG.panelWidth,
      height: NEWS_CONFIG.panelHeight,
    });

    // Custom content area
    this._contentEl = null;
    this._cursorEl = null;
  }

  /** @returns {HTMLElement|null} The underlying DOM element */
  get element() { return this._panel ? this._panel.element : null; }

  // ─── Public API ───────────────────────────────────────────────

  /**
   * Mount the news panel into the DOM.
   */
  mount() {
    this._panel.mount(this._parent);

    // Get the panel's content container
    const panelEl = this._parent.querySelector('#terminal-news-feed');
    if (!panelEl) { console.error('[NewsFeed] Panel element not found'); return; }

    const content = panelEl.querySelector('.terminal-content, .terminal-panel-content');
    if (!content) return;

    this._contentEl = content;

    // Style the content for news feed
    this._contentEl.style.cssText += `
      scroll-behavior: smooth;
      padding: 6px 8px;
      line-height: 1.6;
    `;

    // Add blinking cursor at bottom
    this._cursorEl = document.createElement('div');
    this._cursorEl.className = 'news-cursor';
    this._cursorEl.innerHTML = '<span class="cursor-blink">█</span>';
    this._contentEl.appendChild(this._cursorEl);

    // Create tooltip element
    this._tooltip = document.createElement('div');
    this._tooltip.className = 'news-tooltip';
    this._tooltip.style.display = 'none';
    panelEl.appendChild(this._tooltip);

    // Hover handlers
    this._contentEl.addEventListener('mouseenter', () => this._pause());
    this._contentEl.addEventListener('mouseleave', () => this._resume());

    // Start auto-scroll
    this._startAutoScroll();

    this._mounted = true;
    console.log('[NewsFeed] Mounted');
  }

  /**
   * Show the panel.
   */
  show() {
    this._panel.show();
  }

  /**
   * Hide the panel.
   */
  hide() {
    this._panel.hide();
  }

  /**
   * Add a news article from a briefing_card message.
   * @param {{ title: string, source?: string, summary?: string, link?: string, id?: string, ts?: number }} article
   */
  addArticle(article) {
    const now = new Date(article.ts || Date.now());
    const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

    const entry = {
      id: article.id || `news-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      title: article.title || 'Untitled',
      source: article.source || '',
      summary: article.summary || '',
      link: article.link || '',
      time,
      element: null,
    };

    // FIFO: remove oldest if at limit
    if (this._articles.length >= NEWS_CONFIG.maxArticles) {
      const removed = this._articles.shift();
      if (removed.element && removed.element.parentNode) {
        removed.element.parentNode.removeChild(removed.element);
      }
    }

    this._articles.push(entry);
    this._renderArticle(entry);

    return entry.id;
  }

  /**
   * Highlight an article (when the assistant is speaking about it).
   * @param {string} articleId
   */
  highlightArticle(articleId) {
    // Remove previous highlight
    if (this._activeArticleId) {
      const prevEl = this._contentEl?.querySelector(`[data-article-id="${this._activeArticleId}"]`);
      if (prevEl) prevEl.classList.remove('news-active');
    }

    this._activeArticleId = articleId;
    const el = this._contentEl?.querySelector(`[data-article-id="${articleId}"]`);
    if (el) {
      el.classList.add('news-active');
      // Scroll to it
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });

      // Auto-remove highlight after duration
      setTimeout(() => {
        el.classList.remove('news-active');
        if (this._activeArticleId === articleId) {
          this._activeArticleId = null;
        }
      }, NEWS_CONFIG.highlightDuration);
    }
  }

  /**
   * Clear all articles.
   */
  clear() {
    this._articles = [];
    if (this._contentEl) {
      this._contentEl.innerHTML = '';
      this._contentEl.appendChild(this._cursorEl);
    }
  }

  /**
   * Clean up.
   */
  dispose() {
    this._stopAutoScroll();
    if (this._tooltipTimeout) clearTimeout(this._tooltipTimeout);
    this._panel.unmount();
  }

  // ─── Internal ─────────────────────────────────────────────────

  /**
   * Render a single article entry into the content area.
   * @private
   */
  _renderArticle(entry) {
    if (!this._contentEl) return;

    const line = document.createElement('div');
    line.className = 'news-article terminal-line';
    line.setAttribute('data-article-id', entry.id);

    // Format: [HH:MM] TITLE — source
    const timeSpan = document.createElement('span');
    timeSpan.className = 'news-time';
    timeSpan.textContent = `[${entry.time}] `;

    const titleSpan = document.createElement('span');
    titleSpan.className = 'news-title';
    titleSpan.textContent = entry.title;

    line.appendChild(timeSpan);
    line.appendChild(titleSpan);

    if (entry.source) {
      const sourceSpan = document.createElement('span');
      sourceSpan.className = 'news-source';
      sourceSpan.textContent = ` — ${entry.source}`;
      line.appendChild(sourceSpan);
    }

    // Tooltip on hover
    line.addEventListener('mouseenter', (e) => this._showTooltip(entry, e));
    line.addEventListener('mouseleave', () => this._hideTooltip());

    // Click to open article in browser
    if (entry.link) {
      line.style.cursor = 'pointer';
      line.addEventListener('click', () => {
        if (window.overlayAPI && window.overlayAPI.openExternal) {
          window.overlayAPI.openExternal(entry.link);
        }
      });
    }

    // Insert before cursor
    this._contentEl.insertBefore(line, this._cursorEl);

    entry.element = line;
  }

  /**
   * Show tooltip with article summary.
   * @private
   */
  _showTooltip(entry, event) {
    if (!entry.summary || !this._tooltip) return;

    if (this._tooltipTimeout) clearTimeout(this._tooltipTimeout);

    this._tooltipTimeout = setTimeout(() => {
      this._tooltip.textContent = entry.summary;
      this._tooltip.style.display = 'block';

      // Position near the line
      const rect = event.target.getBoundingClientRect();
      const panelRect = this._tooltip.parentElement.getBoundingClientRect();
      this._tooltip.style.top = `${rect.top - panelRect.top - 40}px`;
      this._tooltip.style.left = '10px';
      this._tooltip.style.right = '10px';
    }, NEWS_CONFIG.tooltipDelay);
  }

  /**
   * Hide the tooltip.
   * @private
   */
  _hideTooltip() {
    if (this._tooltipTimeout) clearTimeout(this._tooltipTimeout);
    if (this._tooltip) {
      this._tooltip.style.display = 'none';
    }
  }

  /**
   * Start auto-scroll interval.
   * @private
   */
  _startAutoScroll() {
    this._stopAutoScroll();
    const interval = 1000 / 60; // ~60fps
    const pxPerTick = NEWS_CONFIG.scrollSpeed / 60;

    this._scrollInterval = setInterval(() => {
      if (this._isPaused || !this._contentEl) return;

      const el = this._contentEl;
      const maxScroll = el.scrollHeight - el.clientHeight;
      if (el.scrollTop < maxScroll) {
        el.scrollTop += pxPerTick;
      }
    }, interval);
  }

  /**
   * Stop auto-scroll.
   * @private
   */
  _stopAutoScroll() {
    if (this._scrollInterval) {
      clearInterval(this._scrollInterval);
      this._scrollInterval = null;
    }
  }

  /**
   * Pause auto-scroll (on hover).
   * @private
   */
  _pause() {
    this._isPaused = true;
  }

  /**
   * Resume auto-scroll.
   * @private
   */
  _resume() {
    this._isPaused = false;
    this._hideTooltip();
  }
}

// ─── CSS Injection ──────────────────────────────────────────────
// Inject news-feed-specific styles
(function injectNewsFeedStyles() {
  if (document.getElementById('news-feed-styles')) return;

  const style = document.createElement('style');
  style.id = 'news-feed-styles';
  style.textContent = `
    /* News article line */
    .news-article {
      padding: 3px 0;
      border-left: 2px solid transparent;
      padding-left: 6px;
      transition: border-color 0.3s, background-color 0.3s;
      cursor: default;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .news-article:hover {
      background: rgba(0, 229, 255, 0.05);
      border-left-color: rgba(0, 229, 255, 0.3);
    }

    /* Active article (speaking about) */
    .news-article.news-active {
      border-left-color: #ffd600;
      background: rgba(255, 214, 0, 0.08);
      animation: news-highlight-flash 0.5s ease-out;
    }

    @keyframes news-highlight-flash {
      0% { background: rgba(255, 214, 0, 0.25); }
      100% { background: rgba(255, 214, 0, 0.08); }
    }

    /* Time stamp */
    .news-time {
      color: rgba(0, 229, 255, 0.5);
      font-size: 0.85em;
    }

    /* Title */
    .news-title {
      color: rgba(0, 229, 255, 0.9);
    }

    /* Source */
    .news-source {
      color: rgba(0, 229, 255, 0.4);
      font-size: 0.85em;
      font-style: italic;
    }

    /* Blinking cursor */
    .news-cursor {
      color: rgba(0, 229, 255, 0.6);
      font-size: 0.9em;
      padding: 2px 0;
    }

    .cursor-blink {
      animation: cursor-blink 1s step-end infinite;
    }

    @keyframes cursor-blink {
      0%, 50% { opacity: 1; }
      51%, 100% { opacity: 0; }
    }

    /* Tooltip */
    .news-tooltip {
      position: absolute;
      background: rgba(10, 14, 20, 0.95);
      border: 1px solid rgba(0, 229, 255, 0.3);
      border-radius: 4px;
      padding: 8px 10px;
      font-size: 0.8em;
      color: rgba(0, 229, 255, 0.8);
      line-height: 1.4;
      z-index: 100;
      pointer-events: none;
      max-height: 80px;
      overflow: hidden;
      backdrop-filter: blur(8px);
    }
  `;
  document.head.appendChild(style);
})();

// Expose globally (loaded as regular script before ES modules)
window.NewsFeedPanel = NewsFeedPanel;

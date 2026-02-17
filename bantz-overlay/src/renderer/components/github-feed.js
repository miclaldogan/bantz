/**
 * Bantz Overlay — GitHub Feed Panel
 *
 * A scrolling terminal panel that displays GitHub activity feed:
 * - Recent commits, PRs, issues from configured repositories
 * - Notifications and mentions
 * - Color-coded by event type
 *
 * Fetches data via overlayAPI.getGitHubFeed() IPC bridge.
 *
 * @module github-feed
 */

// ─── Configuration ──────────────────────────────────────────────
const GH_FEED_CONFIG = {
  maxItems: 60,
  refreshInterval: 60_000,   // 60s auto-refresh
  panelWidth: 340,
  panelHeight: 480,
  animateIn: true,
};

// Event type styling
const EVENT_STYLES = {
  push:         { icon: '⬆', color: '#4ec9b0', label: 'PUSH' },
  pull_request: { icon: '⎇', color: '#c586c0', label: 'PR' },
  issue:        { icon: '●', color: '#f5c842', label: 'ISSUE' },
  review:       { icon: '✓', color: '#6ab04c', label: 'REVIEW' },
  release:      { icon: '◆', color: '#ce9178', label: 'RELEASE' },
  star:         { icon: '★', color: '#f5c842', label: 'STAR' },
  fork:         { icon: '⑂', color: '#569cd6', label: 'FORK' },
  comment:      { icon: '💬', color: '#9cdcfe', label: 'COMMENT' },
  notification: { icon: '🔔', color: '#ff6b6b', label: 'NOTIF' },
  default:      { icon: '·', color: '#808080', label: 'EVENT' },
};

/**
 * GitHubFeedPanel — scrolling GitHub activity terminal.
 */
class GitHubFeedPanel {
  /**
   * @param {HTMLElement} parent - The HUD panel to mount into
   */
  constructor(parent) {
    this._parent = parent;
    this._items = [];
    this._mounted = false;
    this._refreshTimer = null;
    this._isPaused = false;

    // Use the TerminalPanel base component
    this._panel = new window.TerminalPanel({
      id: 'github-feed',
      title: '> GITHUB',
      slot: 'right',
      width: GH_FEED_CONFIG.panelWidth,
      height: GH_FEED_CONFIG.panelHeight,
    });

    this._contentEl = null;
    this._badgeEl = null;
    this._unreadCount = 0;
  }

  /** @returns {HTMLElement|null} The underlying DOM element */
  get element() { return this._panel ? this._panel.element : null; }

  // ─── Public API ───────────────────────────────────────────────

  /**
   * Mount the panel into the DOM.
   */
  mount() {
    if (this._mounted) return;
    this._panel.mount(this._parent);
    this._mounted = true;
    this._buildContent();
    this._injectStyles();
    this._startAutoRefresh();
    this._fetchFeed(); // Initial load
  }

  /** Show the panel */
  show() { this._panel.show(); }

  /** Hide the panel */
  hide() { this._panel.hide(); }

  /**
   * Add a GitHub event item to the feed.
   * @param {Object} item - GitHub event data
   * @param {string} item.type - Event type (push, pull_request, issue, etc.)
   * @param {string} item.repo - Repository name (owner/repo)
   * @param {string} item.title - Event title/description
   * @param {string} [item.actor] - Username who triggered the event
   * @param {string} [item.url] - Link to the event on GitHub
   * @param {string} [item.ts] - Timestamp
   * @param {string} [item.id] - Unique event ID
   * @param {string} [item.branch] - Branch name (for push events)
   * @param {number} [item.number] - PR/Issue number
   * @returns {string} Generated item ID
   */
  addItem(item) {
    const id = item.id || `gh-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const eventType = this._normalizeEventType(item.type);
    const style = EVENT_STYLES[eventType] || EVENT_STYLES.default;

    const entry = {
      id,
      type: eventType,
      repo: item.repo || '',
      title: item.title || '',
      actor: item.actor || '',
      url: item.url || '',
      ts: item.ts || new Date().toISOString(),
      branch: item.branch || '',
      number: item.number || null,
      style,
    };

    this._items.unshift(entry); // newest first

    // FIFO limit
    if (this._items.length > GH_FEED_CONFIG.maxItems) {
      this._items = this._items.slice(0, GH_FEED_CONFIG.maxItems);
    }

    this._renderItem(entry, true);
    return id;
  }

  /**
   * Set multiple items at once (replaces current feed).
   * @param {Array} items - Array of GitHub event objects
   */
  setItems(items) {
    this._items = [];
    if (this._contentEl) this._contentEl.innerHTML = '';

    if (!items || items.length === 0) {
      this._showEmptyState();
      return;
    }

    items.forEach(item => this.addItem(item));
  }

  /**
   * Update unread notification count.
   * @param {number} count
   */
  setUnreadCount(count) {
    this._unreadCount = count;
    if (this._badgeEl) {
      this._badgeEl.textContent = count > 0 ? String(count) : '';
      this._badgeEl.style.display = count > 0 ? 'inline-block' : 'none';
    }
  }

  /** Destroy the panel and cleanup */
  destroy() {
    if (this._refreshTimer) {
      clearInterval(this._refreshTimer);
      this._refreshTimer = null;
    }
    if (this._panel) this._panel.destroy();
    this._mounted = false;
  }

  // ─── Private ──────────────────────────────────────────────────

  _normalizeEventType(type) {
    if (!type) return 'default';
    const t = type.toLowerCase().replace(/event$/i, '').replace(/_/g, '_');
    if (t.includes('push')) return 'push';
    if (t.includes('pull') || t.includes('pr')) return 'pull_request';
    if (t.includes('issue') && !t.includes('comment')) return 'issue';
    if (t.includes('review')) return 'review';
    if (t.includes('release')) return 'release';
    if (t.includes('star') || t.includes('watch')) return 'star';
    if (t.includes('fork')) return 'fork';
    if (t.includes('comment')) return 'comment';
    if (t.includes('notif')) return 'notification';
    return 'default';
  }

  _buildContent() {
    const body = this._panel.bodyElement;
    if (!body) return;

    body.innerHTML = '';

    // Header with unread badge
    const header = document.createElement('div');
    header.className = 'gh-feed-header';
    header.innerHTML = `
      <span class="gh-feed-title">⑂ Activity</span>
      <span class="gh-feed-badge" style="display:none"></span>
      <button class="gh-feed-refresh" title="Refresh">↻</button>
    `;
    body.appendChild(header);

    this._badgeEl = header.querySelector('.gh-feed-badge');

    // Refresh button
    header.querySelector('.gh-feed-refresh').addEventListener('click', () => {
      this._fetchFeed();
    });

    // Scrollable content
    this._contentEl = document.createElement('div');
    this._contentEl.className = 'gh-feed-content';
    body.appendChild(this._contentEl);

    // Pause scrolling on hover
    this._contentEl.addEventListener('mouseenter', () => { this._isPaused = true; });
    this._contentEl.addEventListener('mouseleave', () => { this._isPaused = false; });

    this._showEmptyState();
  }

  _showEmptyState() {
    if (!this._contentEl) return;
    if (this._items.length === 0) {
      this._contentEl.innerHTML = `
        <div class="gh-feed-empty">
          <span style="opacity:0.4; font-size:14px">⑂</span>
          <span style="opacity:0.3; font-size:11px; margin-top:8px">Loading GitHub feed...</span>
        </div>
      `;
    }
  }

  _renderItem(entry, animate = false) {
    if (!this._contentEl) return;

    // Remove empty state if present
    const empty = this._contentEl.querySelector('.gh-feed-empty');
    if (empty) empty.remove();

    const el = document.createElement('div');
    el.className = 'gh-feed-item';
    el.dataset.id = entry.id;
    el.dataset.type = entry.type;

    if (animate && GH_FEED_CONFIG.animateIn) {
      el.classList.add('gh-feed-item-enter');
    }

    const timeStr = this._formatTime(entry.ts);
    const repoShort = entry.repo.includes('/') ? entry.repo.split('/')[1] : entry.repo;

    // Build title with PR/Issue number
    let titleText = entry.title;
    if (entry.number) {
      titleText = `#${entry.number} ${titleText}`;
    }

    el.innerHTML = `
      <div class="gh-feed-item-header">
        <span class="gh-feed-icon" style="color:${entry.style.color}">${entry.style.icon}</span>
        <span class="gh-feed-label" style="color:${entry.style.color}">${entry.style.label}</span>
        <span class="gh-feed-repo">${this._escapeHtml(repoShort)}</span>
        <span class="gh-feed-time">${timeStr}</span>
      </div>
      <div class="gh-feed-item-body">${this._escapeHtml(titleText)}</div>
      ${entry.actor ? `<div class="gh-feed-actor">by ${this._escapeHtml(entry.actor)}</div>` : ''}
      ${entry.branch ? `<div class="gh-feed-branch">→ ${this._escapeHtml(entry.branch)}</div>` : ''}
    `;

    // Click to open on GitHub
    if (entry.url) {
      el.style.cursor = 'pointer';
      el.addEventListener('click', () => {
        if (window.overlayAPI && window.overlayAPI.openExternal) {
          window.overlayAPI.openExternal(entry.url);
        }
      });
    }

    // Insert at top (newest first)
    if (this._contentEl.firstChild) {
      this._contentEl.insertBefore(el, this._contentEl.firstChild);
    } else {
      this._contentEl.appendChild(el);
    }

    // Remove animation class after it completes
    if (animate) {
      setTimeout(() => el.classList.remove('gh-feed-item-enter'), 400);
    }

    // Enforce FIFO limit in DOM
    while (this._contentEl.children.length > GH_FEED_CONFIG.maxItems) {
      this._contentEl.removeChild(this._contentEl.lastChild);
    }
  }

  _formatTime(ts) {
    if (!ts) return '';
    try {
      const date = new Date(ts);
      const now = new Date();
      const diffMs = now - date;
      const diffMin = Math.floor(diffMs / 60000);

      if (diffMin < 1) return 'now';
      if (diffMin < 60) return `${diffMin}m`;
      const diffH = Math.floor(diffMin / 60);
      if (diffH < 24) return `${diffH}h`;
      const diffD = Math.floor(diffH / 24);
      if (diffD < 7) return `${diffD}d`;
      return date.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' });
    } catch {
      return '';
    }
  }

  _escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  async _fetchFeed() {
    const api = window.overlayAPI;
    if (!api || !api.getGitHubFeed) {
      console.warn('[GitHubFeed] overlayAPI.getGitHubFeed not available');
      return;
    }

    try {
      const data = await api.getGitHubFeed();
      if (data && data.events) {
        this.setItems(data.events);
      }
      if (data && typeof data.unreadCount === 'number') {
        this.setUnreadCount(data.unreadCount);
      }
      console.log(`[GitHubFeed] Fetched ${data?.events?.length || 0} events`);
    } catch (err) {
      console.warn('[GitHubFeed] Fetch failed:', err.message || err);
    }
  }

  _startAutoRefresh() {
    if (this._refreshTimer) clearInterval(this._refreshTimer);
    this._refreshTimer = setInterval(() => {
      if (!this._isPaused) {
        this._fetchFeed();
      }
    }, GH_FEED_CONFIG.refreshInterval);
  }

  // ─── CSS Injection ────────────────────────────────────────────

  _injectStyles() {
    if (document.getElementById('gh-feed-styles')) return;
    const style = document.createElement('style');
    style.id = 'gh-feed-styles';
    style.textContent = `
      .gh-feed-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        font-size: 11px;
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
      }

      .gh-feed-title {
        color: rgba(255,255,255,0.5);
        flex: 1;
        text-transform: uppercase;
        letter-spacing: 1px;
      }

      .gh-feed-badge {
        background: #ff4757;
        color: #fff;
        font-size: 10px;
        font-weight: bold;
        padding: 1px 6px;
        border-radius: 8px;
        min-width: 16px;
        text-align: center;
      }

      .gh-feed-refresh {
        background: none;
        border: 1px solid rgba(255,255,255,0.15);
        color: rgba(255,255,255,0.4);
        cursor: pointer;
        font-size: 13px;
        padding: 2px 6px;
        border-radius: 4px;
        transition: all 0.2s;
      }
      .gh-feed-refresh:hover {
        background: rgba(255,255,255,0.08);
        color: rgba(255,255,255,0.8);
        border-color: rgba(255,255,255,0.3);
      }

      .gh-feed-content {
        overflow-y: auto;
        max-height: calc(100% - 36px);
        scrollbar-width: thin;
        scrollbar-color: rgba(255,255,255,0.1) transparent;
      }
      .gh-feed-content::-webkit-scrollbar {
        width: 4px;
      }
      .gh-feed-content::-webkit-scrollbar-thumb {
        background: rgba(255,255,255,0.15);
        border-radius: 2px;
      }

      .gh-feed-empty {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 40px 20px;
        color: rgba(255,255,255,0.3);
      }

      .gh-feed-item {
        padding: 8px 12px;
        border-bottom: 1px solid rgba(255,255,255,0.04);
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
        font-size: 11px;
        transition: background 0.15s;
      }
      .gh-feed-item:hover {
        background: rgba(255,255,255,0.04);
      }

      .gh-feed-item-enter {
        animation: ghFeedSlideIn 0.35s ease-out;
      }

      @keyframes ghFeedSlideIn {
        from {
          opacity: 0;
          transform: translateY(-8px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      .gh-feed-item-header {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-bottom: 3px;
      }

      .gh-feed-icon {
        font-size: 12px;
        flex-shrink: 0;
      }

      .gh-feed-label {
        font-size: 9px;
        font-weight: bold;
        letter-spacing: 0.5px;
        opacity: 0.9;
        flex-shrink: 0;
      }

      .gh-feed-repo {
        color: rgba(86, 156, 214, 0.8);
        font-size: 10px;
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .gh-feed-time {
        color: rgba(255,255,255,0.25);
        font-size: 10px;
        flex-shrink: 0;
      }

      .gh-feed-item-body {
        color: rgba(255,255,255,0.75);
        line-height: 1.4;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        max-width: 300px;
      }

      .gh-feed-actor {
        color: rgba(255,255,255,0.3);
        font-size: 10px;
        margin-top: 2px;
      }

      .gh-feed-branch {
        color: rgba(78, 201, 176, 0.6);
        font-size: 10px;
        margin-top: 1px;
      }
    `;
    document.head.appendChild(style);
  }
}

// Expose globally for renderer.js
window.GitHubFeedPanel = GitHubFeedPanel;

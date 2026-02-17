/**
 * Bantz Overlay — Unified Inbox Panel
 *
 * Full-height left panel displaying a unified notification stream
 * combining Gmail, Calendar, System, and Assistant notifications.
 * Each item is color-coded by source and supports click-to-expand.
 *
 * Data sources:
 *   - Gmail: unread messages (via IngestStore/SyncScheduler)
 *   - Calendar: today's events + upcoming (via IPC briefing)
 *   - System: battery, disk, updates notifications
 *   - Assistant: reminders, proactive suggestions
 *
 * @module inbox-panel
 */

'use strict';

// ─── Configuration ──────────────────────────────────────────────
const INBOX_CONFIG = {
  panelWidth: 300,
  panelHeight: null, // null = fill available height (flex: 1)
  maxItems: 100,
  refreshInterval: 30 * 1000, // 30s auto-refresh
  sources: {
    mail:      { icon: '✉', color: '#4a9eff', label: 'MAIL' },
    calendar:  { icon: '📅', color: '#44ff44', label: 'TAKVİM' },
    system:    { icon: '⚙', color: '#ffaa00', label: 'SİSTEM' },
    assistant: { icon: '◉', color: '#00e5ff', label: 'ASISTAN' },
  },
};

/**
 * InboxPanel — unified notification stream for left column.
 */
class InboxPanel {
  /**
   * @param {HTMLElement} parent - The region container to mount into
   */
  constructor(parent) {
    this._parent = parent;
    this._items = [];
    this._mounted = false;
    this._contentEl = null;
    this._badgeEl = null;
    this._unreadCount = 0;
    this._refreshTimer = null;
    this._expanded = new Set(); // IDs of expanded items

    this._panel = new window.TerminalPanel({
      id: 'inbox',
      title: 'BİLDİRİMLER',
      slot: 'left',
      width: INBOX_CONFIG.panelWidth,
      height: 600, // will be overridden by flex
      maxLines: INBOX_CONFIG.maxItems,
      autoScroll: false,
    });

    this._injectStyles();
  }

  // ─── Public API ─────────────────────────────────────────────

  /**
   * Mount the panel into the DOM.
   */
  mount() {
    if (this._mounted) return;
    this._panel.mount(this._parent);
    this._contentEl = this._panel.contentElement;
    this._mounted = true;

    // Make panel fill available height
    this._panel.element.style.flex = '1';
    this._panel.element.style.height = 'auto';
    this._panel.element.style.minHeight = '200px';

    // Add unread badge to header
    this._addBadge();

    // Start auto-refresh
    this._startRefresh();
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
   * Get the root element.
   * @returns {HTMLElement}
   */
  get element() {
    return this._panel.element;
  }

  /**
   * Add a notification item to the inbox.
   * @param {object} item
   * @param {string} item.id       - Unique item ID
   * @param {string} item.source   - Source type: 'mail'|'calendar'|'system'|'assistant'
   * @param {string} item.title    - Item title/subject
   * @param {string} [item.body]   - Preview text or details
   * @param {string} [item.time]   - Timestamp string
   * @param {boolean} [item.unread] - Whether item is unread
   * @param {string} [item.url]    - URL to open on click
   */
  addItem(item) {
    // Deduplicate by ID
    if (this._items.some(i => i.id === item.id)) return;

    this._items.unshift(item); // newest first

    // Trim to max
    while (this._items.length > INBOX_CONFIG.maxItems) {
      this._items.pop();
    }

    if (item.unread) this._unreadCount++;
    this._updateBadge();
    this._renderItem(item, true); // prepend
  }

  /**
   * Add multiple items at once.
   * @param {object[]} items
   */
  addItems(items) {
    for (const item of items) {
      this.addItem(item);
    }
  }

  /**
   * Set calendar events (replaces existing calendar items).
   * @param {object[]} events - Array of calendar event objects
   */
  setCalendarEvents(events) {
    // Remove old calendar items
    this._items = this._items.filter(i => i.source !== 'calendar');
    this._removeItemsBySource('calendar');

    const now = new Date();
    for (const ev of events) {
      const startTime = ev.start ? new Date(ev.start) : null;
      const isPast = startTime && startTime < now;

      this.addItem({
        id: `cal-${ev.id || ev.summary}`,
        source: 'calendar',
        title: ev.summary || 'Etkinlik',
        body: ev.location || '',
        time: startTime ? startTime.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }) : '',
        unread: !isPast,
      });
    }
  }

  /**
   * Set Gmail messages (replaces existing mail items).
   * @param {object[]} messages
   */
  setMailMessages(messages) {
    this._items = this._items.filter(i => i.source !== 'mail');
    this._removeItemsBySource('mail');

    for (const msg of messages) {
      this.addItem({
        id: `mail-${msg.id || msg.subject}`,
        source: 'mail',
        title: msg.subject || '(Konu yok)',
        body: msg.snippet || msg.from || '',
        time: msg.date || '',
        unread: !!msg.unread,
      });
    }
  }

  /**
   * Add a system notification.
   * @param {string} title
   * @param {string} [body]
   */
  addSystemNotification(title, body = '') {
    this.addItem({
      id: `sys-${Date.now()}`,
      source: 'system',
      title,
      body,
      time: new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }),
      unread: true,
    });
  }

  /**
   * Add an assistant message/reminder.
   * @param {string} title
   * @param {string} [body]
   */
  addAssistantMessage(title, body = '') {
    this.addItem({
      id: `asst-${Date.now()}`,
      source: 'assistant',
      title,
      body,
      time: new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }),
      unread: true,
    });
  }

  /**
   * Clear all items.
   */
  clear() {
    this._items = [];
    this._unreadCount = 0;
    this._contentEl.innerHTML = '';
    this._updateBadge();
  }

  /**
   * Cleanup timers.
   */
  destroy() {
    if (this._refreshTimer) clearInterval(this._refreshTimer);
  }

  // ─── Internal ───────────────────────────────────────────────

  /**
   * Render a single item into the content area.
   * @param {object} item
   * @param {boolean} [prepend=false]
   * @private
   */
  _renderItem(item, prepend = false) {
    const sourceConfig = INBOX_CONFIG.sources[item.source] || INBOX_CONFIG.sources.system;

    const el = document.createElement('div');
    el.className = `inbox-item ${item.unread ? 'inbox-unread' : ''}`;
    el.dataset.id = item.id;
    el.dataset.source = item.source;

    el.innerHTML = `
      <div class="inbox-item-header">
        <span class="inbox-source-badge" style="color: ${sourceConfig.color}; border-color: ${sourceConfig.color}40;">
          ${sourceConfig.icon} ${sourceConfig.label}
        </span>
        <span class="inbox-time">${item.time || ''}</span>
      </div>
      <div class="inbox-item-title">${this._escapeHtml(item.title)}</div>
      ${item.body ? `<div class="inbox-item-body">${this._escapeHtml(item.body)}</div>` : ''}
    `;

    // Click to toggle expand
    el.addEventListener('click', () => {
      if (this._expanded.has(item.id)) {
        this._expanded.delete(item.id);
        el.classList.remove('inbox-expanded');
      } else {
        this._expanded.add(item.id);
        el.classList.add('inbox-expanded');
      }

      // Mark as read
      if (item.unread) {
        item.unread = false;
        el.classList.remove('inbox-unread');
        this._unreadCount = Math.max(0, this._unreadCount - 1);
        this._updateBadge();
      }

      // Open URL if available
      if (item.url && window.overlayAPI) {
        window.overlayAPI.openExternal(item.url);
      }
    });

    if (prepend && this._contentEl.firstChild) {
      this._contentEl.insertBefore(el, this._contentEl.firstChild);
    } else {
      this._contentEl.appendChild(el);
    }
  }

  /**
   * Remove rendered items by source.
   * @param {string} source
   * @private
   */
  _removeItemsBySource(source) {
    if (!this._contentEl) return;
    const els = this._contentEl.querySelectorAll(`[data-source="${source}"]`);
    for (const el of els) el.remove();
  }

  /**
   * Add unread count badge to the panel header.
   * @private
   */
  _addBadge() {
    const header = this._panel.element.querySelector('.terminal-panel-header');
    if (!header) return;

    this._badgeEl = document.createElement('span');
    this._badgeEl.className = 'inbox-badge';
    this._badgeEl.style.cssText = `
      background: #ff4444;
      color: white;
      font-size: 9px;
      font-weight: bold;
      padding: 1px 5px;
      border-radius: 8px;
      min-width: 16px;
      text-align: center;
      display: none;
    `;
    header.appendChild(this._badgeEl);
  }

  /**
   * Update the badge count.
   * @private
   */
  _updateBadge() {
    if (!this._badgeEl) return;
    if (this._unreadCount > 0) {
      this._badgeEl.textContent = this._unreadCount > 99 ? '99+' : String(this._unreadCount);
      this._badgeEl.style.display = 'inline-block';
    } else {
      this._badgeEl.style.display = 'none';
    }
  }

  /**
   * Start auto-refresh timer.
   * @private
   */
  _startRefresh() {
    this._refreshTimer = setInterval(async () => {
      await this._fetchData();
    }, INBOX_CONFIG.refreshInterval);

    // Initial fetch
    setTimeout(() => this._fetchData(), 2000);
  }

  /**
   * Fetch inbox data from IPC.
   * @private
   */
  async _fetchData() {
    const api = window.overlayAPI;
    if (!api) return;

    try {
      // Try to get system metrics for system notifications
      if (api.getSystemMetrics) {
        const metrics = await api.getSystemMetrics();
        if (metrics) {
          // High CPU alert
          if (metrics.cpu > 90) {
            this.addSystemNotification(
              `CPU Yüksek: %${metrics.cpu.toFixed(0)}`,
              'Sistem yükü kritik seviyede'
            );
          }
          // High RAM alert
          if (metrics.ram > 90) {
            this.addSystemNotification(
              `RAM Yüksek: %${metrics.ram.toFixed(0)}`,
              'Bellek kullanımı kritik'
            );
          }
          // Low disk alert
          if (metrics.disk > 90) {
            this.addSystemNotification(
              `Disk Dolu: %${metrics.disk.toFixed(0)}`,
              'Disk alanı kritik seviyede az'
            );
          }
        }
      }
    } catch (e) {
      console.warn('[Inbox] Data fetch error:', e);
    }
  }

  /**
   * HTML escape for safe rendering.
   * @param {string} text
   * @returns {string}
   * @private
   */
  _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Inject inbox-specific CSS styles.
   * @private
   */
  _injectStyles() {
    if (document.getElementById('inbox-panel-styles')) return;

    const style = document.createElement('style');
    style.id = 'inbox-panel-styles';
    style.textContent = `
      .inbox-item {
        padding: 8px 10px;
        border-bottom: 1px solid rgba(0, 229, 255, 0.06);
        cursor: pointer;
        transition: background 0.15s;
      }

      .inbox-item:hover {
        background: rgba(0, 229, 255, 0.04);
      }

      .inbox-unread {
        border-left: 2px solid #00e5ff;
        padding-left: 8px;
      }

      .inbox-expanded .inbox-item-body {
        max-height: 200px;
        opacity: 1;
        margin-top: 4px;
      }

      .inbox-item-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 3px;
      }

      .inbox-source-badge {
        font-size: 9px;
        font-weight: bold;
        letter-spacing: 0.5px;
        padding: 1px 5px;
        border: 1px solid;
        border-radius: 3px;
        text-transform: uppercase;
      }

      .inbox-time {
        font-size: 10px;
        color: rgba(255, 255, 255, 0.35);
      }

      .inbox-item-title {
        font-size: 12px;
        color: rgba(0, 229, 255, 0.85);
        line-height: 1.4;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .inbox-unread .inbox-item-title {
        color: #ffffff;
        font-weight: bold;
      }

      .inbox-item-body {
        font-size: 11px;
        color: rgba(255, 255, 255, 0.4);
        line-height: 1.3;
        max-height: 0;
        opacity: 0;
        overflow: hidden;
        transition: max-height 0.2s ease, opacity 0.2s ease;
      }

      /* New item flash animation */
      @keyframes inbox-flash {
        0% { background: rgba(0, 229, 255, 0.15); }
        100% { background: transparent; }
      }

      .inbox-item:first-child {
        animation: inbox-flash 1s ease-out;
      }
    `;
    document.head.appendChild(style);
  }
}

// Export globally
window.InboxPanel = InboxPanel;

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { InboxPanel, INBOX_CONFIG };
}

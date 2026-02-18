/**
 * Bantz Overlay — Daily Tasks & Agenda Panel
 *
 * Terminal sub-panel showing today's calendar events and tasks.
 * Events are pulled from Google Calendar via IPC briefing data.
 *
 * @module daily-tasks
 */

// ─── Configuration ──────────────────────────────────────────────
const AGENDA_CONFIG = {
  panelWidth: 360,
  panelHeight: 420,
  refreshInterval: 5 * 60 * 1000, // 5 minutes
  emptyMessage: 'Bugün takvimde etkinlik yok, efendim.',
};

/**
 * DailyTasksPanel — calendar agenda & tasks terminal.
 */
class DailyTasksPanel {
  /**
   * @param {HTMLElement} parent - The HUD panel to mount into
   */
  constructor(parent) {
    this._parent = parent;
    this._events = [];
    this._tasks = [];
    this._mounted = false;
    this._contentEl = null;
    this._refreshTimer = null;

    // Use the TerminalPanel base component
    this._panel = new window.TerminalPanel({
      id: 'daily-tasks',
      title: '> GÜNLÜK AJANDA',
      slot: 'left',
      width: AGENDA_CONFIG.panelWidth,
      height: AGENDA_CONFIG.panelHeight,
    });
  }

  /** @returns {HTMLElement|null} The underlying DOM element */
  get element() { return this._panel ? this._panel.element : null; }

  // ─── Public API ───────────────────────────────────────────────

  /**
   * Mount the panel into the DOM.
   */
  mount() {
    this._panel.mount(this._parent);

    const panelEl = this._parent.querySelector('#terminal-daily-tasks');
    if (!panelEl) { console.error('[DailyTasks] Panel element not found'); return; }

    const content = panelEl.querySelector('.terminal-content, .terminal-panel-content');
    if (!content) return;

    this._contentEl = content;
    this._contentEl.style.cssText += `
      padding: 6px 8px;
      line-height: 1.7;
    `;

    this._render();
    this._mounted = true;

    // Auto-refresh timer
    this._refreshTimer = setInterval(() => this._render(), AGENDA_CONFIG.refreshInterval);

    console.log('[DailyTasks] Mounted');
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
   * Add a calendar event from a briefing_card message.
   * @param {{ title: string, start?: string, end?: string, all_day?: boolean, is_imminent?: boolean, id?: string }} event
   */
  addEvent(event) {
    const existing = this._events.find(e => e.id === event.id);
    if (existing) {
      Object.assign(existing, event);
    } else {
      this._events.push({
        id: event.id || `evt-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
        title: event.title || 'Untitled',
        start: event.start ? new Date(event.start) : null,
        end: event.end ? new Date(event.end) : null,
        allDay: event.all_day || false,
        imminent: event.is_imminent || false,
      });
    }
    // Sort by time
    this._events.sort((a, b) => {
      if (a.allDay && !b.allDay) return -1;
      if (!a.allDay && b.allDay) return 1;
      return (a.start?.getTime() || 0) - (b.start?.getTime() || 0);
    });
    this._render();
  }

  /**
   * Add a task item.
   * @param {{ title: string, completed?: boolean, id?: string }} task
   */
  addTask(task) {
    const existing = this._tasks.find(t => t.id === task.id);
    if (existing) {
      Object.assign(existing, task);
    } else {
      this._tasks.push({
        id: task.id || `task-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
        title: task.title || 'Untitled',
        completed: task.completed || false,
      });
    }
    this._render();
  }

  /**
   * Replace all events at once (e.g., full refresh from daemon).
   * @param {Array} events
   */
  setEvents(events) {
    this._events = events.map(e => ({
      id: e.id || `evt-${Math.random().toString(36).slice(2, 7)}`,
      title: e.title || 'Untitled',
      start: e.start ? new Date(e.start) : null,
      end: e.end ? new Date(e.end) : null,
      allDay: e.all_day || false,
      imminent: e.is_imminent || false,
    }));
    this._events.sort((a, b) => {
      if (a.allDay && !b.allDay) return -1;
      if (!a.allDay && b.allDay) return 1;
      return (a.start?.getTime() || 0) - (b.start?.getTime() || 0);
    });
    this._render();
  }

  /**
   * Clear all events and tasks.
   */
  clear() {
    this._events = [];
    this._tasks = [];
    this._render();
  }

  /**
   * Clean up.
   */
  dispose() {
    if (this._refreshTimer) clearInterval(this._refreshTimer);
    this._panel.unmount();
  }

  // ─── Internal ─────────────────────────────────────────────────

  /**
   * Render the full agenda view.
   * @private
   */
  _render() {
    if (!this._contentEl) return;

    this._contentEl.innerHTML = '';
    const now = new Date();

    if (this._events.length === 0 && this._tasks.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'agenda-empty';
      empty.textContent = AGENDA_CONFIG.emptyMessage;
      this._contentEl.appendChild(empty);
      return;
    }

    // Render calendar events
    if (this._events.length > 0) {
      this._events.forEach(event => {
        const line = document.createElement('div');
        line.className = 'agenda-event terminal-line';
        line.setAttribute('data-event-id', event.id);

        const isPast = event.end && event.end < now;
        const isCurrent = event.start && event.end && event.start <= now && event.end >= now;
        const isNext = !isPast && !isCurrent && event.start && event.start > now;

        if (isPast) {
          line.classList.add('agenda-past');
        } else if (isCurrent) {
          line.classList.add('agenda-current');
        } else if (event.imminent) {
          line.classList.add('agenda-imminent');
        }

        // Format time
        let timeStr;
        if (event.allDay) {
          timeStr = '[TÜM GÜN]';
        } else if (event.start && event.end) {
          timeStr = `[${this._formatTime(event.start)}-${this._formatTime(event.end)}]`;
        } else if (event.start) {
          timeStr = `[${this._formatTime(event.start)}]`;
        } else {
          timeStr = '[--:--]';
        }

        // Prefix
        const prefix = isCurrent ? '>>> ' : (isNext && !this._events.some(e => {
          const ec = e.start && e.end && e.start <= now && e.end >= now;
          return ec;
        }) ? '>>> ' : '    ');

        const timeSpan = document.createElement('span');
        timeSpan.className = 'agenda-time';
        timeSpan.textContent = `${prefix}${timeStr} `;

        const titleSpan = document.createElement('span');
        titleSpan.className = 'agenda-title';
        titleSpan.textContent = event.title;

        // Imminent badge
        if (event.imminent && !isCurrent && !isPast) {
          const badge = document.createElement('span');
          badge.className = 'agenda-imminent-badge';
          badge.textContent = ' ⏰';
          titleSpan.appendChild(badge);
        }

        line.appendChild(timeSpan);
        line.appendChild(titleSpan);
        this._contentEl.appendChild(line);
      });
    }

    // Render tasks section
    if (this._tasks.length > 0) {
      const separator = document.createElement('div');
      separator.className = 'agenda-separator';
      separator.textContent = '─── GÖREVLER ───';
      this._contentEl.appendChild(separator);

      this._tasks.forEach(task => {
        const line = document.createElement('div');
        line.className = 'agenda-task terminal-line';
        if (task.completed) line.classList.add('agenda-completed');

        const checkbox = task.completed ? '[x] ' : '[ ] ';
        line.textContent = `${checkbox}${task.title}`;
        this._contentEl.appendChild(line);
      });
    }
  }

  /**
   * Format a Date to HH:MM.
   * @private
   */
  _formatTime(date) {
    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  }
}

// ─── CSS Injection ──────────────────────────────────────────────
(function injectAgendaStyles() {
  if (document.getElementById('agenda-styles')) return;

  const style = document.createElement('style');
  style.id = 'agenda-styles';
  style.textContent = `
    .agenda-empty {
      color: rgba(0, 229, 255, 0.4);
      font-style: italic;
      text-align: center;
      padding: 40px 10px;
      font-size: 0.85em;
    }

    .agenda-event {
      padding: 2px 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .agenda-time {
      color: rgba(0, 229, 255, 0.5);
      font-size: 0.85em;
    }

    .agenda-title {
      color: rgba(0, 229, 255, 0.85);
    }

    /* Current event */
    .agenda-current {
      background: rgba(0, 229, 255, 0.08);
      border-left: 2px solid #00e5ff;
      padding-left: 4px;
    }

    .agenda-current .agenda-time {
      color: #00e5ff;
      font-weight: bold;
    }

    .agenda-current .agenda-title {
      color: #00e5ff;
    }

    /* Imminent event — starts within 30 min */
    .agenda-imminent {
      background: rgba(255, 200, 0, 0.07);
      border-left: 2px solid rgba(255, 200, 0, 0.7);
      padding-left: 4px;
    }

    .agenda-imminent .agenda-time {
      color: rgba(255, 200, 0, 0.85);
      font-weight: bold;
    }

    .agenda-imminent .agenda-title {
      color: rgba(255, 200, 0, 0.95);
    }

    .agenda-imminent-badge {
      font-size: 0.9em;
    }

    /* Past event */
    .agenda-past {
      opacity: 0.5;
    }

    .agenda-past .agenda-title {
      text-decoration: line-through;
    }

    /* Tasks separator */
    .agenda-separator {
      color: rgba(0, 229, 255, 0.3);
      font-size: 0.75em;
      text-align: center;
      padding: 6px 0 3px;
    }

    /* Task items */
    .agenda-task {
      padding: 2px 0;
      color: rgba(0, 229, 255, 0.75);
    }

    .agenda-completed {
      opacity: 0.5;
      text-decoration: line-through;
    }
  `;
  document.head.appendChild(style);
})();

// Expose globally
window.DailyTasksPanel = DailyTasksPanel;

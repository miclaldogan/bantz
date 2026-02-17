/**
 * Bantz Overlay — Weather & System Status Panel
 *
 * Compact terminal sub-panel showing weather conditions and
 * basic system health metrics (CPU, RAM, Disk, Uptime).
 *
 * @module system-status
 */

// ─── Configuration ──────────────────────────────────────────────
const SYSTEM_CONFIG = {
  panelWidth: 250,
  panelHeight: 200,
  systemRefreshMs: 10000,    // 10s for system metrics
  barWidth: 10,              // characters in progress bar
  thresholds: {
    green: 60,
    yellow: 85,
    // > 85 = red
  },
  weatherFallback: 'Hava durumu alınamadı',
};

// ASCII weather condition icons
const WEATHER_ICONS = {
  clear: '☀',
  sunny: '☀',
  cloudy: '☁',
  clouds: '☁',
  overcast: '☁',
  rain: '🌧',
  rainy: '🌧',
  drizzle: '🌧',
  snow: '❄',
  snowy: '❄',
  storm: '⛈',
  thunder: '⛈',
  fog: '🌫',
  mist: '🌫',
  wind: '💨',
  windy: '💨',
  default: '🌡',
};

/**
 * SystemStatusPanel — weather + system health terminal.
 */
class SystemStatusPanel {
  /**
   * @param {HTMLElement} parent - The HUD panel to mount into
   */
  constructor(parent) {
    this._parent = parent;
    this._weather = null;
    this._systemMetrics = null;
    this._contentEl = null;
    this._refreshTimer = null;
    this._mounted = false;

    this._panel = new window.TerminalPanel({
      id: 'system-status',
      title: '> SİSTEM DURUMU',
      slot: 'bottom-left',
      width: SYSTEM_CONFIG.panelWidth,
      height: SYSTEM_CONFIG.panelHeight,
    });
  }

  // ─── Public API ───────────────────────────────────────────────

  /**
   * Mount the panel.
   */
  mount() {
    this._panel.mount(this._parent);

    const panelEl = this._parent.querySelector('#terminal-system-status');
    if (!panelEl) return;

    const content = panelEl.querySelector('.terminal-content');
    if (!content) return;

    this._contentEl = content;
    this._contentEl.style.cssText += `
      padding: 6px 8px;
      line-height: 1.6;
      font-size: 0.85em;
    `;

    this._render();
    this._mounted = true;

    // System metrics refresh
    this._refreshTimer = setInterval(() => {
      this._requestSystemMetrics();
    }, SYSTEM_CONFIG.systemRefreshMs);

    console.log('[SystemStatus] Mounted');
  }

  show() { this._panel.show(); }
  hide() { this._panel.hide(); }

  /**
   * Update weather data from briefing_card.
   * @param {{ temperature?: number, condition?: string, humidity?: number, wind_speed?: number, unit?: string }} data
   */
  setWeather(data) {
    this._weather = data;
    this._render();
  }

  /**
   * Update system metrics.
   * @param {{ cpu?: number, ram?: number, disk?: number, uptime_seconds?: number }} metrics
   */
  setSystemMetrics(metrics) {
    this._systemMetrics = metrics;
    this._render();
  }

  dispose() {
    if (this._refreshTimer) clearInterval(this._refreshTimer);
    this._panel.unmount();
  }

  // ─── Internal ─────────────────────────────────────────────────

  /**
   * Request system metrics via IPC.
   * @private
   */
  _requestSystemMetrics() {
    if (window.overlayAPI && window.overlayAPI.sendDaemonEvent) {
      window.overlayAPI.sendDaemonEvent({ type: 'request_system_metrics' });
    }
  }

  /**
   * Render the full panel content.
   * @private
   */
  _render() {
    if (!this._contentEl) return;

    this._contentEl.innerHTML = '';

    // Weather section
    this._renderWeather();

    // Separator
    const sep = document.createElement('div');
    sep.className = 'system-separator';
    sep.textContent = '────────────────';
    this._contentEl.appendChild(sep);

    // System section
    this._renderSystem();
  }

  /**
   * Render weather section.
   * @private
   */
  _renderWeather() {
    const line = document.createElement('div');
    line.className = 'system-weather terminal-line';

    if (!this._weather) {
      line.textContent = SYSTEM_CONFIG.weatherFallback;
      line.style.color = 'rgba(0, 229, 255, 0.4)';
      line.style.fontStyle = 'italic';
    } else {
      const w = this._weather;
      const icon = this._getWeatherIcon(w.condition);
      const temp = w.temperature != null ? `${w.temperature}°C` : '--°C';
      const humidity = w.humidity != null ? `%${w.humidity} nem` : '';
      const wind = w.wind_speed != null ? `${w.wind_speed} km/s rüzgar` : '';

      const parts = [`${icon} ${temp}`];
      if (humidity) parts.push(humidity);
      if (wind) parts.push(wind);

      line.textContent = parts.join(' | ');
    }

    this._contentEl.appendChild(line);
  }

  /**
   * Render system metrics section.
   * @private
   */
  _renderSystem() {
    const m = this._systemMetrics || {};

    // CPU
    this._renderBar('CPU', m.cpu);
    // RAM
    this._renderBar('RAM', m.ram);
    // Disk
    this._renderBar('SSD', m.disk);
    // Uptime
    this._renderUptime(m.uptime_seconds);
  }

  /**
   * Render a progress bar line.
   * @private
   */
  _renderBar(label, value) {
    const line = document.createElement('div');
    line.className = 'system-bar terminal-line';

    const pct = value != null ? Math.round(value) : 0;
    const filled = Math.round((pct / 100) * SYSTEM_CONFIG.barWidth);
    const empty = SYSTEM_CONFIG.barWidth - filled;
    const bar = '█'.repeat(filled) + '░'.repeat(empty);

    const labelPad = label.padEnd(3);

    const labelSpan = document.createElement('span');
    labelSpan.className = 'system-label';
    labelSpan.textContent = `${labelPad} `;

    const barSpan = document.createElement('span');
    barSpan.className = 'system-bar-chars';
    barSpan.textContent = `[${bar}]`;
    barSpan.style.color = this._getBarColor(pct);

    const pctSpan = document.createElement('span');
    pctSpan.className = 'system-pct';
    pctSpan.textContent = ` ${String(pct).padStart(3)}%`;
    pctSpan.style.color = this._getBarColor(pct);

    line.appendChild(labelSpan);
    line.appendChild(barSpan);
    line.appendChild(pctSpan);
    this._contentEl.appendChild(line);
  }

  /**
   * Render uptime line.
   * @private
   */
  _renderUptime(seconds) {
    const line = document.createElement('div');
    line.className = 'system-uptime terminal-line';

    if (seconds == null) {
      line.textContent = 'UP  --';
    } else {
      const days = Math.floor(seconds / 86400);
      const hours = Math.floor((seconds % 86400) / 3600);
      const mins = Math.floor((seconds % 3600) / 60);

      const parts = [];
      if (days > 0) parts.push(`${days}g`);
      parts.push(`${hours}s`);
      parts.push(`${mins}dk`);
      line.textContent = `UP  ${parts.join(' ')}`;
    }

    this._contentEl.appendChild(line);
  }

  /**
   * Get color based on usage percentage.
   * @private
   */
  _getBarColor(pct) {
    if (pct < SYSTEM_CONFIG.thresholds.green) return '#4caf50';
    if (pct < SYSTEM_CONFIG.thresholds.yellow) return '#ffc107';
    return '#f44336';
  }

  /**
   * Get weather icon for condition string.
   * @private
   */
  _getWeatherIcon(condition) {
    if (!condition) return WEATHER_ICONS.default;
    const key = condition.toLowerCase();
    for (const [k, icon] of Object.entries(WEATHER_ICONS)) {
      if (key.includes(k)) return icon;
    }
    return WEATHER_ICONS.default;
  }
}

// ─── CSS Injection ──────────────────────────────────────────────
(function injectSystemStyles() {
  if (document.getElementById('system-status-styles')) return;

  const style = document.createElement('style');
  style.id = 'system-status-styles';
  style.textContent = `
    .system-weather {
      padding: 2px 0;
      color: rgba(0, 229, 255, 0.85);
    }

    .system-separator {
      color: rgba(0, 229, 255, 0.15);
      font-size: 0.8em;
      padding: 2px 0;
    }

    .system-label {
      color: rgba(0, 229, 255, 0.5);
    }

    .system-bar-chars {
      font-family: 'JetBrains Mono', 'Fira Code', monospace;
    }

    .system-pct {
      font-size: 0.9em;
    }

    .system-uptime {
      color: rgba(0, 229, 255, 0.6);
      padding-top: 2px;
    }
  `;
  document.head.appendChild(style);
})();

// Expose globally
window.SystemStatusPanel = SystemStatusPanel;

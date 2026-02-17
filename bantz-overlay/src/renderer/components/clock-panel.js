/**
 * Bantz Overlay — Clock & Date Panel
 *
 * A compact terminal panel showing the current time and date
 * in terminal aesthetic. Updates every second.
 *
 * @module clock-panel
 */

'use strict';

const CLOCK_CONFIG = {
  panelWidth: 220,
  panelHeight: 95,
  refreshMs: 1000,
};

// Turkish day/month names
const DAYS_TR = ['Pazar', 'Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi'];
const MONTHS_TR = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
                   'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

class ClockPanel {
  constructor(parent) {
    this._parent = parent;
    this._contentEl = null;
    this._timer = null;
    this._mounted = false;

    this._panel = new window.TerminalPanel({
      id: 'clock',
      title: '> SAAT',
      slot: 'bottom-right',
      width: CLOCK_CONFIG.panelWidth,
      height: CLOCK_CONFIG.panelHeight,
    });
  }

  get element() { return this._panel ? this._panel.element : null; }

  mount() {
    this._panel.mount(this._parent);

    const panelEl = this._parent.querySelector('#terminal-clock');
    if (!panelEl) { console.error('[Clock] Panel element not found'); return; }

    const content = panelEl.querySelector('.terminal-content, .terminal-panel-content');
    if (!content) return;

    this._contentEl = content;
    this._contentEl.style.cssText += `
      padding: 6px 10px;
      line-height: 1.5;
      font-size: 0.85em;
      text-align: center;
    `;

    this._render();
    this._timer = setInterval(() => this._render(), CLOCK_CONFIG.refreshMs);
    this._mounted = true;
    console.log('[Clock] Mounted');
  }

  show() { this._panel.show(); }
  hide() { this._panel.hide(); }

  dispose() {
    if (this._timer) clearInterval(this._timer);
    this._panel.unmount();
  }

  _render() {
    if (!this._contentEl) return;
    const now = new Date();

    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const s = String(now.getSeconds()).padStart(2, '0');

    const dayName = DAYS_TR[now.getDay()];
    const day = now.getDate();
    const month = MONTHS_TR[now.getMonth()];
    const year = now.getFullYear();

    this._contentEl.innerHTML = `
      <div style="font-size: 1.8em; color: var(--color-accent); letter-spacing: 3px; font-weight: bold; text-shadow: 0 0 8px rgba(0,229,255,0.4);">
        ${h}<span style="animation: blink 1s step-start infinite;">:</span>${m}<span style="font-size: 0.6em; opacity: 0.6;">${s}</span>
      </div>
      <div style="font-size: 0.85em; color: rgba(0, 229, 255, 0.6); margin-top: 2px;">
        ${dayName}, ${day} ${month} ${year}
      </div>
    `;
  }
}

window.ClockPanel = ClockPanel;

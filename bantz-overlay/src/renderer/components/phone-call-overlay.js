/**
 * Bantz Overlay — Phone Call Overlay Component
 *
 * Full-screen overlay that transforms the HUD when an incoming
 * call arrives. Shows caller info, accept/reject buttons, and
 * in-call status (timer, mute, speaker controls).
 *
 * States:
 *   - hidden    → no call
 *   - incoming  → ringing animation, caller info, accept/reject
 *   - active    → call timer, mute/speaker/hangup controls
 *   - ended     → brief "Arama sonlandı" then hidden
 *
 * IPC messages expected from daemon:
 *   { type: "event", event: "phone:incoming", data: { caller_name, caller_number, caller_photo? } }
 *   { type: "event", event: "phone:ended", data: { duration_seconds } }
 *
 * Usage:
 *   const phoneOverlay = new PhoneCallOverlay();
 *   phoneOverlay.mount(document.body);
 *   phoneOverlay.showIncoming({ caller_name: 'Ali', caller_number: '+90 555 123 4567' });
 *
 * @module phone-call-overlay
 */

'use strict';

class PhoneCallOverlay {
  constructor() {
    this._state = 'hidden'; // hidden | incoming | active | ended
    this._el = null;
    this._callStart = null;
    this._timerInterval = null;
    this._ringPulseInterval = null;
    this._callerInfo = null;
  }

  /**
   * Mount the overlay to a parent element.
   * @param {HTMLElement} parent
   */
  mount(parent) {
    this._el = document.createElement('div');
    this._el.className = 'phone-call-overlay';
    this._el.style.cssText = `
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      z-index: 9999;
      display: none;
      align-items: center;
      justify-content: center;
      flex-direction: column;
      background: radial-gradient(
        ellipse at center,
        rgba(0, 25, 40, 0.95) 0%,
        rgba(0, 10, 20, 0.98) 70%,
        rgba(0, 0, 0, 0.99) 100%
      );
      backdrop-filter: blur(20px);
      pointer-events: auto;
      font-family: 'JetBrains Mono', 'Fira Code', monospace;
      transition: opacity 0.4s ease;
      opacity: 0;
    `;

    this._el.innerHTML = `
      <!-- Incoming Call View -->
      <div class="phone-incoming" style="
        display: none;
        flex-direction: column;
        align-items: center;
        gap: 24px;
      ">
        <div class="phone-ring-indicator" style="
          width: 120px; height: 120px;
          border-radius: 50%;
          border: 2px solid rgba(0, 255, 200, 0.3);
          display: flex;
          align-items: center;
          justify-content: center;
          position: relative;
        ">
          <div class="phone-ring-pulse" style="
            position: absolute;
            width: 100%; height: 100%;
            border-radius: 50%;
            border: 1px solid rgba(0, 255, 200, 0.2);
            animation: phone-ring-pulse 1.5s ease-out infinite;
          "></div>
          <div class="phone-ring-pulse" style="
            position: absolute;
            width: 100%; height: 100%;
            border-radius: 50%;
            border: 1px solid rgba(0, 255, 200, 0.15);
            animation: phone-ring-pulse 1.5s ease-out 0.5s infinite;
          "></div>
          <div class="phone-avatar" style="
            width: 80px; height: 80px;
            border-radius: 50%;
            background: linear-gradient(135deg, #00ffc8 0%, #0088ff 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 36px;
            color: #001020;
            font-weight: 700;
            overflow: hidden;
          ">
            <span class="phone-avatar-text">?</span>
          </div>
        </div>

        <div style="text-align: center;">
          <div class="phone-label" style="
            color: rgba(0, 255, 200, 0.6);
            font-size: 11px;
            letter-spacing: 3px;
            text-transform: uppercase;
            margin-bottom: 8px;
          ">GELEN ARAMA</div>
          <div class="phone-caller-name" style="
            color: #e0f0ff;
            font-size: 28px;
            font-weight: 600;
            margin-bottom: 4px;
          ">Bilinmeyen</div>
          <div class="phone-caller-number" style="
            color: rgba(200, 220, 240, 0.5);
            font-size: 14px;
          "></div>
        </div>

        <div style="
          display: flex;
          gap: 48px;
          margin-top: 32px;
        ">
          <button class="phone-btn phone-reject" style="
            width: 64px; height: 64px;
            border-radius: 50%;
            border: none;
            background: linear-gradient(135deg, #ff3333 0%, #cc0000 100%);
            color: white;
            font-size: 24px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 20px rgba(255, 0, 0, 0.3);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
            pointer-events: auto;
          " title="Reddet">✕</button>
          <button class="phone-btn phone-accept" style="
            width: 64px; height: 64px;
            border-radius: 50%;
            border: none;
            background: linear-gradient(135deg, #00cc66 0%, #009944 100%);
            color: white;
            font-size: 24px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 20px rgba(0, 200, 100, 0.3);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
            pointer-events: auto;
          " title="Kabul et">📞</button>
        </div>
      </div>

      <!-- Active Call View -->
      <div class="phone-active" style="
        display: none;
        flex-direction: column;
        align-items: center;
        gap: 20px;
      ">
        <div class="phone-active-avatar" style="
          width: 80px; height: 80px;
          border-radius: 50%;
          background: linear-gradient(135deg, #00ffc8 0%, #0088ff 100%);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 32px;
          color: #001020;
          font-weight: 700;
          overflow: hidden;
        ">
          <span class="phone-active-avatar-text">?</span>
        </div>

        <div style="text-align: center;">
          <div class="phone-active-name" style="
            color: #e0f0ff;
            font-size: 22px;
            font-weight: 600;
            margin-bottom: 4px;
          ">Arama</div>
          <div class="phone-active-timer" style="
            color: rgba(0, 255, 200, 0.8);
            font-size: 16px;
            font-variant-numeric: tabular-nums;
          ">00:00</div>
        </div>

        <div style="
          display: flex;
          gap: 32px;
          margin-top: 24px;
        ">
          <button class="phone-btn phone-mute" style="
            width: 52px; height: 52px;
            border-radius: 50%;
            border: 1px solid rgba(200, 220, 240, 0.2);
            background: rgba(200, 220, 240, 0.08);
            color: #c8dcf0;
            font-size: 18px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.15s ease;
            pointer-events: auto;
          " title="Sessiz">🔇</button>
          <button class="phone-btn phone-hangup" style="
            width: 64px; height: 64px;
            border-radius: 50%;
            border: none;
            background: linear-gradient(135deg, #ff3333 0%, #cc0000 100%);
            color: white;
            font-size: 22px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 20px rgba(255, 0, 0, 0.3);
            transition: transform 0.15s ease;
            pointer-events: auto;
          " title="Kapat">📵</button>
          <button class="phone-btn phone-speaker" style="
            width: 52px; height: 52px;
            border-radius: 50%;
            border: 1px solid rgba(200, 220, 240, 0.2);
            background: rgba(200, 220, 240, 0.08);
            color: #c8dcf0;
            font-size: 18px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.15s ease;
            pointer-events: auto;
          " title="Hoparlör">🔊</button>
        </div>
      </div>

      <!-- Call Ended View -->
      <div class="phone-ended" style="
        display: none;
        flex-direction: column;
        align-items: center;
        gap: 12px;
      ">
        <div style="
          color: rgba(200, 220, 240, 0.5);
          font-size: 14px;
          letter-spacing: 2px;
          text-transform: uppercase;
        ">ARAMA SONLANDI</div>
        <div class="phone-ended-duration" style="
          color: #e0f0ff;
          font-size: 18px;
        "></div>
      </div>
    `;

    parent.appendChild(this._el);
    this._bindEvents();

    // Inject keyframe animation
    if (!document.getElementById('phone-call-styles')) {
      const style = document.createElement('style');
      style.id = 'phone-call-styles';
      style.textContent = `
        @keyframes phone-ring-pulse {
          0% { transform: scale(1); opacity: 0.6; }
          100% { transform: scale(1.8); opacity: 0; }
        }
        .phone-btn:hover {
          transform: scale(1.12) !important;
        }
        .phone-btn:active {
          transform: scale(0.95) !important;
        }
        .phone-mute.active, .phone-speaker.active {
          background: rgba(0, 255, 200, 0.2) !important;
          border-color: rgba(0, 255, 200, 0.4) !important;
        }
      `;
      document.head.appendChild(style);
    }

    console.log('[PhoneCallOverlay] Mounted');
  }

  /**
   * Bind button click events.
   */
  _bindEvents() {
    const acceptBtn = this._el.querySelector('.phone-accept');
    const rejectBtn = this._el.querySelector('.phone-reject');
    const hangupBtn = this._el.querySelector('.phone-hangup');
    const muteBtn = this._el.querySelector('.phone-mute');
    const speakerBtn = this._el.querySelector('.phone-speaker');

    acceptBtn.addEventListener('click', () => this.acceptCall());
    rejectBtn.addEventListener('click', () => this.rejectCall());
    hangupBtn.addEventListener('click', () => this.hangUp());

    muteBtn.addEventListener('click', () => {
      muteBtn.classList.toggle('active');
      this._sendEvent('phone:mute-toggle');
    });

    speakerBtn.addEventListener('click', () => {
      speakerBtn.classList.toggle('active');
      this._sendEvent('phone:speaker-toggle');
    });
  }

  /**
   * Show incoming call screen.
   * @param {{ caller_name: string, caller_number?: string, caller_photo?: string }} info
   */
  showIncoming(info) {
    this._callerInfo = info;
    this._state = 'incoming';

    // Set caller info
    const initial = (info.caller_name || '?').charAt(0).toUpperCase();
    this._el.querySelector('.phone-avatar-text').textContent = initial;
    this._el.querySelector('.phone-caller-name').textContent = info.caller_name || 'Bilinmeyen';
    this._el.querySelector('.phone-caller-number').textContent = info.caller_number || '';

    // If photo URL provided, use it as avatar background
    if (info.caller_photo) {
      const avatar = this._el.querySelector('.phone-avatar');
      avatar.style.backgroundImage = `url(${info.caller_photo})`;
      avatar.style.backgroundSize = 'cover';
      avatar.querySelector('.phone-avatar-text').style.display = 'none';
    }

    // Show incoming, hide others
    this._el.querySelector('.phone-incoming').style.display = 'flex';
    this._el.querySelector('.phone-active').style.display = 'none';
    this._el.querySelector('.phone-ended').style.display = 'none';

    // Fade in
    this._el.style.display = 'flex';
    requestAnimationFrame(() => { this._el.style.opacity = '1'; });

    // Notify sphere to enter "ringing" state
    if (window.bantzStateAnimator) {
      window.bantzStateAnimator.setState('listening');
    }

    console.log(`[PhoneCallOverlay] Incoming: ${info.caller_name}`);
  }

  /**
   * Accept the incoming call — transition to active view.
   */
  acceptCall() {
    if (this._state !== 'incoming') return;
    this._state = 'active';

    // Update active view
    const name = this._callerInfo?.caller_name || 'Arama';
    const initial = name.charAt(0).toUpperCase();
    this._el.querySelector('.phone-active-avatar-text').textContent = initial;
    this._el.querySelector('.phone-active-name').textContent = name;

    if (this._callerInfo?.caller_photo) {
      const avatar = this._el.querySelector('.phone-active-avatar');
      avatar.style.backgroundImage = `url(${this._callerInfo.caller_photo})`;
      avatar.style.backgroundSize = 'cover';
      avatar.querySelector('.phone-active-avatar-text').style.display = 'none';
    }

    // Switch views
    this._el.querySelector('.phone-incoming').style.display = 'none';
    this._el.querySelector('.phone-active').style.display = 'flex';

    // Start timer
    this._callStart = Date.now();
    const timerEl = this._el.querySelector('.phone-active-timer');
    this._timerInterval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - this._callStart) / 1000);
      const min = String(Math.floor(elapsed / 60)).padStart(2, '0');
      const sec = String(elapsed % 60).padStart(2, '0');
      timerEl.textContent = `${min}:${sec}`;
    }, 1000);

    // Tell daemon
    this._sendEvent('phone:accept');

    // Sphere state
    if (window.bantzStateAnimator) {
      window.bantzStateAnimator.setState('speaking');
    }

    console.log('[PhoneCallOverlay] Call accepted');
  }

  /**
   * Reject the incoming call.
   */
  rejectCall() {
    if (this._state !== 'incoming') return;
    this._sendEvent('phone:reject');
    this._showEnded(0);
    console.log('[PhoneCallOverlay] Call rejected');
  }

  /**
   * Hang up an active call.
   */
  hangUp() {
    if (this._state !== 'active') return;
    const duration = this._callStart
      ? Math.floor((Date.now() - this._callStart) / 1000)
      : 0;
    this._sendEvent('phone:hangup');
    this._showEnded(duration);
    console.log('[PhoneCallOverlay] Call hung up');
  }

  /**
   * External: daemon tells us call ended (remote hangup).
   * @param {number} durationSeconds
   */
  callEnded(durationSeconds) {
    this._showEnded(durationSeconds || 0);
  }

  /**
   * Show "call ended" view then auto-hide.
   */
  _showEnded(durationSeconds) {
    this._state = 'ended';
    if (this._timerInterval) clearInterval(this._timerInterval);

    // Format duration
    if (durationSeconds > 0) {
      const min = Math.floor(durationSeconds / 60);
      const sec = durationSeconds % 60;
      this._el.querySelector('.phone-ended-duration').textContent =
        `${min} dk ${sec} sn`;
    } else {
      this._el.querySelector('.phone-ended-duration').textContent = '';
    }

    // Switch views
    this._el.querySelector('.phone-incoming').style.display = 'none';
    this._el.querySelector('.phone-active').style.display = 'none';
    this._el.querySelector('.phone-ended').style.display = 'flex';

    // Sphere back to idle
    if (window.bantzStateAnimator) {
      window.bantzStateAnimator.setState('idle');
    }

    // Auto-hide after 2s
    setTimeout(() => this.hide(), 2000);
  }

  /**
   * Hide the overlay.
   */
  hide() {
    this._el.style.opacity = '0';
    setTimeout(() => {
      this._el.style.display = 'none';
      this._state = 'hidden';
      this._callerInfo = null;
      if (this._timerInterval) clearInterval(this._timerInterval);

      // Reset views
      this._el.querySelector('.phone-incoming').style.display = 'none';
      this._el.querySelector('.phone-active').style.display = 'none';
      this._el.querySelector('.phone-ended').style.display = 'none';

      // Reset mute/speaker
      this._el.querySelector('.phone-mute').classList.remove('active');
      this._el.querySelector('.phone-speaker').classList.remove('active');

      // Reset avatar
      const avatars = this._el.querySelectorAll('.phone-avatar, .phone-active-avatar');
      avatars.forEach(a => {
        a.style.backgroundImage = '';
        const txt = a.querySelector('span');
        if (txt) txt.style.display = '';
      });
    }, 400);
  }

  /**
   * Send event to daemon via overlay IPC bridge.
   */
  _sendEvent(eventName) {
    if (window.overlayAPI && window.overlayAPI.sendDaemonEvent) {
      window.overlayAPI.sendDaemonEvent({
        type: 'event',
        event: eventName,
        data: { caller: this._callerInfo },
      });
    }
  }

  /**
   * @returns {'hidden'|'incoming'|'active'|'ended'}
   */
  get state() {
    return this._state;
  }
}

// ── Expose globally ─────────────────────────────────────────────
window.PhoneCallOverlay = PhoneCallOverlay;

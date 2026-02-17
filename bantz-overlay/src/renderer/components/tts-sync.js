/**
 * Bantz Overlay — TTS Voice Sync (#1415)
 *
 * Synchronizes typewriter text output with TTS voice playback
 * so words appear on-screen as they are spoken.
 *
 * Listens for IPC `tts_word_boundary` events containing:
 *   { word_index, timestamp, word }
 *
 * Modes:
 *   - Synced: TTS active → typewriter follows word boundaries
 *   - Fallback: No TTS data → token-rate-based timing (30ms/token)
 *   - Mute: TTS disabled → typewriter runs independently
 *
 * @module tts-sync
 */

'use strict';

// ── Config ────────────────────────────────────────────────────────
const TTS_SYNC_CONFIG = {
  highlightDuration:   200,   // ms to highlight spoken word
  highlightColor:      '#ffffff',  // brighter white for spoken word
  catchUpThreshold:    3,     // words behind before instant catch-up
  fallbackTokenDelay:  30,    // ms per token when no TTS data
  idleTimeout:         5000,  // ms without word boundary → assume TTS stopped
  speakerFadeIn:       300,   // ms for speaker icon appear
  speakerFadeOut:      500,   // ms for speaker icon disappear
};

/**
 * TTS Voice Synchronizer.
 *
 * Bridges the gap between TTS word-boundary events and the
 * typewriter visual output, keeping them perceptually in sync.
 */
class TTSVoiceSync {
  /**
   * @param {object} typewriter — TypewriterOutput instance
   * @param {HTMLElement} hudPanel — Main HUD panel (for speaker icon)
   */
  constructor(typewriter, hudPanel) {
    /** @type {object} */
    this._typewriter = typewriter;
    /** @type {HTMLElement} */
    this._hud = hudPanel;

    /** Whether TTS is currently active */
    this._ttsActive = false;

    /** Whether TTS is enabled (not muted) */
    this._ttsEnabled = true;

    /** Current word index from TTS */
    this._currentWordIndex = 0;

    /** Total tokens/words pushed to typewriter */
    this._totalTokens = 0;

    /** Words buffer for highlight tracking */
    this._words = [];

    /** Idle timeout handle */
    this._idleTimer = null;

    /** Speaker icon element */
    this._speakerIcon = null;

    this._createSpeakerIcon();

    console.log('[TTSSync] Initialized');
  }

  // ── Public API ────────────────────────────────────────────────

  /**
   * Called when TTS playback starts.
   */
  onTTSStart() {
    this._ttsActive = true;
    this._currentWordIndex = 0;
    this._totalTokens = 0;
    this._words = [];
    this._showSpeakerIcon();
    this._resetIdleTimer();
    console.log('[TTSSync] TTS started');
  }

  /**
   * Called when TTS playback ends.
   */
  onTTSEnd() {
    this._ttsActive = false;
    this._hideSpeakerIcon();
    this._clearIdleTimer();
    console.log('[TTSSync] TTS ended');
  }

  /**
   * Handle a TTS word boundary event.
   *
   * @param {object} event
   * @param {number} event.word_index — Index of the word being spoken
   * @param {number} event.timestamp  — Timestamp of the boundary
   * @param {string} [event.word]     — The word itself
   */
  onWordBoundary(event) {
    if (!this._ttsActive) return;
    this._resetIdleTimer();

    const targetIndex = event.word_index;

    // Check if typewriter is behind — catch up if needed
    if (targetIndex - this._currentWordIndex > TTS_SYNC_CONFIG.catchUpThreshold) {
      // Catch up instantly: flush pending tokens
      this._catchUp(targetIndex);
    }

    this._currentWordIndex = targetIndex;

    // Highlight the currently spoken word
    if (event.word) {
      this._highlightWord(event.word);
    }
  }

  /**
   * Register a token being added to typewriter.
   * Used to track how many tokens have been rendered.
   *
   * @param {string} token
   */
  trackToken(token) {
    this._totalTokens++;
    if (token.trim()) {
      this._words.push(token.trim());
    }
  }

  /**
   * Set whether TTS is enabled (vs muted).
   * When muted, typewriter runs at normal speed independently.
   *
   * @param {boolean} enabled
   */
  setTTSEnabled(enabled) {
    this._ttsEnabled = !!enabled;
    if (!enabled) {
      this._ttsActive = false;
      this._hideSpeakerIcon();
    }
  }

  /**
   * Whether TTS is currently active and syncing.
   * @returns {boolean}
   */
  get isSyncing() {
    return this._ttsActive && this._ttsEnabled;
  }

  /**
   * Get the appropriate token delay based on sync state.
   * - Synced: 0ms (typewriter waits for word boundaries)
   * - Fallback: 30ms per token
   * - Mute: 30ms per token
   *
   * @returns {number} Delay in ms
   */
  getTokenDelay() {
    if (this._ttsActive && this._ttsEnabled) {
      return 0; // TTS drives the timing
    }
    return TTS_SYNC_CONFIG.fallbackTokenDelay;
  }

  /** Cleanup */
  destroy() {
    this._clearIdleTimer();
    if (this._speakerIcon && this._speakerIcon.parentNode) {
      this._speakerIcon.parentNode.removeChild(this._speakerIcon);
    }
  }

  // ── Internal ──────────────────────────────────────────────────

  /**
   * Catch up typewriter to match TTS position.
   * @param {number} targetIndex
   * @private
   */
  _catchUp(targetIndex) {
    if (!this._typewriter) return;

    // If typewriter supports instant flush, use it
    const behind = targetIndex - this._currentWordIndex;
    console.log(`[TTSSync] Catching up ${behind} words`);

    // Signal typewriter to flush its queue
    if (this._typewriter._flushQueue) {
      this._typewriter._flushQueue();
    }
  }

  /**
   * Briefly highlight the currently spoken word in the typewriter.
   * @param {string} word
   * @private
   */
  _highlightWord(word) {
    const container = this._typewriter?._container ||
                      document.getElementById('typewriter-output');
    if (!container) return;

    const textEl = container.querySelector('#typewriter-text') ||
                   container.querySelector('span');
    if (!textEl) return;

    // Find the word in the current text content
    const text = textEl.textContent || '';
    const wordStart = text.lastIndexOf(word);
    if (wordStart < 0) return;

    // Create a range and wrap the word temporarily
    // Use a non-destructive approach: apply a CSS class via a span
    const before = text.substring(0, wordStart);
    const after = text.substring(wordStart + word.length);

    textEl.innerHTML =
      `${this._escapeHtml(before)}<span class="tts-spoken-word">${this._escapeHtml(word)}</span>${this._escapeHtml(after)}`;

    // Remove highlight after duration
    setTimeout(() => {
      const highlight = textEl.querySelector('.tts-spoken-word');
      if (highlight) {
        highlight.classList.add('tts-spoken-word-fade');
        setTimeout(() => {
          // Restore plain text
          textEl.textContent = text;
        }, 100);
      }
    }, TTS_SYNC_CONFIG.highlightDuration);
  }

  /**
   * Escape HTML entities.
   * @param {string} str
   * @returns {string}
   * @private
   */
  _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /**
   * Create the speaker icon indicator.
   * @private
   */
  _createSpeakerIcon() {
    const icon = document.createElement('div');
    icon.className = 'tts-speaker-icon';
    icon.textContent = '🔊';
    icon.style.cssText = `
      position: absolute;
      bottom: 8px;
      right: 12px;
      font-size: 14px;
      opacity: 0;
      transition: opacity ${TTS_SYNC_CONFIG.speakerFadeIn}ms ease-out;
      pointer-events: none;
      z-index: 10;
    `;
    this._hud.appendChild(icon);
    this._speakerIcon = icon;
  }

  /**
   * Show the speaker icon.
   * @private
   */
  _showSpeakerIcon() {
    if (this._speakerIcon) {
      this._speakerIcon.style.opacity = '0.6';
    }
  }

  /**
   * Hide the speaker icon.
   * @private
   */
  _hideSpeakerIcon() {
    if (this._speakerIcon) {
      this._speakerIcon.style.transition =
        `opacity ${TTS_SYNC_CONFIG.speakerFadeOut}ms ease-in`;
      this._speakerIcon.style.opacity = '0';
    }
  }

  /**
   * Reset the idle timer (TTS seems active).
   * @private
   */
  _resetIdleTimer() {
    this._clearIdleTimer();
    this._idleTimer = setTimeout(() => {
      if (this._ttsActive) {
        console.log('[TTSSync] TTS idle timeout — assuming stopped');
        this.onTTSEnd();
      }
    }, TTS_SYNC_CONFIG.idleTimeout);
  }

  /**
   * Clear idle timer.
   * @private
   */
  _clearIdleTimer() {
    if (this._idleTimer) {
      clearTimeout(this._idleTimer);
      this._idleTimer = null;
    }
  }
}

// ── Expose globally ───────────────────────────────────────────────
window.TTSVoiceSync = TTSVoiceSync;

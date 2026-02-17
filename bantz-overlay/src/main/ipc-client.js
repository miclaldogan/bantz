/**
 * Bantz Overlay — IPC Client
 *
 * Connects to the daemon's Unix domain socket (overlay.sock)
 * using JSONL (newline-delimited JSON) wire protocol.
 *
 * Responsibilities:
 * - Auto-connect on startup with retry logic
 * - Parse incoming JSONL messages
 * - Send ack/event/pong messages back to daemon
 * - Emit connection state changes
 * - Handle ping/pong heartbeat
 *
 * Wire format matches src/bantz/ipc/protocol.py:
 *   Socket: ~/.local/share/bantz/ipc/overlay.sock
 *   Each message: JSON object + '\n'
 *   Common fields: v, type, ts, id
 *
 * @module ipc-client
 */

const net = require('net');
const path = require('path');
const fs = require('fs');
const { EventEmitter } = require('events');
const crypto = require('crypto');

// Protocol version — must match Python IPC_VERSION
const IPC_VERSION = 1;

/**
 * Default socket path: ~/.local/share/bantz/ipc/overlay.sock
 */
function getSocketPath() {
  const xdgData = process.env.XDG_DATA_HOME || path.join(process.env.HOME, '.local/share');
  return path.join(xdgData, 'bantz', 'ipc', 'overlay.sock');
}

/**
 * Generate a 12-char hex message ID.
 */
function generateId() {
  return crypto.randomBytes(6).toString('hex');
}

/**
 * Get current timestamp in milliseconds.
 */
function nowMs() {
  return Date.now();
}

/**
 * Connection states.
 * @enum {string}
 */
const ConnectionState = {
  DISCONNECTED: 'disconnected',
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
};

/**
 * IPC Client for communicating with the Bantz daemon.
 *
 * Events emitted:
 * - 'message'         (msg: object) — parsed JSONL message from daemon
 * - 'state-change'    (state: ConnectionState) — connection state changed
 * - 'error'           (err: Error) — socket error
 *
 * @extends EventEmitter
 */
class IPCClient extends EventEmitter {
  /**
   * @param {object} [options]
   * @param {string} [options.socketPath]      - Override socket path
   * @param {number} [options.retryIntervalMs] - Retry interval (default 2000)
   * @param {number} [options.maxRetries]      - Max retries, 0 = infinite (default 0)
   * @param {number} [options.pingTimeoutMs]   - Ping timeout (default 5000)
   */
  constructor(options = {}) {
    super();

    this._socketPath = options.socketPath || getSocketPath();
    this._retryIntervalMs = options.retryIntervalMs || 2000;
    this._maxRetries = options.maxRetries || 0;
    this._pingTimeoutMs = options.pingTimeoutMs || 5000;

    /** @type {net.Socket|null} */
    this._socket = null;

    /** @type {ConnectionState} */
    this._state = ConnectionState.DISCONNECTED;

    /** @type {number} */
    this._retryCount = 0;

    /** @type {NodeJS.Timeout|null} */
    this._retryTimer = null;

    /** @type {NodeJS.Timeout|null} */
    this._pingTimer = null;

    /** Incoming data buffer for partial JSONL messages. */
    this._buffer = '';

    /** Whether the client has been intentionally stopped. */
    this._stopped = false;
  }

  // ─── Public API ─────────────────────────────────────────────

  /**
   * Current connection state.
   * @returns {ConnectionState}
   */
  get state() {
    return this._state;
  }

  /**
   * Whether currently connected.
   * @returns {boolean}
   */
  get connected() {
    return this._state === ConnectionState.CONNECTED;
  }

  /**
   * Start connecting to the daemon socket.
   * Will retry automatically on failure.
   */
  connect() {
    this._stopped = false;
    this._retryCount = 0;
    this._doConnect();
  }

  /**
   * Disconnect and stop retrying.
   */
  disconnect() {
    this._stopped = true;
    this._clearRetryTimer();
    this._clearPingTimer();

    if (this._socket) {
      this._socket.destroy();
      this._socket = null;
    }

    this._setState(ConnectionState.DISCONNECTED);
  }

  /**
   * Send a message to the daemon.
   * @param {object} msg - Message object (will be JSON-serialized + '\n')
   * @returns {boolean} - True if sent, false if not connected
   */
  send(msg) {
    if (!this._socket || this._state !== ConnectionState.CONNECTED) {
      return false;
    }

    // Ensure required fields
    const envelope = {
      v: IPC_VERSION,
      id: generateId(),
      ts: nowMs(),
      ...msg,
    };

    try {
      const line = JSON.stringify(envelope) + '\n';
      this._socket.write(line, 'utf-8');
      return true;
    } catch (err) {
      console.error('[IPC] Send error:', err.message);
      return false;
    }
  }

  /**
   * Send an ACK for a received message.
   * @param {string} msgId - ID of the message being acknowledged
   */
  sendAck(msgId) {
    return this.send({ type: 'ack', id: msgId });
  }

  /**
   * Send a pong reply.
   */
  sendPong() {
    return this.send({ type: 'pong' });
  }

  /**
   * Send an event message (overlay → daemon).
   * @param {string} event - Event type: 'timeout' | 'dismissed'
   * @param {string} [reason] - Reason: 'no_speech' | 'user_close' | 'internal'
   */
  sendEvent(event, reason = 'internal') {
    return this.send({ type: 'event', event, reason });
  }

  // ─── Internal: Connection ───────────────────────────────────

  /**
   * Attempt to connect to the socket.
   * @private
   */
  _doConnect() {
    if (this._stopped) return;

    // Check if socket file exists before attempting connection
    if (!fs.existsSync(this._socketPath)) {
      console.log(`[IPC] Socket not found: ${this._socketPath}`);
      this._setState(ConnectionState.DISCONNECTED);
      this._scheduleRetry();
      return;
    }

    this._setState(ConnectionState.CONNECTING);

    this._socket = new net.Socket();
    this._buffer = '';

    this._socket.connect(this._socketPath, () => {
      console.log('[IPC] Connected to daemon');
      this._retryCount = 0;
      this._setState(ConnectionState.CONNECTED);
    });

    this._socket.on('data', (data) => {
      this._onData(data);
    });

    this._socket.on('error', (err) => {
      // ENOENT = socket doesn't exist, ECONNREFUSED = daemon not listening
      if (err.code !== 'ENOENT' && err.code !== 'ECONNREFUSED') {
        console.error('[IPC] Socket error:', err.message);
      }
      this.emit('error', err);
    });

    this._socket.on('close', () => {
      console.log('[IPC] Connection closed');
      this._socket = null;
      this._setState(ConnectionState.DISCONNECTED);
      this._clearPingTimer();
      this._scheduleRetry();
    });
  }

  /**
   * Handle incoming data from socket.
   * Accumulates into buffer and splits by newline (JSONL).
   * @private
   */
  _onData(data) {
    this._buffer += data.toString('utf-8');

    // Process complete lines (JSONL: each message ends with \n)
    let newlineIdx;
    while ((newlineIdx = this._buffer.indexOf('\n')) !== -1) {
      const line = this._buffer.substring(0, newlineIdx).trim();
      this._buffer = this._buffer.substring(newlineIdx + 1);

      if (!line) continue;

      try {
        const msg = JSON.parse(line);
        this._handleMessage(msg);
      } catch (err) {
        console.error('[IPC] JSON parse error:', err.message, 'line:', line.substring(0, 100));
      }
    }
  }

  /**
   * Process a parsed message.
   * Auto-handles ping/pong; emits all messages.
   * @private
   */
  _handleMessage(msg) {
    // Auto-respond to pings
    if (msg.type === 'ping') {
      this.sendPong();
    }

    // Auto-acknowledge state messages
    if (msg.type === 'state' && msg.id) {
      this.sendAck(msg.id);
    }

    // Emit to listeners
    this.emit('message', msg);
  }

  // ─── Internal: State Management ──────────────────────────────

  /**
   * @private
   */
  _setState(newState) {
    if (this._state !== newState) {
      const oldState = this._state;
      this._state = newState;
      console.log(`[IPC] ${oldState} → ${newState}`);
      this.emit('state-change', newState);
    }
  }

  // ─── Internal: Retry Logic ───────────────────────────────────

  /**
   * @private
   */
  _scheduleRetry() {
    if (this._stopped) return;

    if (this._maxRetries > 0 && this._retryCount >= this._maxRetries) {
      console.log('[IPC] Max retries reached');
      return;
    }

    this._clearRetryTimer();
    this._retryCount++;

    // Exponential backoff: 2s, 4s, 8s, max 30s
    const delay = Math.min(
      this._retryIntervalMs * Math.pow(1.5, Math.min(this._retryCount - 1, 6)),
      30000
    );

    console.log(`[IPC] Retry #${this._retryCount} in ${Math.round(delay)}ms`);

    this._retryTimer = setTimeout(() => {
      this._retryTimer = null;
      this._doConnect();
    }, delay);
  }

  /**
   * @private
   */
  _clearRetryTimer() {
    if (this._retryTimer) {
      clearTimeout(this._retryTimer);
      this._retryTimer = null;
    }
  }

  /**
   * @private
   */
  _clearPingTimer() {
    if (this._pingTimer) {
      clearTimeout(this._pingTimer);
      this._pingTimer = null;
    }
  }
}

module.exports = {
  IPCClient,
  ConnectionState,
  getSocketPath,
  generateId,
  nowMs,
  IPC_VERSION,
};

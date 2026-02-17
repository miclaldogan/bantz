/**
 * Bantz Overlay — IPC Server
 *
 * Creates a Unix domain socket server at overlay.sock that the daemon
 * (OverlayClient) connects to.  Speaks JSONL (newline-delimited JSON).
 *
 * Architecture:
 *   Electron overlay  ──creates──▶  overlay.sock  ◀──connects──  Python daemon
 *
 * This matches the original OverlayServer (Python/PyQt5) contract:
 *   - The overlay process OWNS the socket (creates & cleans up)
 *   - The daemon connects as a client
 *
 * Responsibilities:
 * - Create overlay.sock and listen for incoming daemon connection
 * - Parse incoming JSONL messages from daemon
 * - Send ack/event/pong messages back to daemon
 * - Emit connection state changes
 * - Handle ping/pong heartbeat
 * - Allow only ONE daemon connection at a time
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
 * Ensure socket directory exists with correct permissions.
 */
function ensureSocketDir() {
  const socketPath = getSocketPath();
  const dir = path.dirname(socketPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    console.log(`[IPC] Created socket directory: ${dir}`);
  }
}

/**
 * Remove stale socket file if it exists.
 */
function cleanupSocket() {
  const socketPath = getSocketPath();
  if (fs.existsSync(socketPath)) {
    try {
      fs.unlinkSync(socketPath);
      console.log('[IPC] Removed stale socket');
    } catch (err) {
      console.error('[IPC] Failed to remove stale socket:', String(err.message || '').replace(/[\r\n]/g, ''));
    }
  }
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
 * IPC Server for communicating with the Bantz daemon.
 *
 * Creates a Unix socket server that the daemon's OverlayClient connects to.
 * API-compatible with the old IPCClient so main.js needs minimal changes.
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
   * @param {number} [options.pingTimeoutMs]   - Ping timeout (default 5000)
   */
  constructor(options = {}) {
    super();

    this._socketPath = options.socketPath || getSocketPath();
    this._pingTimeoutMs = options.pingTimeoutMs || 5000;

    /** @type {net.Server|null} */
    this._server = null;

    /** @type {net.Socket|null} - The connected daemon socket */
    this._socket = null;

    /** @type {ConnectionState} */
    this._state = ConnectionState.DISCONNECTED;

    /** @type {NodeJS.Timeout|null} */
    this._pingTimer = null;

    /** Incoming data buffer for partial JSONL messages. */
    this._buffer = '';

    /** Whether the server has been intentionally stopped. */
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
   * Whether a daemon client is currently connected.
   * @returns {boolean}
   */
  get connected() {
    return this._state === ConnectionState.CONNECTED;
  }

  /**
   * Create the Unix socket server and start listening.
   * The daemon's OverlayClient will connect to us.
   * Method name kept as connect() for API compatibility with main.js.
   */
  connect() {
    if (this._server) return; // already listening

    this._stopped = false;

    // Ensure directory & clean stale socket
    ensureSocketDir();
    cleanupSocket();

    this._setState(ConnectionState.CONNECTING);

    this._server = net.createServer((daemonSocket) => {
      this._onDaemonConnected(daemonSocket);
    });

    this._server.on('error', (err) => {
      console.error('[IPC] Server error:', String(err.message || '').replace(/[\r\n]/g, ''));
      this.emit('error', err);
    });

    this._server.listen(this._socketPath, () => {
      // Set perms: user-only read/write
      try {
        fs.chmodSync(this._socketPath, 0o600);
      } catch (_) { /* ignore */ }
      console.log(`[IPC] Server listening on ${this._socketPath}`);
      // Stay in CONNECTING until daemon actually connects
    });
  }

  /**
   * Stop the server, disconnect daemon, cleanup socket.
   */
  disconnect() {
    this._stopped = true;
    this._clearPingTimer();

    if (this._socket) {
      this._socket.destroy();
      this._socket = null;
    }

    if (this._server) {
      this._server.close();
      this._server = null;
    }

    cleanupSocket();
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

  // ─── Internal: Connection Handling ──────────────────────────

  /**
   * Handle a new daemon connection.
   * Only ONE daemon connection is allowed at a time.
   * @private
   */
  _onDaemonConnected(daemonSocket) {
    if (this._socket) {
      console.warn('[IPC] Daemon already connected, rejecting new connection');
      daemonSocket.destroy();
      return;
    }

    console.log('[IPC] Daemon connected');
    this._socket = daemonSocket;
    this._buffer = '';
    this._setState(ConnectionState.CONNECTED);

    daemonSocket.on('data', (data) => {
      this._onData(data);
    });

    daemonSocket.on('error', (err) => {
      if (err.code !== 'ECONNRESET' && err.code !== 'EPIPE') {
        console.error('[IPC] Daemon socket error:', String(err.message || '').replace(/[\r\n]/g, ''));
      }
      this.emit('error', err);
    });

    daemonSocket.on('close', () => {
      console.log('[IPC] Daemon disconnected');
      this._socket = null;
      this._buffer = '';
      this._clearPingTimer();
      this._setState(ConnectionState.DISCONNECTED);
      // Server keeps listening — daemon may reconnect
      if (!this._stopped) {
        this._setState(ConnectionState.CONNECTING);
      }
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

/**
 * Bantz Overlay — IPC Client Tests
 *
 * Unit tests for the IPC client module.
 * Uses a mock Unix socket server to verify the client behavior.
 *
 * Run: node bantz-overlay/tests/test_ipc_client.js
 */

const net = require('net');
const fs = require('fs');
const path = require('path');
const os = require('os');
const assert = require('assert');
const { IPCClient, ConnectionState, IPC_VERSION, generateId, nowMs } = require('../src/main/ipc-client');

// Test socket in temp dir to avoid polluting real paths
const TEST_SOCKET = path.join(os.tmpdir(), `bantz-test-ipc-${process.pid}.sock`);

// Clean up socket file
function cleanup() {
  try { fs.unlinkSync(TEST_SOCKET); } catch (_) {}
}

/**
 * Create a mock daemon server on the test socket.
 * @returns {Promise<net.Server>}
 */
function createMockServer() {
  return new Promise((resolve) => {
    cleanup();
    const server = net.createServer();
    server.listen(TEST_SOCKET, () => resolve(server));
  });
}

/**
 * Collect messages from a socket connection.
 * @param {net.Socket} socket
 * @returns {{ messages: object[] }}
 */
function messageCollector(socket) {
  const collector = { messages: [], buffer: '' };
  socket.on('data', (data) => {
    collector.buffer += data.toString();
    let idx;
    while ((idx = collector.buffer.indexOf('\n')) !== -1) {
      const line = collector.buffer.substring(0, idx).trim();
      collector.buffer = collector.buffer.substring(idx + 1);
      if (line) {
        try { collector.messages.push(JSON.parse(line)); } catch (_) {}
      }
    }
  });
  return collector;
}

/**
 * Wait for a condition with timeout.
 */
function waitFor(condFn, timeoutMs = 3000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const check = () => {
      if (condFn()) return resolve();
      if (Date.now() - start > timeoutMs) return reject(new Error('Timeout'));
      setTimeout(check, 50);
    };
    check();
  });
}

// ─── Tests ────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;

async function test(name, fn) {
  try {
    await fn();
    passed++;
    console.log(`  ✓ ${name}`);
  } catch (err) {
    failed++;
    console.log(`  ✗ ${name}`);
    console.log(`    ${err.message}`);
  }
}

async function runTests() {
  console.log('IPC Client Tests\n');

  // ── Test: generateId returns 12-char hex
  await test('generateId returns 12-char hex string', async () => {
    const id = generateId();
    assert.strictEqual(id.length, 12);
    assert.ok(/^[0-9a-f]{12}$/.test(id));
  });

  // ── Test: nowMs returns reasonable timestamp
  await test('nowMs returns current millisecond timestamp', async () => {
    const ts = nowMs();
    assert.ok(ts > 1700000000000); // after ~2023
    assert.ok(ts < 2000000000000); // before ~2033
  });

  // ── Test: Client starts disconnected
  await test('client starts in DISCONNECTED state', async () => {
    const client = new IPCClient({ socketPath: TEST_SOCKET });
    assert.strictEqual(client.state, ConnectionState.DISCONNECTED);
    assert.strictEqual(client.connected, false);
  });

  // ── Test: Client connects to mock server
  await test('client connects to mock daemon', async () => {
    const server = await createMockServer();
    const client = new IPCClient({ socketPath: TEST_SOCKET, retryIntervalMs: 100 });

    const stateChanges = [];
    client.on('state-change', (s) => stateChanges.push(s));

    server.on('connection', () => {}); // accept connection

    client.connect();
    await waitFor(() => client.connected);

    assert.strictEqual(client.state, ConnectionState.CONNECTED);
    assert.ok(stateChanges.includes(ConnectionState.CONNECTING));
    assert.ok(stateChanges.includes(ConnectionState.CONNECTED));

    client.disconnect();
    server.close();
    cleanup();
  });

  // ── Test: Client receives JSONL messages
  await test('client receives and parses JSONL messages', async () => {
    const server = await createMockServer();
    const client = new IPCClient({ socketPath: TEST_SOCKET, retryIntervalMs: 100 });

    const received = [];
    client.on('message', (msg) => received.push(msg));

    server.on('connection', (socket) => {
      // Send a state message
      const msg = { v: 1, type: 'state', id: 'test123', ts: Date.now(), state: 'idle' };
      socket.write(JSON.stringify(msg) + '\n');
    });

    client.connect();
    await waitFor(() => received.length > 0);

    assert.strictEqual(received[0].type, 'state');
    assert.strictEqual(received[0].state, 'idle');
    assert.strictEqual(received[0].id, 'test123');

    client.disconnect();
    server.close();
    cleanup();
  });

  // ── Test: Client auto-responds to ping
  await test('client auto-responds pong to ping', async () => {
    const server = await createMockServer();
    const client = new IPCClient({ socketPath: TEST_SOCKET, retryIntervalMs: 100 });
    let collector;

    server.on('connection', (socket) => {
      collector = messageCollector(socket);
      // Send ping
      socket.write(JSON.stringify({ v: 1, type: 'ping', id: 'ping1', ts: Date.now() }) + '\n');
    });

    client.connect();
    await waitFor(() => collector && collector.messages.some((m) => m.type === 'pong'), 3000);

    const pong = collector.messages.find((m) => m.type === 'pong');
    assert.ok(pong, 'Pong message not found');
    assert.strictEqual(pong.type, 'pong');
    assert.strictEqual(pong.v, IPC_VERSION);

    client.disconnect();
    server.close();
    cleanup();
  });

  // ── Test: Client auto-acks state messages
  await test('client auto-acks state messages', async () => {
    const server = await createMockServer();
    const client = new IPCClient({ socketPath: TEST_SOCKET, retryIntervalMs: 100 });
    let collector;

    server.on('connection', (socket) => {
      collector = messageCollector(socket);
      // Send state message
      socket.write(JSON.stringify({
        v: 1, type: 'state', id: 'state42', ts: Date.now(), state: 'thinking'
      }) + '\n');
    });

    client.connect();
    await waitFor(() => collector && collector.messages.some((m) => m.type === 'ack'), 3000);

    const ack = collector.messages.find((m) => m.type === 'ack');
    assert.ok(ack, 'ACK not found');
    assert.strictEqual(ack.id, 'state42');

    client.disconnect();
    server.close();
    cleanup();
  });

  // ── Test: Client sends event messages
  await test('client.sendEvent sends correct format', async () => {
    const server = await createMockServer();
    const client = new IPCClient({ socketPath: TEST_SOCKET, retryIntervalMs: 100 });
    let collector;

    server.on('connection', (socket) => {
      collector = messageCollector(socket);
    });

    client.connect();
    await waitFor(() => client.connected);

    client.sendEvent('dismissed', 'user_close');
    await waitFor(() => collector && collector.messages.some((m) => m.type === 'event'));

    const event = collector.messages.find((m) => m.type === 'event');
    assert.ok(event);
    assert.strictEqual(event.event, 'dismissed');
    assert.strictEqual(event.reason, 'user_close');
    assert.strictEqual(event.v, IPC_VERSION);

    client.disconnect();
    server.close();
    cleanup();
  });

  // ── Test: Client handles multiple JSONL in one chunk
  await test('client handles multiple messages in one data chunk', async () => {
    const server = await createMockServer();
    const client = new IPCClient({ socketPath: TEST_SOCKET, retryIntervalMs: 100 });
    const received = [];
    client.on('message', (msg) => received.push(msg));

    server.on('connection', (socket) => {
      // Send two messages in one write (batched)
      const msg1 = JSON.stringify({ v: 1, type: 'state', id: 'a', ts: 1, state: 'idle' });
      const msg2 = JSON.stringify({ v: 1, type: 'state', id: 'b', ts: 2, state: 'thinking' });
      socket.write(msg1 + '\n' + msg2 + '\n');
    });

    client.connect();
    await waitFor(() => received.length >= 2);

    assert.strictEqual(received[0].id, 'a');
    assert.strictEqual(received[1].id, 'b');

    client.disconnect();
    server.close();
    cleanup();
  });

  // ── Test: send returns false when disconnected
  await test('send returns false when disconnected', async () => {
    const client = new IPCClient({ socketPath: TEST_SOCKET });
    const result = client.send({ type: 'event', event: 'timeout' });
    assert.strictEqual(result, false);
  });

  // ── Test: Disconnect stops retrying
  await test('disconnect stops retry loop', async () => {
    const client = new IPCClient({ socketPath: TEST_SOCKET, retryIntervalMs: 100 });

    client.connect();
    // Wait a bit for retry to start
    await new Promise((r) => setTimeout(r, 150));
    client.disconnect();

    assert.strictEqual(client.state, ConnectionState.DISCONNECTED);
    assert.strictEqual(client._retryTimer, null);
  });

  // ── Summary ────
  console.log(`\n${passed + failed} tests, ${passed} passed, ${failed} failed`);
  cleanup();
  process.exit(failed > 0 ? 1 : 0);
}

runTests().catch((err) => {
  console.error('Test runner error:', err);
  cleanup();
  process.exit(1);
});

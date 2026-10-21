import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readdir, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const here = new URL('.', import.meta.url);
const bundle = new URL('./buzz-managed.mjs', here);
const fixtureKey = '01'.padStart(64, '0');
const fixturePubkey = '79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798';
const ownerPubkey = '11'.repeat(32);
const fixtureSig = '22'.repeat(64);

function rpc(child, message) {
  child.stdin.write(`${JSON.stringify(message)}\n`);
}

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return Buffer.concat(chunks);
}

test('stdio initialize and tool listing are offline, clean, and complete', async (t) => {
  const root = await mkdtemp(join(tmpdir(), 'buzz-managed-test-'));
  const home = join(root, 'home');
  await mkdir(home);
  const attachmentPath = join(root, 'fixture.png');
  await writeFile(attachmentPath, Buffer.from('synthetic attachment'));
  t.after(async () => rm(root, { recursive: true, force: true }));

  const channelId = 'aa'.repeat(32);
  const targetId = 'bb'.repeat(32);
  const rootId = 'cc'.repeat(32);
  const targetAuthor = 'dd'.repeat(32);
  const imeta = ['imeta', 'url http://fixture.invalid/media.png', 'm image/png', 'x ' + '33'.repeat(32), 'size 20', 'name fixture.png'];
  const targetEvent = {
    id: targetId,
    pubkey: targetAuthor,
    created_at: 1_700_000_000,
    kind: 9,
    content: 'synthetic target',
    tags: [
      ['h', channelId],
      ['e', rootId, '', 'root'],
      ['p', fixturePubkey],
      imeta,
      ['auth', ownerPubkey, 'managed-agent', fixtureSig],
      ['x-private-test', 'must not escape'],
    ],
    sig: '44'.repeat(64),
  };
  const requests = [];
  let submittedEvent = null;
  const relay = createServer(async (request, response) => {
    const rawBody = await readBody(request);
    const body = request.method === 'POST' ? JSON.parse(rawBody.toString('utf8') || 'null') : null;
    requests.push({ method: request.method, url: request.url, body });
    response.setHeader('Content-Type', 'application/json');
    if (request.method === 'PUT' && request.url === '/upload') {
      response.end(JSON.stringify({
        url: `http://127.0.0.1/media/${'33'.repeat(32)}.png`,
        sha256: '33'.repeat(32),
        size: 20,
        type: 'image/png',
      }));
      return;
    }
    if (request.method === 'POST' && request.url === '/events') {
      submittedEvent = body;
      response.end(JSON.stringify({ ok: true }));
      return;
    }
    if (request.method === 'POST' && request.url === '/query') {
      const filter = body[0] || {};
      let result = [];
      if (filter.kinds?.[0] === 39002) {
        result = [{ id: '55'.repeat(32), pubkey: ownerPubkey, kind: 39002, content: '', tags: [['d', channelId], ['p', fixturePubkey]] }];
      } else if (filter.kinds?.[0] === 39000) {
        result = [{ id: '66'.repeat(32), pubkey: ownerPubkey, kind: 39000, content: '', tags: [['d', channelId], ['name', 'Agent Codex Thai'], ['about', 'fixture']] }];
      } else if (filter.kinds?.[0] === 0) {
        result = [{ id: '77'.repeat(32), pubkey: targetAuthor, kind: 0, content: JSON.stringify({ display_name: 'Fixture Author' }), tags: [] }];
      } else if (filter.kinds?.[0] === 9 || filter.ids?.includes(targetId)) {
        result = [targetEvent];
      }
      response.end(JSON.stringify(result));
      return;
    }
    response.writeHead(500).end(JSON.stringify({ error: 'unexpected synthetic route' }));
  });
  await new Promise((resolve) => relay.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => relay.close(resolve)));
  const address = relay.address();

  const secretSentinel = fixtureKey;
  const child = spawn(process.execPath, [bundle.pathname.replace(/^\/(.:)/, '$1')], {
    env: {
      PATH: process.env.PATH,
      SystemRoot: process.env.SystemRoot,
      HOME: home,
      USERPROFILE: home,
      BUZZ_PRIVATE_KEY: fixtureKey,
      BUZZ_EXPECTED_PUBKEY: fixturePubkey,
      BUZZ_AUTH_TAG: JSON.stringify(['auth', ownerPubkey, 'managed-agent', fixtureSig]),
      BUZZ_RELAY_HTTP: `http://127.0.0.1:${address.port}`,
      BUZZ_IDENTITY_NAME: 'Codex Thai Test Fixture',
    },
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  t.after(() => child.kill());

  let stderr = '';
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', (chunk) => { stderr += chunk; });
  const responses = new Map();
  let stdoutBuffer = '';
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {
    stdoutBuffer += chunk;
    while (stdoutBuffer.includes('\n')) {
      const newline = stdoutBuffer.indexOf('\n');
      const line = stdoutBuffer.slice(0, newline).trim();
      stdoutBuffer = stdoutBuffer.slice(newline + 1);
      if (line) {
        const message = JSON.parse(line);
        if ('id' in message) responses.set(message.id, message);
      }
    }
  });

  async function waitFor(id) {
    const deadline = Date.now() + 5000;
    while (!responses.has(id) && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    assert.ok(responses.has(id), `response ${id} missing; stderr=${stderr}`);
    return responses.get(id);
  }

  rpc(child, {
    jsonrpc: '2.0', id: 1, method: 'initialize',
    params: { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'fixture', version: '1' } },
  });
  rpc(child, { jsonrpc: '2.0', method: 'notifications/initialized', params: {} });
  rpc(child, { jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} });

  assert.equal((await waitFor(1)).error, undefined);
  const tools = (await waitFor(2)).result.tools;
  assert.equal(tools.length, 24);
  const names = new Set(tools.map((tool) => tool.name));
  for (const expected of ['buzz_read', 'buzz_reply', 'buzz_post', 'buzz_attachment_read']) {
    assert.ok(names.has(expected), `missing ${expected}`);
  }

  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(requests.length, 0, 'startup made a relay/profile request');
  assert.deepEqual(await readdir(home), [], 'managed startup wrote into HOME/USERPROFILE');
  assert.ok(!stderr.includes(secretSentinel), 'stderr exposed the private fixture key');

  rpc(child, {
    jsonrpc: '2.0', id: 3, method: 'tools/call',
    params: { name: 'buzz_read', arguments: { channel: 'Agent Codex Thai', limit: 10 } },
  });
  const readResponse = await waitFor(3);
  assert.equal(readResponse.error, undefined);
  const readPayload = JSON.parse(readResponse.result.content[0].text);
  assert.equal(readPayload.channel, channelId);
  assert.equal(readPayload.events[0].id, targetId);
  assert.equal(readPayload.events[0].pubkey, targetAuthor);
  assert.deepEqual(readPayload.events[0].tags, [
    ['h', channelId],
    ['e', rootId, '', 'root'],
    ['p', fixturePubkey],
    imeta,
  ]);
  assert.equal('sig' in readPayload.events[0], false);
  assert.equal(JSON.stringify(readPayload).includes('must not escape'), false);
  assert.equal(JSON.stringify(readPayload).includes(fixtureSig), false);

  rpc(child, {
    jsonrpc: '2.0', id: 4, method: 'tools/call',
    params: {
      name: 'buzz_reply',
      arguments: { channel: 'Agent Codex Thai', event: targetId, text: 'synthetic reply', attachment: attachmentPath },
    },
  });
  const replyResponse = await waitFor(4);
  assert.equal(replyResponse.error, undefined);
  const replyPayload = JSON.parse(replyResponse.result.content[0].text);
  assert.match(replyPayload.event_id, /^[0-9a-f]{64}$/);
  assert.equal(replyPayload.channel, channelId);
  assert.equal(replyPayload.reply_to, targetId);
  assert.equal(replyPayload.root, rootId);
  assert.equal(replyPayload.text, 'synthetic reply');
  assert.equal(replyPayload.attachment.filename, 'fixture.png');
  assert.ok(submittedEvent, 'reply event was not submitted to the synthetic relay');
  assert.ok(submittedEvent.tags.some((tag) => tag[0] === 'e' && tag[1] === rootId && tag[3] === 'root'));
  assert.ok(submittedEvent.tags.some((tag) => tag[0] === 'e' && tag[1] === targetId && tag[3] === 'reply'));
  assert.ok(submittedEvent.tags.some((tag) => tag[0] === 'imeta'));
  assert.equal(replyPayload.event_id, submittedEvent.id);
  assert.ok(!stderr.includes(secretSentinel), 'stderr exposed the private fixture key after tool calls');
  child.kill();
});

import assert from 'node:assert/strict';
import test from 'node:test';

import { enforceManagedMode, resolveManagedKey } from './managed_identity.mjs';

const key = new Uint8Array(32).fill(7);
const pubkey = 'ab'.repeat(32);
const owner = 'cd'.repeat(32);
const sig = 'ef'.repeat(64);
const base = {
  BUZZ_PRIVATE_KEY: '07'.repeat(32),
  BUZZ_EXPECTED_PUBKEY: pubkey,
  BUZZ_AUTH_TAG: JSON.stringify(['auth', owner, 'managed-agent', sig]),
};
const callbacks = {
  decode(value) {
    if (value === 'nsec-fixture') return { type: 'nsec', data: key };
    throw new Error('invalid');
  },
  getPublicKey(value) {
    assert.deepEqual(value, key);
    return pubkey;
  },
  hexToSk(value) {
    assert.equal(value, '07'.repeat(32));
    return key;
  },
};

test('rejects an absent managed key', async () => {
  await assert.rejects(
    resolveManagedKey({ ...base, BUZZ_PRIVATE_KEY: '' }, callbacks),
    /identity was not inherited/,
  );
});

test('rejects an invalid key decoder result without exposing input', async () => {
  const secret = 'this-is-not-a-key';
  await assert.rejects(
    resolveManagedKey({ ...base, BUZZ_PRIVATE_KEY: secret }, callbacks),
    (error) => !error.message.includes(secret) && /invalid agent key encoding/.test(error.message),
  );
});

test('rejects missing and malformed owner delegation', () => {
  assert.throws(() => enforceManagedMode({ ...base, BUZZ_AUTH_TAG: '' }), /owner delegation/);
  assert.throws(() => enforceManagedMode({ ...base, BUZZ_AUTH_TAG: '["auth"]' }), /owner delegation/);
});

test('rejects a key that differs from the explicit pin', async () => {
  await assert.rejects(
    resolveManagedKey(base, { ...callbacks, getPublicKey: () => '12'.repeat(32) }),
    /pinned agent/,
  );
});

test('rejects an agent key equal to the owner identity', async () => {
  const env = {
    ...base,
    BUZZ_EXPECTED_PUBKEY: pubkey,
    BUZZ_AUTH_TAG: JSON.stringify(['auth', pubkey, 'managed-agent', sig]),
  };
  await assert.rejects(resolveManagedKey(env, callbacks), /pinned agent/);
});

test('requires an explicit public-key pin', () => {
  assert.throws(() => enforceManagedMode({ ...base, BUZZ_EXPECTED_PUBKEY: '' }), /identity pin/);
});

test('rejects wire-sign and service-refresh modes', () => {
  assert.throws(() => enforceManagedMode({ ...base, BUZZ_WIRE_SIGN: 'true' }), /refuses human OAuth/);
  assert.throws(() => enforceManagedMode({ ...base, BUZZ_SERVICE_REFRESH: 'refresh' }), /refuses human OAuth/);
});

test('accepts nsec and hex only through in-memory callbacks', async () => {
  let decoded = 0;
  let fromHex = 0;
  const memoryCallbacks = {
    ...callbacks,
    decode(value) {
      decoded += 1;
      assert.equal(value, 'nsec-fixture');
      return { type: 'nsec', data: key };
    },
    hexToSk(value) {
      fromHex += 1;
      assert.equal(value, '07'.repeat(32));
      return key;
    },
  };
  assert.equal(await resolveManagedKey(base, memoryCallbacks), key);
  assert.equal(await resolveManagedKey({ ...base, BUZZ_PRIVATE_KEY: 'nsec-fixture' }, memoryCallbacks), key);
  assert.equal(fromHex, 1);
  assert.equal(decoded, 1);
});

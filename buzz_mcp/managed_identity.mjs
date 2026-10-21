// Managed-agent authentication only. No files, OAuth, fallback identity or logging.
export function enforceManagedMode(env) {
  if (/^(1|true|yes|on)$/i.test(String(env.BUZZ_WIRE_SIGN || '').trim()) ||
      String(env.BUZZ_SERVICE_REFRESH || '').trim()) {
    throw new Error('Managed Buzz MCP refuses human OAuth and service-refresh modes');
  }
  if (!/^[0-9a-f]{64}$/i.test(String(env.BUZZ_EXPECTED_PUBKEY || '').trim())) {
    throw new Error('Managed Buzz MCP requires an explicit public agent identity pin');
  }
  let tag;
  try { tag = JSON.parse(env.BUZZ_AUTH_TAG || ''); } catch {}
  if (!Array.isArray(tag) || tag.length !== 4 || tag[0] !== 'auth' ||
      !/^[0-9a-f]{64}$/i.test(tag[1] || '') || typeof tag[2] !== 'string' ||
      !/^[0-9a-f]{128}$/i.test(tag[3] || '')) {
    throw new Error('Managed Buzz MCP requires the owner delegation supplied by Buzz');
  }
  return tag;
}

export async function resolveManagedKey(env, { decode, getPublicKey, hexToSk }) {
  const tag = enforceManagedMode(env);
  const raw = String(env.BUZZ_PRIVATE_KEY || '').trim();
  if (!raw) throw new Error('Managed Buzz MCP identity was not inherited from Buzz');
  let sk;
  try {
    if (/^[0-9a-f]{64}$/i.test(raw)) sk = hexToSk(raw);
    else {
      const decoded = decode(raw);
      if (decoded.type !== 'nsec') throw new Error();
      sk = decoded.data;
    }
    if (!(sk instanceof Uint8Array) || sk.length !== 32) throw new Error();
  } catch { throw new Error('Managed Buzz MCP received an invalid agent key encoding'); }
  let pubkey;
  try { pubkey = getPublicKey(sk); }
  catch { throw new Error('Managed Buzz MCP received an invalid agent signing key'); }
  const expected = env.BUZZ_EXPECTED_PUBKEY.trim().toLowerCase();
  if (pubkey !== expected || tag[1].toLowerCase() === pubkey) {
    throw new Error('Managed Buzz MCP refuses an identity other than the pinned agent');
  }
  return sk;
}

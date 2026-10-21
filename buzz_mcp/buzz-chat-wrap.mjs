// Codex Thái buzz-chat MCP entry point.
// Buzz runs one harness per community and gives each its own BUZZ_RELAY_URL
// (wss://<community>.communities.buzz.xyz). buzz-managed.mjs only reads
// BUZZ_RELAY_HTTP, so derive it here; otherwise every reply would go to a
// single hard-coded community. Identity (BUZZ_PRIVATE_KEY, BUZZ_AUTH_TAG) is
// forwarded by Codex from the harness environment, never stored in config.
const relay = process.env.BUZZ_RELAY_URL;
if (relay) {
  process.env.BUZZ_RELAY_HTTP = relay
    .replace(/^wss:/i, "https:")
    .replace(/^ws:/i, "http:")
    .replace(/\/+$/, "");
}
await import("./buzz-managed.mjs");

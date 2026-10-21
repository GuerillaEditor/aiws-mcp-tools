"""Build the pinned Buzz MCP bundle for a Buzz-managed agent.

The patch is intentionally marker- and hash-locked.  A source update must be
reviewed before this builder will touch the generated bundle.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


SOURCE = Path(r"C:\GithubRepo\buzz-mcp\dist\buzz-mcp.mjs")
HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "buzz-managed.mjs"
MANIFEST = HERE / "manifest.json"

VERSION = "0.2.22"
COMMIT = "5870e40426a4011c33251ac26e82cd8e614f83d2"
SOURCE_SHA256 = "b4d591d71802276350d404b9f8b49fd76f635b73105861d252c4969b0ae84d81"

SHEBANG = "#!/usr/bin/env node\n"
IMPORT = (
    "import { enforceManagedMode, resolveManagedKey } "
    "from './managed_identity.mjs';\n"
    "enforceManagedMode(process.env);\n"
)
RESOLVE_START = "async function resolveKey(opts = {}) {"
SELFTEST_START = 'if (process.argv.includes("--test")) {'
SIGNER_MARKER = "\n// signer.mjs\n"
MANAGED_RESOLVER = """async function resolveKey(opts = {}) {
  return resolveManagedKey(opts.env ?? process.env, {
    decode: decode3,
    getPublicKey,
    hexToSk
  });
}
"""
AUTO_PROFILE = """if (IDENTITY_OK && signer.canSign(0)) publishProfile(MY_NAME).catch(() => {
});
"""
NO_AUTO_PROFILE = """if (false && IDENTITY_OK && signer.canSign(0)) publishProfile(MY_NAME).catch(() => {
});
"""
READ_HANDLER_START = '    if (name === "buzz_read") {'
READ_HANDLER_END = '    if (name === "buzz_search") {'
READ_RETURN = r"""      return ok(`#${ch.name} (${rows.length} msgs) \u2014 <id> = react target:
` + (rows.join("\n") || "(empty)"));
"""
MANAGED_READ_RETURN = """      return ok(JSON.stringify({
        channel: ch.id,
        events: (evs || []).map((e) => ({
          id: e.id,
          pubkey: e.pubkey,
          created_at: e.created_at,
          content: e.content,
          tags: (e.tags || []).filter((t) => ["h", "e", "p", "imeta"].includes(t[0]))
        }))
      }));
"""
REPLY_HANDLER_START = '    if (name === "buzz_reply") {'
REPLY_HANDLER_END = '    if (name === "buzz_forward") {'
REPLY_RETURN = """      return ok(`replied in #${ch.name} to ${who}'s <${String(target.id).slice(0, 8)}>${mentioned ? ` (p-tagged ${mentioned})` : ""}${attached ? ` [+attachment ${attached.filename}, ${(attached.size / MB).toFixed(1)} MB]` : ""}: ${bodyText}`);
"""
MANAGED_REPLY_RETURN = """      return ok(JSON.stringify({
        event_id: ev.id,
        channel: ch.id,
        reply_to: target.id,
        root: rootId || target.id,
        attachment: attached,
        text: bodyText
      }));
"""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_once(text: str, marker: str, label: str) -> int:
    count = text.count(marker)
    if count != 1:
        raise SystemExit(f"marker mismatch: expected one {label}, found {count}")
    return text.index(marker)


def replace_once_in_handler(
    text: str,
    handler_start: str,
    handler_end: str,
    old: str,
    new: str,
    label: str,
) -> str:
    start = require_once(text, handler_start, f"{label} handler start")
    end = require_once(text, handler_end, f"{label} handler end")
    if end <= start:
        raise SystemExit(f"marker mismatch: {label} handler order")
    segment = text[start:end]
    if segment.count(old) != 1:
        raise SystemExit(
            f"marker mismatch: expected one {label} return in bounded handler, "
            f"found {segment.count(old)}"
        )
    return text[:start] + segment.replace(old, new, 1) + text[end:]


def build() -> None:
    raw = SOURCE.read_bytes()
    actual_hash = sha256(raw)
    if actual_hash != SOURCE_SHA256:
        raise SystemExit(
            f"source hash mismatch: expected {SOURCE_SHA256}, got {actual_hash}"
        )

    # The pinned Windows checkout stores CRLF.  Normalize only after verifying
    # the byte hash so the structural patch remains deterministic everywhere.
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if not text.startswith(SHEBANG):
        raise SystemExit("marker mismatch: source shebang")
    require_once(text, RESOLVE_START, "resolveKey definition")
    require_once(text, SELFTEST_START, "legacy inline self-test")
    require_once(text, SIGNER_MARKER, "signer section")
    require_once(text, AUTO_PROFILE, "startup profile publication")

    resolve_at = text.index(RESOLVE_START)
    selftest_at = text.index(SELFTEST_START)
    signer_at = text.index(SIGNER_MARKER, selftest_at)
    if not resolve_at < selftest_at < signer_at:
        raise SystemExit("marker mismatch: resolver/self-test/signer order")

    # Replace the legacy resolver and remove its inline self-test as one locked
    # range.  That test exercised the disk keystore and must never run here.
    text = text[:resolve_at] + MANAGED_RESOLVER + text[signer_at:]
    text = text.replace(AUTO_PROFILE, NO_AUTO_PROFILE, 1)
    text = replace_once_in_handler(
        text,
        READ_HANDLER_START,
        READ_HANDLER_END,
        READ_RETURN,
        MANAGED_READ_RETURN,
        "buzz_read",
    )
    text = replace_once_in_handler(
        text,
        REPLY_HANDLER_START,
        REPLY_HANDLER_END,
        REPLY_RETURN,
        MANAGED_REPLY_RETURN,
        "buzz_reply",
    )
    text = SHEBANG + IMPORT + text[len(SHEBANG) :]

    if SELFTEST_START in text:
        raise SystemExit("postcondition failed: legacy self-test remains")
    if text.count("resolveManagedKey(opts.env ?? process.env") != 1:
        raise SystemExit("postcondition failed: managed resolver missing or duplicated")
    if text.count(NO_AUTO_PROFILE) != 1:
        raise SystemExit("postcondition failed: startup publication guard")
    if text.count(MANAGED_READ_RETURN) != 1:
        raise SystemExit("postcondition failed: structured buzz_read return")
    if text.count(MANAGED_REPLY_RETURN) != 1:
        raise SystemExit("postcondition failed: structured buzz_reply return")

    built = text.encode("utf-8")
    OUTPUT.write_bytes(built)
    manifest = {
        "name": "buzz-managed",
        "version": VERSION,
        "source": str(SOURCE),
        "source_commit": COMMIT,
        "source_sha256": SOURCE_SHA256,
        "output": OUTPUT.name,
        "output_sha256": sha256(built),
        "patches": [
            "require Buzz-managed in-memory identity with explicit agent pin and owner delegation",
            "remove legacy resolver and disk-writing inline self-test",
            "disable automatic profile publication at startup",
            "return full event IDs and allowlisted thread/attachment tags from buzz_read",
            "return structured event, channel, root, reply, and attachment data from buzz_reply",
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"built {OUTPUT} sha256={manifest['output_sha256']}")


if __name__ == "__main__":
    build()

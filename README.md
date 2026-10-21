# aiws-mcp-tools

Hai MCP tool custom của Nam (không có nguồn public). Clone về máy mới để chạy lại.

```
comfy_media_mcp/   # MCP "comfy-media": gen ảnh/video headless trên ComfyUI local :8188
buzz_mcp/          # MCP "buzz-chat" managed (buzz-chat-wrap.mjs + bundle buzz-managed.mjs)
```

## 1. comfy_media_mcp

- File: `comfy_media_mcp/server.py` (FastMCP). Gọi ComfyUI local tại `http://127.0.0.1:8188`.
- Cần: Python 3.13, `pip install fastmcp requests`, và ComfyUI Desktop đã cài.
- Env ghi đè (đổi cho máy mới nếu khác):
  - `COMFY_URL` (mặc định `http://127.0.0.1:8188`)
  - `COMFY_MEDIA_OUT` (mặc định `C:\AIWorkstation\buzz_agents\claude_media\outputs`)
  - Đường dẫn `COMFY_EXE` hardcode trong `server.py` (`C:\GithubRepo\ComfyUI\Comfy Desktop\Comfy Desktop.exe`) — sửa nếu máy mới cài chỗ khác.

Cấu hình MCP (ví dụ `.mcp.json` / claude_desktop_config):
```json
"comfy-media": {
  "command": "python",
  "args": ["C:\\AIWorkstation\\mcp\\comfy_media_mcp\\server.py"]
}
```

## 2. buzz_mcp (buzz-chat)

- Entry: `buzz_mcp/buzz-chat-wrap.mjs` — derive `BUZZ_RELAY_HTTP` từ `BUZZ_RELAY_URL` rồi import `./buzz-managed.mjs`.
- `buzz-managed.mjs` = bundle đã build (0.2.22, xem `manifest.json`). Nguồn gốc: `C:\GithubRepo\buzz-mcp` → `python build_managed.py` để build lại.
- **Identity không nằm trong repo** — lấy từ env do Buzz forward: `BUZZ_PRIVATE_KEY`, `BUZZ_AUTH_TAG`, `BUZZ_EXPECTED_PUBKEY`, `BUZZ_RELAY_URL`. Không commit các giá trị này.
- Cần Node 18+.

Cấu hình MCP (ví dụ):
```json
"buzz-chat": {
  "command": "node",
  "args": ["...\\buzz_mcp\\buzz-chat-wrap.mjs"]
}
```

## Lưu ý
- Repo private — không có secret/private key nào được commit (đã kiểm). Tất cả định danh đọc từ biến môi trường.
- Sau khi clone, sửa lại đường dẫn tuyệt đối trong `server.py` và trong MCP config cho khớp máy mới.

"""comfy-media MCP: headless image/video generation on the local ComfyUI (127.0.0.1:8188).

Graphs are the recipes proven on this PC (see C:\\AIWorkstation\\knowledge\\comfyui.md, minimax_h3.md):
  image: Z-Image turbo (default), Krea2 turbo, FLUX.2 Klein 9B (+ reference images)
  video: MiniMax H3 FL2VA int8 + fl2v turbo 8-step LoRA, 960x544, 124/158 frames @24fps
ComfyUI's own queue runs one GPU job at a time.
"""
import json, os, pathlib, random, subprocess, time, uuid
from datetime import datetime

import requests
from fastmcp import FastMCP

URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
OUT_ROOT = pathlib.Path(os.environ.get("COMFY_MEDIA_OUT", r"C:\AIWorkstation\buzz_agents\claude_media\outputs"))
COMFY_EXE = r"C:\GithubRepo\ComfyUI\Comfy Desktop\Comfy Desktop.exe"

mcp = FastMCP("comfy-media")


# ---------------------------------------------------------------- helpers

def _up() -> bool:
    try:
        return requests.get(f"{URL}/system_stats", timeout=3).ok
    except requests.RequestException:
        return False


def _need_up():
    if not _up():
        raise RuntimeError("ComfyUI is not running on :8188 - call comfy_start first")


def _upload(path: str) -> str:
    p = pathlib.Path(path)
    if not p.is_file():
        raise FileNotFoundError(path)
    with open(p, "rb") as f:
        r = requests.post(f"{URL}/upload/image", files={"image": (p.name, f)}, data={"overwrite": "true"}, timeout=120)
    r.raise_for_status()
    return r.json()["name"]


def _submit(graph: dict) -> str:
    r = requests.post(f"{URL}/prompt", json={"prompt": graph, "client_id": str(uuid.uuid4())}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected the graph: {r.text[:1500]}")
    return r.json()["prompt_id"]


def _outdir() -> pathlib.Path:
    d = OUT_ROOT / datetime.now().strftime("%Y%m%d")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _strip_png_metadata(data: bytes) -> bytes:
    """Drop text/time/exif chunks (ComfyUI embeds the whole workflow in tEXt); Buzz relay rejects PNGs with metadata."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data
    out, i = [data[:8]], 8
    while i + 8 <= len(data):
        length = int.from_bytes(data[i:i + 4], "big")
        ctype = data[i + 4:i + 8]
        end = i + 12 + length
        if ctype not in (b"tEXt", b"iTXt", b"zTXt", b"tIME", b"eXIf"):
            out.append(data[i:end])
        i = end
    return b"".join(out)


def _collect(pid: str, entry: dict) -> list[str]:
    files = []
    for node_out in entry.get("outputs", {}).values():
        for key in ("images", "gifs", "videos"):
            for im in node_out.get(key, []):
                if im.get("type") != "output":
                    continue
                b = requests.get(f"{URL}/view", params={"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": "output"}, timeout=300).content
                fp = _outdir() / f"{pid[:8]}_{im['filename']}"
                fp.write_bytes(_strip_png_metadata(b))
                files.append(str(fp))
    return files


def _poll(pid: str, max_wait_s: int) -> dict:
    t0 = time.time()
    while True:
        h = requests.get(f"{URL}/history/{pid}", timeout=30).json()
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                msgs = [m for m in st.get("messages", []) if m[0] == "execution_error"]
                return {"status": "error", "prompt_id": pid, "error": json.dumps(msgs)[:1500]}
            if st.get("completed"):
                return {"status": "done", "prompt_id": pid, "seconds": round(time.time() - t0), "files": _collect(pid, h[pid])}
        if time.time() - t0 > max_wait_s:
            q = requests.get(f"{URL}/queue", timeout=10).json()
            running = any(item[1] == pid for item in q.get("queue_running", []))
            return {"status": "running" if running else "queued", "prompt_id": pid,
                    "hint": "call wait_job again with this prompt_id; never resubmit"}
        time.sleep(3)


def _seed(seed: int) -> int:
    return seed if seed >= 0 else random.randint(1, 2**31 - 1)


# ---------------------------------------------------------------- graphs

def _zimage(prompt, w, h, seed, prefix):
    return {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"}},
        "ms": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["unet", 0], "shift": 3.0}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
        "neg": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["pos", 0]}},
        "latent": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "ks": {"class_type": "KSampler", "inputs": {"model": ["ms", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["latent", 0],
                                                    "seed": seed, "steps": 9, "cfg": 1.0, "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1.0}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": prefix}},
    }


def _krea2(prompt, w, h, seed, prefix):
    return {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "krea2_turbo_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_4b_fp8_scaled.safetensors", "type": "krea2", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
        "neg": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["pos", 0]}},
        "latent": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "ks": {"class_type": "KSampler", "inputs": {"model": ["unet", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["latent", 0],
                                                    "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": prefix}},
    }


def _flux2(prompt, refs, w, h, seed, prefix):
    g = {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux-2-klein-9b-fp8.safetensors", "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_8b_fp8mixed.safetensors", "type": "flux2", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
        "neg": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["pos", 0]}},
    }
    pos, neg = ["pos", 0], ["neg", 0]
    for i, name in enumerate(refs):
        g[f"load{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g[f"scale{i}"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": [f"load{i}", 0], "upscale_method": "lanczos", "megapixels": 1.0, "resolution_steps": 1}}
        g[f"enc{i}"] = {"class_type": "VAEEncode", "inputs": {"pixels": [f"scale{i}", 0], "vae": ["vae", 0]}}
        g[f"rp{i}"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": pos, "latent": [f"enc{i}", 0]}}
        g[f"rn{i}"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": neg, "latent": [f"enc{i}", 0]}}
        pos, neg = [f"rp{i}", 0], [f"rn{i}", 0]
    g.update({
        "guider": {"class_type": "CFGGuider", "inputs": {"model": ["unet", 0], "positive": pos, "negative": neg, "cfg": 1.0}},
        "sched": {"class_type": "Flux2Scheduler", "inputs": {"steps": 4, "width": w, "height": h}},
        "latent": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "sampler": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "sca": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["sampler", 0], "sigmas": ["sched", 0], "latent_image": ["latent", 0]}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["sca", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": prefix}},
    })
    return g


def _i2i(g, image_name, w, h, denoise):
    g["init_load"] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
    g["init_scale"] = {"class_type": "ImageScale", "inputs": {"image": ["init_load", 0], "upscale_method": "lanczos", "width": w, "height": h, "crop": "center"}}
    g["init_enc"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["init_scale", 0], "vae": ["vae", 0]}}
    g["ks"]["inputs"]["latent_image"] = ["init_enc", 0]
    g["ks"]["inputs"]["denoise"] = denoise
    g.pop("latent", None)
    return g


def _h3(prompt, w, h, length, seed, prefix, first=None, last=None, mid=None):
    g = {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
        "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["unet", 0], "lora_name": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", "strength_model": 1.0}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_int8_convrot.safetensors"}},
        "prepare": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["clip", 0], "vae": ["vae", 0], "prompt": prompt, "width": w, "height": h, "length": length}},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "sampler": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "sigmas": {"class_type": "BasicScheduler", "inputs": {"model": ["lora", 0], "scheduler": "simple", "steps": 8, "denoise": 1.0}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "combine": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["decode", 0], "frame_rate": 24, "loop_count": 0, "filename_prefix": prefix,
                                                                 "format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": 19, "save_metadata": False,
                                                                 "trim_to_audio": False, "pingpong": False, "save_output": True}},
    }
    for key, name in (("first_frame", first), ("last_frame", last)):
        if name:
            g[f"load_{key}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
            g["prepare"]["inputs"][key] = [f"load_{key}", 0]
    cond = ["prepare", 0]
    if mid:
        g["load_mid"] = {"class_type": "LoadImage", "inputs": {"image": mid}}
        g["guide"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {"positive": cond, "latent": ["prepare", 1], "frame_idx": length // 2,
                                                                   "vae": ["vae", 0], "image": ["load_mid", 0]}}
        cond = ["guide", 0]
    g["guider"] = {"class_type": "BasicGuider", "inputs": {"model": ["lora", 0], "conditioning": cond}}
    g["sample"] = {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["sampler", 0],
                                                                     "sigmas": ["sigmas", 0], "latent_image": ["prepare", 1]}}
    return g


# ---------------------------------------------------------------- tools

@mcp.tool()
def comfy_status() -> dict:
    """ComfyUI health: up/down, GPU VRAM, and how many jobs are running/pending in its queue."""
    if not _up():
        return {"up": False}
    s = requests.get(f"{URL}/system_stats", timeout=5).json()
    q = requests.get(f"{URL}/queue", timeout=5).json()
    dev = (s.get("devices") or [{}])[0]
    return {"up": True, "gpu": dev.get("name"), "vram_free_gb": round(dev.get("vram_free", 0) / 2**30, 1),
            "running": len(q.get("queue_running", [])), "pending": len(q.get("queue_pending", []))}


@mcp.tool()
def comfy_start(max_wait_s: int = 480) -> dict:
    """Launch Comfy Desktop if ComfyUI is down and wait until :8188 answers (boot takes 2-6 min)."""
    if _up():
        return {"up": True, "started": False}
    subprocess.Popen([COMFY_EXE], creationflags=subprocess.DETACHED_PROCESS)
    t0 = time.time()
    while time.time() - t0 < max_wait_s:
        time.sleep(5)
        if _up():
            return {"up": True, "started": True, "seconds": round(time.time() - t0)}
    return {"up": False, "started": True, "hint": "still booting; call comfy_status later"}


@mcp.tool()
def gen_image(prompt: str, model: str = "zimage", width: int = 1344, height: int = 768, seed: int = -1,
              ref_images: list[str] | None = None, init_image: str | None = None, denoise: float = 0.6,
              max_wait_s: int = 600) -> dict:
    """Generate one image locally (0 credit). Blocks until done (~20-90 s) and returns local file paths.

    model: "zimage" (default, fast photoreal), "krea2" (stylized/cinematic), "flux2" (FLUX.2 Klein 9B; the only
    one that accepts ref_images = local image paths for character/prop consistency).
    width/height: multiples of 16; 1344x768 landscape, 768x1344 portrait, 1024x1024 square.
    init_image + denoise (0.3-0.8): img2img from a local image (zimage/krea2 only).
    """
    _need_up()
    seed = _seed(seed)
    prefix = f"buzz/{model}"
    if model == "flux2":
        g = _flux2(prompt, [_upload(p) for p in (ref_images or [])], width, height, seed, prefix)
    elif model in ("zimage", "krea2"):
        g = (_zimage if model == "zimage" else _krea2)(prompt, width, height, seed, prefix)
        if init_image:
            g = _i2i(g, _upload(init_image), width, height, denoise)
    else:
        raise ValueError("model must be zimage | krea2 | flux2")
    res = _poll(_submit(g), max_wait_s)
    res.update(model=model, seed=seed)
    return res


@mcp.tool()
def gen_video(prompt: str, first_frame: str | None = None, last_frame: str | None = None, mid_frame: str | None = None,
              seconds: int = 5, portrait: bool = False, seed: int = -1) -> dict:
    """Queue one MiniMax H3 video locally (0 credit, 960x544 or 544x960, 24 fps). Returns a prompt_id immediately;
    then call wait_job(prompt_id) until status == "done" (expect several minutes per clip).

    first_frame/last_frame/mid_frame: local image paths (e.g. from gen_image). Strongly recommended: always give
    first_frame for a controllable shot. seconds: 5 (124 frames) or 6.5 (158 frames) - longer clips risk GPU crashes.
    """
    _need_up()
    length = 158 if seconds >= 6 else 124
    w, h = (544, 960) if portrait else (960, 544)
    up = {k: _upload(v) if v else None for k, v in (("first", first_frame), ("last", last_frame), ("mid", mid_frame))}
    pid = _submit(_h3(prompt, w, h, length, _seed(seed), "buzz/h3", up["first"], up["last"], up["mid"]))
    return {"status": "queued", "prompt_id": pid, "frames": length, "size": f"{w}x{h}"}


@mcp.tool()
def wait_job(prompt_id: str, max_wait_s: int = 540) -> dict:
    """Wait for a queued ComfyUI job. Returns status done (with local file paths) / error / running / queued."""
    _need_up()
    return _poll(prompt_id, max_wait_s)


@mcp.tool()
def cancel_job(prompt_id: str) -> dict:
    """Cancel a pending job, or interrupt it if it is the one currently running."""
    _need_up()
    q = requests.get(f"{URL}/queue", timeout=10).json()
    if any(item[1] == prompt_id for item in q.get("queue_running", [])):
        requests.post(f"{URL}/interrupt", timeout=10)
        return {"interrupted": prompt_id}
    requests.post(f"{URL}/queue", json={"delete": [prompt_id]}, timeout=10)
    return {"deleted": prompt_id}


if __name__ == "__main__":
    mcp.run()

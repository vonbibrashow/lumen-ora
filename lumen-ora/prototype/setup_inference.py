#!/usr/bin/env python3
"""
Lumen Ora — Inference Setup Script
Downloads llama.cpp Windows binary and a suitable GGUF model.

Usage:
    python setup_inference.py              # auto-detect disk space, pick model size
    python setup_inference.py --model 1.5b # force small model
    python setup_inference.py --model 7b   # force 7B model
    python setup_inference.py --llama-only # only download llama.cpp binary
    python setup_inference.py --model-only # only download the model
    python setup_inference.py --deps       # only install Python dependencies

This script:
  1. Checks available disk space on C:
  2. Downloads the latest llama.cpp Windows release from GitHub
  3. Extracts llama-server.exe (and required DLLs) to inference-bridge/llama-cpp/
  4. Downloads a GGUF model from HuggingFace sized to fit available space
  5. Installs Python dependencies for the inference bridge
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _c(code: str, t: str) -> str:
    return f"\033[{code}m{t}\033[0m"

def green(t: str) -> str:  return _c("32", t)
def red(t: str) -> str:    return _c("31", t)
def yellow(t: str) -> str: return _c("33", t)
def cyan(t: str) -> str:   return _c("36", t)
def bold(t: str) -> str:   return _c("1", t)

def info(msg: str) -> None:  print(f"  {cyan('INFO')} {msg}")
def ok(msg: str) -> None:    print(f"  {green('OK  ')} {msg}")
def warn(msg: str) -> None:  print(f"  {yellow('WARN')} {msg}")
def err(msg: str) -> None:   print(f"  {red('ERR ')} {msg}", file=sys.stderr)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROTOTYPE_DIR = Path(__file__).parent
LLAMA_DIR = PROTOTYPE_DIR / "inference-bridge" / "llama-cpp"
MODEL_DIR = PROTOTYPE_DIR / "inference-bridge" / "models"

# ---------------------------------------------------------------------------
# Disk space check
# ---------------------------------------------------------------------------

def get_free_gb_windows() -> float:
    """Get free GB on C: drive using ctypes (Windows)."""
    try:
        import ctypes
        free_bytes = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            "C:\\", None, None, ctypes.byref(free_bytes)
        )
        return free_bytes.value / (1024**3)
    except Exception:
        pass
    # Fallback via shutil
    try:
        usage = shutil.disk_usage("C:\\")
        return usage.free / (1024**3)
    except Exception:
        return 0.0


def get_free_gb() -> float:
    import platform
    if platform.system() == "Windows":
        return get_free_gb_windows()
    try:
        usage = shutil.disk_usage("/")
        return usage.free / (1024**3)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------

# Model catalog: (label, hf_repo, filename, size_gb, min_disk_gb)
# Using Qwen2.5-Instruct GGUF variants hosted on HuggingFace
MODELS = {
    "1.5b": {
        "label": "Qwen2.5-1.5B-Instruct Q4_K_M (~1.0 GB)",
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size_gb": 1.0,
        "min_free_gb": 3.0,
    },
    "3b": {
        "label": "Qwen2.5-3B-Instruct Q4_K_M (~1.9 GB)",
        "url": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf",
        "filename": "qwen2.5-3b-instruct-q4_k_m.gguf",
        "size_gb": 1.9,
        "min_free_gb": 5.0,
    },
    "7b": {
        "label": "Qwen2.5-7B-Instruct Q4_K_M (~4.7 GB)",
        "url": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "size_gb": 4.7,
        "min_free_gb": 10.0,
    },
}


def pick_model(free_gb: float) -> dict:
    """Auto-select model size based on available disk space."""
    if free_gb >= 20:
        return MODELS["7b"]
    elif free_gb >= 10:
        return MODELS["3b"]
    else:
        return MODELS["1.5b"]


# ---------------------------------------------------------------------------
# Progress download helper
# ---------------------------------------------------------------------------

class DownloadProgress:
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.last_pct = -1
        self.start_time = time.time()

    def __call__(self, block_num: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            return
        downloaded = block_num * block_size
        pct = min(100, int(downloaded * 100 / total_size))
        if pct != self.last_pct and pct % 5 == 0:
            elapsed = time.time() - self.start_time
            speed = downloaded / elapsed / (1024**2) if elapsed > 0 else 0
            done_mb = downloaded / (1024**2)
            total_mb = total_size / (1024**2)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            print(f"\r  [{bar}] {pct:3d}%  {done_mb:.0f}/{total_mb:.0f} MB  {speed:.1f} MB/s",
                  end="", flush=True)
            self.last_pct = pct
            if pct == 100:
                print()  # newline at 100%


def download_file(url: str, dest: Path, label: str) -> bool:
    """Download a file with progress reporting. Returns True on success."""
    info(f"Downloading {label}")
    info(f"  URL: {url}")
    info(f"  Destination: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    tmp_dest = dest.with_suffix(dest.suffix + ".part")

    try:
        # Try urllib first (no extra deps)
        urllib.request.urlretrieve(url, tmp_dest, reporthook=DownloadProgress(dest.name))
        tmp_dest.rename(dest)
        size_mb = dest.stat().st_size / (1024**2)
        ok(f"Downloaded {label} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        err(f"Download failed: {e}")
        if tmp_dest.exists():
            tmp_dest.unlink()
        return False


# ---------------------------------------------------------------------------
# GitHub API: find latest llama.cpp release asset
# ---------------------------------------------------------------------------

def get_latest_llama_asset() -> tuple[str, str] | None:
    """
    Query GitHub releases API for the latest llama.cpp Windows binary.
    Returns (download_url, asset_name) or None.

    Priority:
      1. win-avx2 (most common modern CPU)
      2. win-noavx2 (older CPUs)
      3. Any Windows zip
    """
    api_url = "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest"
    info("Querying GitHub API for latest llama.cpp release...")

    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "lumen-ora-setup/0.1",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            release = json.loads(r.read())
    except Exception as e:
        err(f"GitHub API request failed: {e}")
        return None

    tag = release.get("tag_name", "unknown")
    info(f"Latest release: {tag}")

    assets = release.get("assets", [])

    # Preference order: avx2 > noavx2 > any win zip
    def score(name: str) -> int:
        name = name.lower()
        if not name.endswith(".zip"):
            return -1
        if "win" not in name:
            return -1
        if "avx2" in name and "no" not in name:
            return 3
        if "noavx2" in name:
            return 2
        if "win" in name:
            return 1
        return 0

    ranked = sorted(assets, key=lambda a: score(a["name"]), reverse=True)
    for asset in ranked:
        if score(asset["name"]) > 0:
            info(f"Selected asset: {asset['name']} ({asset['size'] / (1024**2):.1f} MB)")
            return asset["browser_download_url"], asset["name"]

    err("No suitable Windows binary found in latest release. Assets available:")
    for a in assets[:10]:
        print(f"    {a['name']}")
    return None


# ---------------------------------------------------------------------------
# Extract llama-server from zip
# ---------------------------------------------------------------------------

def extract_llama_server(zip_path: Path, dest_dir: Path) -> bool:
    """
    Extract llama-server.exe (and required DLLs) from the release zip.
    Returns True on success.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            info(f"Zip contains {len(names)} files")

            # Extract everything — we need the DLLs too
            extracted = 0
            for name in names:
                # Only extract top-level files (executables + DLLs), skip subdirs
                # unless they are the bin/ folder
                basename = Path(name).name
                if not basename:
                    continue
                suffix = Path(basename).suffix.lower()
                if suffix in (".exe", ".dll", ".so", ""):
                    target = dest_dir / basename
                    with zf.open(name) as src, open(target, "wb") as dst:
                        dst.write(src.read())
                    extracted += 1

            info(f"Extracted {extracted} files to {dest_dir}")

        # Verify llama-server.exe is present
        server = dest_dir / "llama-server.exe"
        if server.exists():
            ok(f"llama-server.exe extracted ({server.stat().st_size / (1024**2):.1f} MB)")
            return True
        else:
            # Some releases name it 'server.exe' or put it in a subdirectory
            # Try a full extraction
            warn("llama-server.exe not found in top-level, trying full extraction...")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(dest_dir)

            # Search for it
            candidates = list(dest_dir.rglob("llama-server.exe")) + list(dest_dir.rglob("server.exe"))
            if candidates:
                # Move to expected location
                src = candidates[0]
                dst = dest_dir / "llama-server.exe"
                if src != dst:
                    src.rename(dst)
                ok(f"llama-server.exe found and placed at {dst}")
                return True
            else:
                err("Could not find llama-server.exe or server.exe in the zip")
                return False

    except Exception as e:
        err(f"Extraction failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Python dependency installation
# ---------------------------------------------------------------------------

def install_python_deps() -> bool:
    """Install Python dependencies for the inference bridge."""
    req_file = PROTOTYPE_DIR / "inference-bridge" / "requirements.txt"
    if not req_file.exists():
        err(f"requirements.txt not found: {req_file}")
        return False

    info("Installing Python dependencies...")
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(req_file), "--quiet"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            ok("Python dependencies installed")
            return True
        else:
            err(f"pip install failed:\n{result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        err("pip install timed out")
        return False
    except Exception as e:
        err(f"Failed to run pip: {e}")
        return False


# ---------------------------------------------------------------------------
# Build policy engine in WSL2 (if not already built)
# ---------------------------------------------------------------------------

def build_policy_engine() -> bool:
    """Build the policy engine in WSL2 using cargo build."""
    win_binary = PROTOTYPE_DIR / "policy-engine" / "target" / "debug" / "policy-engine.exe"
    if win_binary.exists():
        ok(f"Policy engine binary already exists: {win_binary}")
        return True

    # Check WSL2 binary
    wsl_path = str(PROTOTYPE_DIR / "policy-engine").replace("C:\\", "/mnt/c/").replace("\\", "/")
    try:
        r = subprocess.run(
            ["wsl", "-d", "Ubuntu-22.04", "--", "test", "-f",
             f"{wsl_path}/target/debug/policy-engine"],
            timeout=5, capture_output=True,
        )
        if r.returncode == 0:
            ok("Policy engine binary already built (WSL2)")
            return True
    except Exception:
        pass

    info("Building policy engine in WSL2 (first build takes ~2 min)...")
    try:
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu-22.04", "--",
             "bash", "-c", f"cd '{wsl_path}' && cargo build 2>&1"],
            timeout=300,
            capture_output=False,  # Show output directly
        )
        if result.returncode == 0:
            ok("Policy engine built successfully")
            return True
        else:
            err(f"cargo build failed (exit code {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        err("cargo build timed out after 5 minutes")
        return False
    except FileNotFoundError:
        err("WSL2 not found — install Ubuntu-22.04 from Microsoft Store")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download llama.cpp and a GGUF model for Lumen Ora",
    )
    parser.add_argument("--model", choices=["1.5b", "3b", "7b"],
                        help="Force a specific model size (default: auto based on disk space)")
    parser.add_argument("--llama-only", action="store_true",
                        help="Only download llama.cpp binary")
    parser.add_argument("--model-only", action="store_true",
                        help="Only download the model")
    parser.add_argument("--deps", action="store_true",
                        help="Only install Python dependencies")
    parser.add_argument("--build-policy", action="store_true",
                        help="Build the policy engine in WSL2")
    parser.add_argument("--skip-llama", action="store_true",
                        help="Skip llama.cpp download (already have it)")
    parser.add_argument("--skip-model", action="store_true",
                        help="Skip model download (already have one)")
    args = parser.parse_args()

    print(bold(cyan("""
╔══════════════════════════════════════════════════════════╗
║          Lumen Ora — Inference Setup                     ║
║  Downloads llama.cpp + GGUF model for first boot         ║
╚══════════════════════════════════════════════════════════╝""")))

    success = True

    # ── Deps only ─────────────────────────────────────────────────────────────
    if args.deps:
        return 0 if install_python_deps() else 1

    # ── Build policy engine ───────────────────────────────────────────────────
    if args.build_policy:
        return 0 if build_policy_engine() else 1

    # ── Disk space ────────────────────────────────────────────────────────────
    free_gb = get_free_gb()
    print(f"\n  {cyan('Disk space:')} {free_gb:.1f} GB free on C:")

    if free_gb < 2.0:
        err(f"Less than 2 GB free ({free_gb:.1f} GB). Free up disk space before proceeding.")
        return 1

    # ── llama.cpp binary ──────────────────────────────────────────────────────
    if not args.model_only and not args.skip_llama:
        print(f"\n{bold('Step 1: llama.cpp Windows binary')}")

        server_exe = LLAMA_DIR / "llama-server.exe"
        if server_exe.exists():
            size_mb = server_exe.stat().st_size / (1024**2)
            ok(f"llama-server.exe already present ({size_mb:.1f} MB) — skipping download")
        else:
            result = get_latest_llama_asset()
            if result is None:
                err("Could not find llama.cpp release. Check https://github.com/ggerganov/llama.cpp/releases")
                success = False
            else:
                dl_url, asset_name = result
                with tempfile.TemporaryDirectory() as td:
                    zip_path = Path(td) / asset_name
                    if download_file(dl_url, zip_path, "llama.cpp Windows binary"):
                        if not extract_llama_server(zip_path, LLAMA_DIR):
                            success = False
                    else:
                        success = False

    # ── Model download ────────────────────────────────────────────────────────
    if not args.llama_only and not args.skip_model:
        print(f"\n{bold('Step 2: GGUF model')}")

        # Check if a model already exists
        existing = list(MODEL_DIR.glob("*.gguf")) if MODEL_DIR.exists() else []
        if existing:
            for m in existing:
                size_gb = m.stat().st_size / (1024**3)
                ok(f"Model already present: {m.name} ({size_gb:.2f} GB) — skipping download")
        else:
            # Pick model
            if args.model:
                model_cfg = MODELS[args.model]
            else:
                model_cfg = pick_model(free_gb)

            info(f"Selected model: {model_cfg['label']}")

            if free_gb < model_cfg["min_free_gb"]:
                warn(f"Low disk space ({free_gb:.1f} GB free, need {model_cfg['min_free_gb']} GB). "
                     f"Proceeding anyway — the download may fail.")

            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            dest = MODEL_DIR / model_cfg["filename"]

            if not download_file(model_cfg["url"], dest, model_cfg["label"]):
                success = False
                err("\nIf the HuggingFace URL is blocked, try:")
                err("  1. Using a VPN or mirror")
                err("  2. Downloading manually from https://huggingface.co/Qwen")
                err(f"  3. Placing the .gguf file in: {MODEL_DIR}")

    # ── Python deps ───────────────────────────────────────────────────────────
    if not args.llama_only and not args.model_only:
        print(f"\n{bold('Step 3: Python dependencies')}")
        if not install_python_deps():
            success = False

    # ── Policy engine ─────────────────────────────────────────────────────────
    if not args.llama_only and not args.model_only:
        print(f"\n{bold('Step 4: Policy Engine (WSL2 build)')}")
        if not build_policy_engine():
            warn("Policy engine build failed — run manually:")
            warn("  wsl -d Ubuntu-22.04 -- bash -c 'cd /mnt/c/.../prototype/policy-engine && cargo build'")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    if success:
        print(green(bold("Setup complete!")))
        print()
        print("Next steps:")
        print(f"  1. Run the test suite:  python prototype/test_e2e.py")
        print(f"  2. Start the full stack:")
        print(f"     a. Policy engine:   wsl -d Ubuntu-22.04 -- "
              f"prototype/policy-engine/target/debug/policy-engine")
        models = list(MODEL_DIR.glob("*.gguf")) if MODEL_DIR.exists() else []
        if models:
            m = models[0]
            win_path = str(m)
            wsl_path = win_path.replace("C:\\", "/mnt/c/").replace("\\", "/")
            print(f"     b. llama-server:    inference-bridge/llama-cpp/llama-server.exe "
                  f"--model {win_path} --port 8080")
            print(f"     c. Inference bridge: python inference-bridge/bridge.py")
        print(f"  3. Full e2e test:       python prototype/test_e2e.py --all")
    else:
        print(red(bold("Setup encountered errors — see messages above.")))

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

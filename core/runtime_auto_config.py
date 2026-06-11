"""Automatic ONNX Runtime backend selection for Spectro on Windows."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import toml

ONNX_VARIANTS = [
    "onnxruntime",
    "onnxruntime-gpu",
    "onnxruntime-directml",
    "onnxruntime-openvino",
]

CONFIG_PATH = Path("cfg/general_config.toml")


def _run(command, check=False, timeout=60):
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
        timeout=timeout,
    )


def _pip(args, check=True):
    command = [sys.executable, "-m", "pip", *args]
    print(" ".join(command))
    return _run(command, check=check, timeout=300)


def _installed_providers():
    # Query providers in a child process so pip reinstall results are not hidden by Python import cache.
    code = (
        "import json\n"
        "try:\n"
        " import onnxruntime as ort\n"
        " print(json.dumps(list(ort.get_available_providers())))\n"
        "except Exception:\n"
        " print(json.dumps([]))\n"
    )
    try:
        result = _run([sys.executable, "-c", code], timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            import json
            return list(json.loads(result.stdout.strip().splitlines()[-1]))
    except Exception:
        pass
    return []


def _detect_gpu():
    try:
        result = _run(
            ["nvidia-smi", "--query-gpu=name,compute_cap", "--format=csv,noheader,nounits"],
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            first = result.stdout.strip().splitlines()[0]
            parts = [part.strip() for part in first.split(",")]
            name = parts[0] if parts else "NVIDIA GPU"
            compute_cap = 0.0
            if len(parts) > 1:
                try:
                    compute_cap = float(parts[1])
                except ValueError:
                    compute_cap = 0.0
            return "nvidia", name, compute_cap
    except Exception:
        pass

    try:
        result = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
            ],
            timeout=10,
        )
        names = result.stdout.strip()
        lowered = names.lower()
        if "amd" in lowered or "radeon" in lowered:
            return "amd", names.splitlines()[0] if names else "AMD Radeon", 0.0
        if "intel" in lowered:
            return "intel", names.splitlines()[0] if names else "Intel GPU", 0.0
    except Exception:
        pass

    return "cpu", "CPU", 0.0


def _cuda_dependency_ready():
    try:
        from core.cuda_runtime_paths import add_cuda_dll_directories, has_cuda_dependency_dlls
        add_cuda_dll_directories()
        ready, missing = has_cuda_dependency_dlls()
        return ready, missing
    except Exception:
        return False, ["cublasLt64_12.dll", "cudnn64_9.dll"]


def _desired_backend():
    gpu_kind, gpu_name, compute_cap = _detect_gpu()

    if gpu_kind == "nvidia":
        cuda_ready, missing = _cuda_dependency_ready()
        if cuda_ready:
            return {
                "backend": "cuda",
                "package": "onnxruntime-gpu",
                "provider": "CUDAExecutionProvider",
                "gpu_name": gpu_name,
                "reason": "NVIDIA GPU with CUDA/cuDNN runtime found.",
            }
        return {
            "backend": "directml",
            "package": "onnxruntime-directml",
            "provider": "DmlExecutionProvider",
            "gpu_name": gpu_name,
            "reason": "NVIDIA GPU found, but CUDA/cuDNN DLLs are missing. DirectML is the safest automatic backend.",
            "missing": missing,
        }

    if gpu_kind in ("amd", "intel"):
        return {
            "backend": "directml",
            "package": "onnxruntime-directml",
            "provider": "DmlExecutionProvider",
            "gpu_name": gpu_name,
            "reason": f"{gpu_kind.upper()} GPU found. DirectML is recommended on Windows.",
        }

    return {
        "backend": "cpu",
        "package": "onnxruntime",
        "provider": "CPUExecutionProvider",
        "gpu_name": gpu_name,
        "reason": "No supported GPU was detected.",
    }


def _install_onnx_variant(package):
    _pip(["uninstall", "-y", *ONNX_VARIANTS], check=False)
    result = _pip(["install", "--upgrade", package], check=False)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        print(
            "Auto runtime: could not switch ONNX Runtime automatically. "
            "Close Spectro/PyCharm processes that may use onnxruntime DLLs and run again."
        )


def _write_backend_to_config(backend):
    if not CONFIG_PATH.exists():
        return
    config = toml.load(str(CONFIG_PATH))
    current = str(config.get("cpu_or_gpu", "auto")).strip().lower()
    if current != backend:
        config["cpu_or_gpu"] = backend
        CONFIG_PATH.write_text(toml.dumps(config), encoding="utf-8")


def configure_runtime_auto(force=False):
    """Install and select the best ONNX backend for the current Windows device."""
    if os.environ.get("SPECTRO_SKIP_RUNTIME_AUTO", "").strip().lower() in ("1", "true", "yes"):
        return

    desired = _desired_backend()
    providers = _installed_providers()
    current_has_provider = desired["provider"] in providers

    # CPU package can expose only CPUExecutionProvider. If that is already available, no install is needed.
    if not current_has_provider:
        print(
            "Auto runtime: switching ONNX Runtime to "
            f"{desired['backend']} for {desired['gpu_name']}. {desired['reason']}"
        )
        if desired.get("missing"):
            print("Auto runtime: missing CUDA DLLs: " + ", ".join(desired["missing"]))
        _install_onnx_variant(desired["package"])
        providers = _installed_providers()

    if desired["provider"] in providers:
        _write_backend_to_config(desired["backend"])
        print(
            "Auto runtime: selected "
            f"{desired['backend']} ({desired['provider']}). Providers: {', '.join(providers)}"
        )
    else:
        _write_backend_to_config("cpu")
        print(
            "Auto runtime: requested provider is still unavailable. "
            f"Falling back to CPU. Providers: {', '.join(providers) or 'none'}"
        )


if __name__ == "__main__":
    configure_runtime_auto(force=True)

import os
import subprocess
import sys
from pathlib import Path


def bundle_root() -> str:
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return os.path.abspath(str(meipass))
    if getattr(sys, "frozen", False):
        exe_parent = str(Path(sys.executable).resolve().parent)
        internal_dir = os.path.join(exe_parent, "_internal")
        if os.path.isdir(internal_dir):
            return internal_dir
    return str(Path(__file__).resolve().parents[1])


def workspace_root() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve().parent)
    return str(Path(__file__).resolve().parents[1])



def join_root(*parts: str) -> str:
    return os.path.join(workspace_root(), *parts)


def asset_path(*parts: str) -> str:
    return first_existing_path(
        join_root("assets", *parts),
        os.path.join(bundle_root(), "assets", *parts),
    )


def app_path(*parts: str) -> str:
    return first_existing_path(
        join_root("app", *parts),
        os.path.join(bundle_root(), "app", *parts),
    )


def first_existing_path(*candidates: str) -> str:
    for candidate in candidates:
        path = str(candidate or "").strip()
        if path and os.path.exists(path):
            return path
    return str(candidates[0] if candidates else "")


def bin_path(*parts: str) -> str:
    primary = os.path.join(bundle_root(), "bin", *parts)
    workspace_fallback = join_root("bin", *parts)
    cwd_fallback = os.path.join(os.getcwd(), "bin", *parts)
    exe_fallback = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "bin", *parts)
    return first_existing_path(primary, workspace_fallback, cwd_fallback, exe_fallback)


def models_path(*parts: str) -> str:
    writable = join_root("models", *parts)
    bundled = os.path.join(bundle_root(), "models", *parts)

    # Packaged builds create writable placeholder directories so optional
    # resources can be downloaded after installation.  For SenseVoice that
    # placeholder must not shadow a complete bundled model under _internal.
    # Keep the normal writable-first behavior for every other model family.
    if parts and str(parts[0]).strip().lower() == "sensevoice":
        required = ("model.int8.onnx", "tokens.txt")
        for candidate in (writable, bundled):
            if all(os.path.isfile(os.path.join(candidate, name)) for name in required):
                return candidate

    return first_existing_path(writable, bundled)


def writable_models_path(*parts: str) -> str:
    """Return deterministic writable destination for downloaded/created models in workspace.

    Always targets workspace_root()/models, never bundle_root().
    """
    return join_root("models", *parts)


def temp_path(*parts: str) -> str:
    return join_root("temp", *parts)


def output_path(*parts: str) -> str:
    return join_root("output", *parts)


def logs_path(*parts: str) -> str:
    return join_root("logs", *parts)


def render_jobs_path(*parts: str) -> str:
    return join_root("render_jobs", *parts)


def raw_tts_path(*parts: str) -> str:
    return join_root("raw_tts", *parts)



def subprocess_hidden_kwargs() -> dict:
    """Return Windows flags that keep console child processes invisible.

    The GUI build has no console of its own.  Without these flags, console
    programs such as FFmpeg/FFprobe create a temporary console window every
    time they start, which causes visible flashes and adds process-launch
    overhead.  The debug console build remains unaffected.
    """
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def subprocess_text_kwargs() -> dict:
    """Return safe options for text captured from external Windows tools.

    ``subprocess`` otherwise decodes captured output using the current Windows
    ANSI code page (often reported by Python as ``charmap``).  FFmpeg and
    FFprobe include the input path in diagnostics, so a Unicode file or user
    path can make that implicit decode fail before the actual workflow starts.
    Our bundled tools emit UTF-8 diagnostics; replacement is intentional for
    diagnostic text so an unexpected third-party byte never aborts a job.
    """
    return {
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        **subprocess_hidden_kwargs(),
    }


def ensure_runtime_directories(base_dir: str | None = None) -> list[str]:
    """Ensure all required writable directories exist in the workspace.

    Creates: output, temp, render_jobs, raw_tts, models, logs
    under base_dir (defaults to workspace_root()).

    Performs a real write probe check in each directory and fails fast
    with a descriptive PermissionError if the workspace is not writable.
    Returns the list of absolute paths ensured.
    """
    root = base_dir or workspace_root()
    required_dirs = [
        "output",
        "temp",
        "render_jobs",
        "raw_tts",
        "models",
        "logs",
    ]
    created = []
    for rel_path in required_dirs:
        full_path = os.path.join(root, rel_path)
        try:
            os.makedirs(full_path, exist_ok=True)
        except (OSError, PermissionError) as exc:
            raise PermissionError(
                f"Không thể tạo thư mục làm việc (workspace not writable): '{full_path}'. "
                f"Vui lòng kiểm tra quyền ghi tại thư mục ứng dụng."
            ) from exc

        # Real write probe: kiểm tra khả năng ghi thực tế
        probe_name = f".write_probe_{os.getpid()}_{abs(hash(rel_path))}.tmp"
        probe_path = os.path.join(full_path, probe_name)
        try:
            with open(probe_path, "wb") as pf:
                pf.write(b"probe")
        except (OSError, PermissionError) as exc:
            raise PermissionError(
                f"Thư mục làm việc không có quyền ghi thực tế (write probe failed): '{full_path}'. "
                f"Vui lòng chạy ứng dụng tại thư mục có quyền ghi."
            ) from exc
        finally:
            if os.path.isfile(probe_path):
                try:
                    os.remove(probe_path)
                except OSError:
                    pass

        created.append(os.path.abspath(full_path))
    return created



def resolve_ffmpeg_path() -> str:
    """Resolve FFmpeg binary via 3-state resolution cascade:
    1. Frozen bundle (_internal/bin/ffmpeg/ffmpeg.exe or bundle_root()/bin/ffmpeg/...)
    2. Workspace / bundled local path (workspace_root()/bin/ffmpeg/ffmpeg.exe)
    3. System PATH fallback (shutil.which('ffmpeg.exe') or shutil.which('ffmpeg'))

    Raises FileNotFoundError if none are found.
    """
    import shutil

    # State 1: Frozen bundle / primary binary path
    bundled = bin_path("ffmpeg", "ffmpeg.exe")
    if bundled and os.path.isfile(bundled):
        return os.path.abspath(bundled)

    bundled_flat = bin_path("ffmpeg.exe")
    if bundled_flat and os.path.isfile(bundled_flat):
        return os.path.abspath(bundled_flat)

    # State 2: Workspace local path
    workspace_candidates = [
        join_root("bin", "ffmpeg", "ffmpeg.exe"),
        join_root("bin", "ffmpeg.exe"),
    ]
    for cand in workspace_candidates:
        if os.path.isfile(cand):
            return os.path.abspath(cand)

    # State 3: System PATH fallback
    sys_ffmpeg = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
    if sys_ffmpeg:
        return os.path.abspath(sys_ffmpeg)

    raise FileNotFoundError(
        "Không tìm thấy file thực thi FFmpeg tại bundle, workspace, hoặc biến môi trường PATH."
    )


def resolve_vieneu_runtime(daemon_url: str = "http://localhost:53239", timeout: float = 0.5) -> dict:
    """Resolve VieNeu TTS runtime using resolution cascade:
    1. HTTP Daemon (daemon_url/ping)
    2. Environment variable VIENEU_PYTHON
    3. Local/bundled virtualenv (./vieneu_env/... or ./.vieneu_venv/...)
    4. Safe fallback with descriptive error (does not crash).
    """
    import urllib.request
    import urllib.error

    # 1. HTTP Daemon
    try:
        req = urllib.request.Request(f"{daemon_url.rstrip('/')}/ping", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return {
                    "available": True,
                    "type": "daemon",
                    "target": daemon_url,
                    "error": None,
                }
    except Exception:
        pass

    # 2. VIENEU_PYTHON environment variable
    env_python = os.environ.get("VIENEU_PYTHON", "").strip()
    if env_python and os.path.isfile(env_python):
        return {
            "available": True,
            "type": "external_python",
            "target": os.path.abspath(env_python),
            "error": None,
        }

    # 3. Local / bundled virtualenv
    local_candidates = [
        join_root("vieneu_env", "Scripts", "python.exe"),
        join_root(".vieneu_venv", "Scripts", "python.exe"),
        join_root("vieneu_env", "bin", "python"),
        join_root(".vieneu_venv", "bin", "python"),
    ]
    for cand in local_candidates:
        if os.path.isfile(cand):
            return {
                "available": True,
                "type": "local_env",
                "target": os.path.abspath(cand),
                "error": None,
            }

    # 4. Fallback with descriptive message
    return {
        "available": False,
        "type": "none",
        "target": None,
        "error": "VieNeu TTS runtime chưa sẵn sàng. Hãy khởi động VieNeu Daemon tại port 53239 hoặc cấu hình biến môi trường VIENEU_PYTHON.",
    }


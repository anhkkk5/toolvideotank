"""VieNeu TTS Backend Implementation.

Implements TTSBackend interface according to Step 5.2.2.2:
- Supports strictly 'vieneu_cogaihoatbat' and 'vieneu_thanhnientutin'.
- Raises ValueError on invalid or unsupported voice_id (strictly NO silent voice fallback).
- Calls persistent daemon or CLI fallback with the EXACT same voice & model.
- Generates raw WAV, verifies existence & validity, and returns raw measured duration.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

from app.services.tts_backend import TTSBackend, measure_wav_duration

# Default paths and port
DEFAULT_VIENEU_PORT = 53239
DEFAULT_VIENEU_PYTHON = r"D:\VieNeu-TTS\.venv\Scripts\python.exe"
DEFAULT_MODEL_COGAI = r"D:\VieNeu-TTS\custom_models\cogai\cogai_merged_model\merged"
DEFAULT_MODEL_THANHNIEN = r"D:\VieNeu-TTS\custom_models\thanhnien\merged"


class VieNeuBackend(TTSBackend):
    """VieNeu-TTS Adapter tuân thủ hợp đồng TTSBackend."""

    # Bản đồ ánh xạ cấu hình cứng cho VieNeu (bất biến)
    SUPPORTED_VOICES: dict[str, dict[str, str]] = {
        "vieneu_cogaihoatbat": {
            "name": "Cô gái hoạt bát",
            "model_env": "VIENEU_MODEL_COGAI",
            "default_path": DEFAULT_MODEL_COGAI,
        },
        "vieneu_thanhnientutin": {
            "name": "Thanh niên tự tin",
            "model_env": "VIENEU_MODEL_THANHNIEN",
            "default_path": DEFAULT_MODEL_THANHNIEN,
        },
    }

    def __init__(
        self,
        port: int = DEFAULT_VIENEU_PORT,
        python_path: str | None = None,
        worker_path: str | None = None,
    ):
        self.port = int(os.getenv("VIENEU_SERVER_PORT", str(port)) or str(port))
        if not python_path:
            env_py = os.getenv("VIENEU_PYTHON", "").strip()
            if env_py and os.path.isfile(env_py):
                self.python_path = env_py
            else:
                # Kiểm tra thư mục models/vieneu/ nếu người dùng đã tải gói về
                cur_dir = os.path.dirname(os.path.abspath(__file__))
                proj_root = os.path.dirname(os.path.dirname(cur_dir))
                candidates = [
                    os.path.join(proj_root, "models", "vieneu", ".venv", "Scripts", "python.exe"),
                    os.path.join(proj_root, "models", "vieneu", "python.exe"),
                ]
                found_py = next((c for c in candidates if os.path.isfile(c)), None)
                self.python_path = found_py or DEFAULT_VIENEU_PYTHON
        else:
            self.python_path = python_path

        if not worker_path:
            # Tìm vieneu_worker.py trong thư mục app
            cur_dir = os.path.dirname(os.path.abspath(__file__))
            app_dir = os.path.dirname(cur_dir)
            self.worker_path = os.path.join(app_dir, "vieneu_worker.py")
        else:
            self.worker_path = worker_path

    def _resolve_model(self, voice_id: str) -> tuple[str, str]:
        """Xác định model path và voice speaker name từ voice_id.
        
        Ném ValueError ngay nếu voice_id không hợp lệ (NO SILENT FALLBACK).
        """
        v_id = str(voice_id or "").strip().lower()
        if v_id not in self.SUPPORTED_VOICES:
            raise ValueError(
                f"Invalid or unsupported VieNeu voice_id: '{voice_id}'. "
                f"Supported voices: {list(self.SUPPORTED_VOICES.keys())}"
            )

        info = self.SUPPORTED_VOICES[v_id]
        voice_name = info["name"]
        env_key = info["model_env"]
        default_path = info["default_path"]

        model_path = os.getenv(env_key, "").strip()
        if not model_path and env_key == "VIENEU_MODEL_COGAI":
            model_path = os.getenv("VIENEU_MODEL_DIR", "").strip()
        if not model_path:
            cur_dir = os.path.dirname(os.path.abspath(__file__))
            proj_root = os.path.dirname(os.path.dirname(cur_dir))
            sub = "cogai/cogai_merged_model/merged" if "cogai" in v_id else "thanhnien/merged"
            local_model = os.path.join(proj_root, "models", "vieneu", "custom_models", sub)
            if os.path.isdir(local_model):
                model_path = local_model
            else:
                model_path = default_path

        if not os.path.isdir(model_path):
            raise RuntimeError(
                f"VieNeu model directory not found for '{v_id}': {model_path}. "
                "Vui lòng vào Quản lý tài nguyên để tải gói VieNeu AI hoặc kiểm tra lại đường dẫn."
            )

        return model_path, voice_name

    @classmethod
    def _is_server_alive(cls, port: int) -> bool:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/ping", method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def ensure_daemon_running(self) -> bool:
        """Đảm bảo persistent daemon server đang chạy để tái sử dụng model trong RAM,
        giúp tốc độ lồng tiếng tăng gấp 20-50 lần (từ 20 phút xuống còn ~1 phút)."""
        if self._is_server_alive(self.port):
            return True

        if not self.python_path or not os.path.isfile(self.python_path):
            return False
        if not self.worker_path or not os.path.isfile(self.worker_path):
            return False

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        cmd = [
            self.python_path,
            "-X", "utf8",
            self.worker_path,
            "--server",
            "--port", str(self.port),
        ]
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            # Chờ tối đa 6 giây cho server khởi động
            import time
            for _ in range(30):
                time.sleep(0.2)
                if self._is_server_alive(self.port):
                    print(f"[VieNeuBackend] Persistent daemon server started successfully at port {self.port}.")
                    return True
        except Exception as e:
            print(f"[VieNeuBackend] Auto-start daemon error: {e}")

        return False

    def _call_daemon(self, text: str, voice_name: str, model_path: str, output_path: str) -> bool:
        """Thử gọi daemon nội bộ qua HTTP POST."""
        req_data = json.dumps({
            "text": text,
            "model": model_path,
            "voice": voice_name,
            "output": output_path,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/synthesize",
            data=req_data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                if resp.status == 200:
                    resp_json = json.loads(resp.read().decode("utf-8"))
                    return bool(resp_json.get("ok"))
        except Exception:
            return False
        return False

    def _call_cli(self, text: str, voice_name: str, model_path: str, output_path: str) -> None:
        """Backend execution fallback qua CLI vieneu_worker.py (vẫn cùng model và voice)."""
        if not self.python_path or not os.path.isfile(self.python_path):
            raise RuntimeError(f"VieNeu Python executable not found: {self.python_path}")
        if not self.worker_path or not os.path.isfile(self.worker_path):
            raise RuntimeError(f"VieNeu worker script not found: {self.worker_path}")

        cmd = [
            self.python_path,
            "-X",
            "utf8",
            self.worker_path,
            "--model",
            model_path,
            "--output",
            output_path,
            "--voice",
            voice_name,
        ]

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.run(
            cmd,
            input=text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            creationflags=creationflags,
        )

        if proc.returncode != 0:
            err_msg = proc.stderr or proc.stdout or f"Process exited with code {proc.returncode}"
            raise RuntimeError(f"VieNeu CLI synthesis failed:\n{err_msg}")

    def synthesize(self, text: str, voice_id: str, output_path: str) -> float:
        """Sinh âm thanh thô ra output_path và trả về thời lượng thực tế (giây).
        
        Quy trình chuẩn:
        1. Validate voice_id -> ném ValueError nếu không hợp lệ.
        2. Resolve model & voice_name tương ứng.
        3. Thực hiện sinh âm thanh qua daemon (hoặc CLI fallback).
        4. Kiểm tra file output_path tồn tại và có kích thước hợp lệ.
        5. Đo thời lượng thực tế từ header WAV bằng measure_wav_duration().
        6. Trả về duration thô (không can thiệp tốc độ).
        """
        clean_text = str(text or "").strip()
        if not clean_text:
            raise ValueError("TTS text cannot be empty.")

        # 1 & 2. Validate voice_id và resolve model
        model_path, voice_name = self._resolve_model(voice_id)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        # Xóa file cũ nếu đã tồn tại trước khi sinh để tránh nhận nhầm file rác cũ
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass

        # 3. Thực thi sinh âm thanh (tự động khởi động persistent daemon để sinh siêu tốc)
        self.ensure_daemon_running()
        success = self._call_daemon(clean_text, voice_name, model_path, output_path)
        if not success or not os.path.isfile(output_path):
            # Backend execution fallback sang CLI (giữ nguyên voice & model)
            self._call_cli(clean_text, voice_name, model_path, output_path)

        # 4. Kiểm tra file output_path
        if not os.path.isfile(output_path) or os.path.getsize(output_path) < 100:
            raise RuntimeError(
                f"VieNeu output WAV was not created or is empty: {output_path}"
            )

        # 5. Đo thời lượng thực tế
        duration = measure_wav_duration(output_path)
        if duration <= 0.0:
            raise RuntimeError(
                f"Failed to read valid duration from VieNeu WAV: {output_path}"
            )

        return duration

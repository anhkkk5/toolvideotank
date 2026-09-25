"""Unified TTS Backend supporting VieNeu, Piper, Edge, and other catalog voices."""

from __future__ import annotations

import os
import sys
from app.services.tts_backend import TTSBackend, measure_wav_duration
from app.services.vieneu_backend import VieNeuBackend


class UnifiedTTSBackend(TTSBackend):
    """Universal TTS Backend that routes requests to VieNeu, Piper, or Edge engines.
    
    Standardized to implement TTSBackend interface according to Step 5.1 & 5.2.1.
    """

    def __init__(self, vieneu_backend: TTSBackend | None = None):
        self.vieneu_backend = vieneu_backend or VieNeuBackend()

    def synthesize(self, text: str, voice_id: str, output_path: str) -> float:
        clean_text = str(text or "").strip()
        v_id = str(voice_id or "").strip()
        if not clean_text:
            return 0.0
        if not v_id:
            raise ValueError("Voice ID cannot be empty")

        # 1. Ưu tiên VieNeuBackend cho các giọng VieNeu chính thức
        if hasattr(self.vieneu_backend, "SUPPORTED_VOICES") and v_id in self.vieneu_backend.SUPPORTED_VOICES:
            try:
                return self.vieneu_backend.synthesize(clean_text, v_id, output_path)
            except Exception:
                # Nếu worker server VieNeu chưa sẵn sàng, tiếp tục thử qua tts_processor
                pass

        # 2. Điều phối qua synthesize_text_to_wav_16k_mono (Piper, Edge, Catalog)
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)

        try:
            from tts_processor import synthesize_text_to_wav_16k_mono
            synthesize_text_to_wav_16k_mono(
                text=clean_text,
                wav_path=output_path,
                voice=v_id,
            )
        except Exception as exc:
            raise RuntimeError(f"TTS synthesis failed for voice '{v_id}': {exc}") from exc

        dur = measure_wav_duration(output_path)
        if dur <= 0:
            raise RuntimeError(f"Generated WAV file is empty or invalid: {output_path}")
        return dur

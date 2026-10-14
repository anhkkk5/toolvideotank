"""Regression Test Suite for Step 5.2.2.7: Strict Skip Rules Enforcement.

Validates that VoiceoverService terminates early with status="skipped"
and ABSOLUTELY NEVER calls Backend.synthesize() under any skip conditions:
1. translated_text is empty ("")
2. is_noise is True
3. skip_tts is True
4. voice_id is empty ("")
5. Combination: is_noise=True and skip_tts=True

Assertions:
- status == "skipped"
- audio_path == ""
- duration == 0.0
- Backend.synthesize() is NEVER CALLED (call_count == 0)
- NO audio WAV file created on disk
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

WORKSPACE_DIR = Path(__file__).resolve().parent
APP_DIR = WORKSPACE_DIR / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.voiceover_service import VoiceoverService
from services.tts_backend import TTSBackend


class AssertNeverCalledBackend(TTSBackend):
    """Spy Backend kiểm chứng: Nếu synthesize() bị gọi thì ném AssertionError ngay lập tức."""
    def __init__(self):
        self.call_count = 0

    def synthesize(self, text: str, voice_id: str, output_path: str) -> float:
        self.call_count += 1
        raise AssertionError(
            f"VIOLATION! Backend.synthesize() was called with text='{text}', voice_id='{voice_id}'!"
        )


def run_skip_rules_tests():
    print("=" * 65)
    print("      TEST 5.2.2.7: STRICT SKIP RULES & ZERO BACKEND INVOCATION")
    print("=" * 65)

    raw_dir = os.path.join(str(WORKSPACE_DIR), "raw_tts")
    os.makedirs(raw_dir, exist_ok=True)

    spy_backend = AssertNeverCalledBackend()
    service = VoiceoverService(backend=spy_backend, raw_output_dir=raw_dir)

    skip_cases = [
        (
            "Empty translated text",
            {"segment_id": 201, "translated_text": "", "voice_id": "vieneu_thanhnientutin", "is_noise": False, "skip_tts": False},
        ),
        (
            "Whitespace-only translated text",
            {"segment_id": 202, "translated_text": "   \n\t  ", "voice_id": "vieneu_thanhnientutin", "is_noise": False, "skip_tts": False},
        ),
        (
            "is_noise=True (Disclaimer / OCR noise)",
            {"segment_id": 203, "translated_text": "Kịch bản chỉ mang tính hư cấu", "voice_id": "vieneu_thanhnientutin", "is_noise": True, "skip_tts": False},
        ),
        (
            "skip_tts=True (Music / Non-speech segment)",
            {"segment_id": 204, "translated_text": "[Tiếng đàn piano]", "voice_id": "vieneu_cogaihoatbat", "is_noise": False, "skip_tts": True},
        ),
        (
            "Empty voice_id (Unassigned / Unknown gender)",
            {"segment_id": 205, "translated_text": "Câu nói không rõ nhân vật", "voice_id": "", "is_noise": False, "skip_tts": False},
        ),
        (
            "Combined noise and empty voice",
            {"segment_id": 206, "translated_text": "", "voice_id": "", "is_noise": True, "skip_tts": True},
        ),
    ]

    all_passed = True

    for idx, (name, kwargs) in enumerate(skip_cases, start=1):
        target_wav = os.path.join(raw_dir, f"test_skip_{kwargs['segment_id']}.wav")
        if os.path.isfile(target_wav):
            os.remove(target_wav)

        print(f"\n[Case {idx}] {name}")
        print(f"  Inputs: text='{kwargs['translated_text'][:30]}', voice_id='{kwargs['voice_id']}', is_noise={kwargs['is_noise']}, skip_tts={kwargs['skip_tts']}")

        call_count_before = spy_backend.call_count
        res = service.generate(**kwargs, output_path=target_wav)

        print(f"  -> Result status: {res.status}")
        print(f"  -> Backend calls: {spy_backend.call_count - call_count_before}")

        errors = []
        if res.status != "skipped":
            errors.append(f"Expected status 'skipped', got '{res.status}'")
        if spy_backend.call_count != call_count_before:
            errors.append(f"Backend synthesize was called {spy_backend.call_count - call_count_before} times!")
        if res.audio_path != "":
            errors.append(f"audio_path must be empty, got '{res.audio_path}'")
        if res.duration != 0.0:
            errors.append(f"duration must be 0.0, got {res.duration}")
        if os.path.isfile(target_wav):
            errors.append(f"Audio file was wrongly created at: {target_wav}")

        if errors:
            print("  [FAIL] Errors detected:")
            for err in errors:
                print(f"    - {err}")
            all_passed = False
        else:
            print("  [PASS] Successfully skipped at service gateway without calling backend.")

    print("\n" + "-" * 65)
    print(f"Total Backend Synthesize Calls across all cases: {spy_backend.call_count}")
    if all_passed and spy_backend.call_count == 0:
        print("RESULT: ALL 6/6 SKIP CASES PASSED! ZERO BACKEND INVOCATION.")
    else:
        print("RESULT: SOME SKIP CASES FAILED.")
    print("=" * 65)
    return all_passed and spy_backend.call_count == 0


if __name__ == "__main__":
    ok = run_skip_rules_tests()
    if not ok:
        sys.exit(1)

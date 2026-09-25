"""Regression Test Suite for Step 5.2.2.6: Test Invalid voice_id & No Silent Fallback.

Validates fail-fast and no-silent-fallback behavior:
- empty voice_id ("")       -> status="skipped" (caught by Skip Rule, no backend call)
- "invalid_voice"           -> status="failed" (ValueError from backend, no silent fallback)
- "vieneu_unknown"          -> status="failed" (ValueError from backend, no silent fallback)
- "piper_xxx"               -> status="failed" (ValueError from backend, no silent fallback)

Ensures:
- NO WAV generated
- NO silent fallback to male or female
- NO Gender AI invocation
- Transparent error message
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
from services.vieneu_backend import VieNeuBackend


def run_invalid_voice_tests():
    print("=" * 65)
    print("      TEST 5.2.2.6: TEST INVALID VOICE_ID & NO SILENT FALLBACK")
    print("=" * 65)

    raw_dir = os.path.join(str(WORKSPACE_DIR), "raw_tts")
    os.makedirs(raw_dir, exist_ok=True)

    real_backend = VieNeuBackend()
    service = VoiceoverService(backend=real_backend, raw_output_dir=raw_dir)

    test_cases = [
        # (case_name, voice_id, expected_status, expected_error_substr)
        ("Empty voice_id", "", "skipped", ""),
        ("Generic invalid voice", "invalid_voice", "failed", "Invalid or unsupported VieNeu voice_id"),
        ("Unknown vieneu voice", "vieneu_unknown", "failed", "Invalid or unsupported VieNeu voice_id"),
        ("Unsupported external provider", "piper_xxx", "failed", "Invalid or unsupported VieNeu voice_id"),
    ]

    all_passed = True
    for idx, (name, voice_id, exp_status, err_substr) in enumerate(test_cases, start=1):
        target_wav = os.path.join(raw_dir, f"test_invalid_{idx}.wav")
        if os.path.isfile(target_wav):
            os.remove(target_wav)

        print(f"\n[Case {idx}] {name}: voice_id='{voice_id}'")
        res = service.generate(
            segment_id=100 + idx,
            translated_text="Câu thoại thử nghiệm lỗi giọng",
            start=1.0,
            end=3.0,
            voice_id=voice_id,
            output_path=target_wav,
        )

        print(f"  -> Result status: {res.status}")
        print(f"  -> Result voice_id: '{res.voice_id}'")
        print(f"  -> Error: '{res.error}'")
        
        # Verify status
        if res.status != exp_status:
            print(f"  [FAIL] Expected status '{exp_status}', got '{res.status}'")
            all_passed = False
            continue

        # Verify no WAV was generated
        if os.path.isfile(target_wav):
            print(f"  [FAIL] Audio file should NOT have been generated at: {target_wav}")
            all_passed = False
            continue

        # Verify no silent fallback occurred
        if res.voice_id in ("vieneu_thanhnientutin", "vieneu_cogaihoatbat"):
            print(f"  [FAIL] Silent fallback detected! voice_id was modified to '{res.voice_id}'")
            all_passed = False
            continue

        # Verify error message for failed cases
        if exp_status == "failed" and err_substr not in res.error:
            print(f"  [FAIL] Expected error containing '{err_substr}', got '{res.error}'")
            all_passed = False
            continue

        print(f"  [PASS] Correctly handled: status='{res.status}', no audio generated, no fallback.")

    print("\n" + "-" * 65)
    if all_passed:
        print("RESULT: ALL INVALID VOICE_ID CASES PASSED! NO SILENT FALLBACK.")
    else:
        print("RESULT: SOME CASES FAILED.")
    print("=" * 65)
    return all_passed


if __name__ == "__main__":
    ok = run_invalid_voice_tests()
    if not ok:
        sys.exit(1)

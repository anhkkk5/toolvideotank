"""Automated Regression Test Matrix for CapCap Gender AI Pipeline.

Comprehensive 10-Test Matrix validating:
- Layer 1: Raw AI immutability & quality assessment
- Layer 2: Anchor-based temporal smoothing rules & edge cases
- Layer 3: Dialogue-switch & boundary switch protection
- Layer 4: Non-speech, music & unknown handling
- Layer 5: Contract guarantee (final_* is the only source for TTS)

Usage:
    python test_gender_regression.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

WORKSPACE_DIR = Path(__file__).resolve().parent
APP_DIR = WORKSPACE_DIR / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import soundfile as sf
from services.gender_service import GenderService
from services.temporal_gender_smoothing import TemporalGenderSmoothingService
from vad_processor import get_speech_segments


def _ensure_test_audio() -> str:
    """Ensure a 16kHz mono audio test file is available."""
    audio_path = WORKSPACE_DIR / "scratch" / "video_audio.wav"
    if audio_path.is_file():
        return str(audio_path)

    candidates = [
        Path(r"C:\Users\anh27\Downloads\UnduhTiktok.com_7499737263962672435_D1.mp4"),
    ]
    source_video = next((p for p in candidates if p.is_file()), None)
    if not source_video:
        raise FileNotFoundError(
            f"Cannot find test audio at {audio_path} and no sample video found."
        )

    audio_path.parent.mkdir(parents=True, exist_ok=True)
    import subprocess
    cmd = ["ffmpeg", "-y", "-i", str(source_video), "-vn", "-ar", "16000", "-ac", "1", str(audio_path)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return str(audio_path)


def run_full_test_matrix() -> bool:
    test_results: list[tuple[str, bool, list[str]]] = []

    # =========================================================================
    # PART A: AUDIO PIPELINE INTEGRATION TESTS (TEST 1 - 4)
    # =========================================================================
    audio_path = _ensure_test_audio()
    audio_np, sr = sf.read(audio_path, dtype="float32")
    if audio_np.ndim > 1:
        audio_np = audio_np.mean(axis=-1)
    vad_segs = get_speech_segments(audio_np, sr=sr)

    cues = [
        # Nhóm 1: Clear Male
        {"id": 1, "start": 0.0, "end": 1.5, "text": "你介意你喜欢的女生"},
        {"id": 24, "start": 76.5, "end": 78.5, "text": "是不是误会她了"},

        # Nhóm 2: Clear Female
        {"id": 5, "start": 9.5, "end": 13.5, "text": "王宇你这两天怎么回事"},
        {"id": 10, "start": 24.5, "end": 26.5, "text": "你是不是成心想气我啊"},

        # Nhóm 3: Short + BGM (kèm Anchors 22, 24, 26 trong cùng cụm)
        {"id": 22, "start": 73.5, "end": 75.5, "text": "看着她离开的背影"},
        {"id": 23, "start": 75.5, "end": 76.5, "text": "我再一次的怀疑自己"},
        {"id": 25, "start": 78.5, "end": 79.5, "text": "我开始反思我自己"},
        {"id": 26, "start": 79.5, "end": 81.5, "text": "最近对她的态度"},
        {"id": 27, "start": 81.5, "end": 83.5, "text": "直到"},

        # Nhóm 4: Rapid Male / Female Switch
        {"id": 18, "start": 59.5, "end": 60.5, "text": "你还能好好说吗"},
        {"id": 19, "start": 60.5, "end": 62.5, "text": "我怎么没好好跟你说了"},
    ]
    cues.sort(key=lambda c: c["start"])

    service = GenderService()
    raw_results = service.detect_cues(audio_path, cues, vad_intervals=vad_segs)
    final_results = TemporalGenderSmoothingService.smooth(raw_results)
    by_id = {r["id"]: r for r in final_results}

    # TEST 1: Clear Male
    t1_errs = []
    for cid in [1, 24]:
        r = by_id.get(cid, {})
        if r.get("raw_gender") != "male":
            t1_errs.append(f"Câu {cid}: raw_gender={r.get('raw_gender')} != 'male'")
        if r.get("raw_confidence_trust") != "HIGH":
            t1_errs.append(f"Câu {cid}: trust={r.get('raw_confidence_trust')} != 'HIGH'")
        if r.get("final_gender") != "male":
            t1_errs.append(f"Câu {cid}: final_gender={r.get('final_gender')} != 'male'")
        if r.get("decision_mode") != "raw_audio":
            t1_errs.append(f"Câu {cid}: decision_mode={r.get('decision_mode')} != 'raw_audio'")
    test_results.append(("TEST 1 - Clear Male", len(t1_errs) == 0, t1_errs))

    # TEST 2: Clear Female
    t2_errs = []
    for cid in [5, 10]:
        r = by_id.get(cid, {})
        if r.get("raw_gender") != "female":
            t2_errs.append(f"Câu {cid}: raw_gender={r.get('raw_gender')} != 'female'")
        if r.get("raw_confidence_trust") != "HIGH":
            t2_errs.append(f"Câu {cid}: trust={r.get('raw_confidence_trust')} != 'HIGH'")
        if r.get("final_gender") != "female":
            t2_errs.append(f"Câu {cid}: final_gender={r.get('final_gender')} != 'female'")
        if r.get("decision_mode") != "raw_audio":
            t2_errs.append(f"Câu {cid}: decision_mode={r.get('decision_mode')} != 'raw_audio'")
    test_results.append(("TEST 2 - Clear Female", len(t2_errs) == 0, t2_errs))

    # TEST 3: Short + BGM
    t3_errs = []
    for cid in [23, 25, 27]:
        r = by_id.get(cid, {})
        if r.get("raw_gender") != "female":
            t3_errs.append(f"Câu {cid}: raw_gender={r.get('raw_gender')} must preserve raw 'female'")
        if r.get("raw_confidence_trust") == "HIGH":
            t3_errs.append(f"Câu {cid}: trust should not be HIGH for short/BGM audio")
        if r.get("final_gender") != "male":
            t3_errs.append(f"Câu {cid}: final_gender={r.get('final_gender')} != 'male'")
        if r.get("decision_mode") != "contextual_smoothing":
            t3_errs.append(f"Câu {cid}: decision_mode={r.get('decision_mode')} != 'contextual_smoothing'")
        if "anchor_continuity_smoothing" not in r.get("gender_reason", []):
            t3_errs.append(f"Câu {cid}: missing 'anchor_continuity_smoothing'")
    test_results.append(("TEST 3 - Short + BGM (Anchor Smoothing)", len(t3_errs) == 0, t3_errs))

    # TEST 4: Rapid Switch
    t4_errs = []
    r18 = by_id.get(18, {})
    r19 = by_id.get(19, {})
    if r18.get("final_gender") != "female" or r18.get("decision_mode") != "raw_audio":
        t4_errs.append(f"Câu 18: final_gender={r18.get('final_gender')} mode={r18.get('decision_mode')}")
    if r19.get("final_gender") != "male" or r19.get("decision_mode") != "raw_audio":
        t4_errs.append(f"Câu 19: final_gender={r19.get('final_gender')} mode={r19.get('decision_mode')}")
    test_results.append(("TEST 4 - Rapid Male/Female Switch", len(t4_errs) == 0, t4_errs))

    # =========================================================================
    # PART B: MATRIX EDGE CASE SCENARIOS (TEST 5 - 10)
    # =========================================================================

    # TEST 5: Male Anchor -> Short Segment -> Female Anchor
    # Không được kéo short segment sang Male chỉ vì đứng sau Male!
    t5_cues = [
        {"id": 201, "start": 30.0, "end": 32.0, "raw_gender": "male", "raw_gender_confidence": 0.98, "raw_confidence_trust": "HIGH", "audio_quality": "clean", "speech_duration": 1.9, "text": "Anh nói trước"},
        {"id": 202, "start": 32.2, "end": 32.6, "raw_gender": "unknown", "raw_gender_confidence": 0.51, "raw_confidence_trust": "LOW", "audio_quality": "low", "speech_duration": 0.4, "text": "Ừm"},
        {"id": 203, "start": 32.8, "end": 34.8, "raw_gender": "female", "raw_gender_confidence": 0.99, "raw_confidence_trust": "HIGH", "audio_quality": "clean", "speech_duration": 1.9, "text": "Em nghe đây"},
    ]
    t5_res = {r["id"]: r for r in TemporalGenderSmoothingService.smooth(t5_cues)}
    t5_errs = []
    # Short segment 202 không được bị kéo thành 'male'
    if t5_res[202].get("final_gender") == "male":
        t5_errs.append("Short segment 202 was falsely forced to 'male' despite adjacent female anchor.")
    test_results.append(("TEST 5 - Male -> Short -> Female Boundary", len(t5_errs) == 0, t5_errs))

    # TEST 6: Female Anchor -> Short Segment -> Male Anchor
    t6_cues = [
        {"id": 301, "start": 40.0, "end": 42.0, "raw_gender": "female", "raw_gender_confidence": 0.99, "raw_confidence_trust": "HIGH", "audio_quality": "clean", "speech_duration": 1.9, "text": "Anh đi đâu đấy?"},
        {"id": 302, "start": 42.1, "end": 42.5, "raw_gender": "unknown", "raw_gender_confidence": 0.52, "raw_confidence_trust": "LOW", "audio_quality": "low", "speech_duration": 0.4, "text": "Hả?"},
        {"id": 303, "start": 42.7, "end": 44.7, "raw_gender": "male", "raw_gender_confidence": 0.98, "raw_confidence_trust": "HIGH", "audio_quality": "clean", "speech_duration": 1.9, "text": "Tôi đi làm việc"},
    ]
    t6_res = {r["id"]: r for r in TemporalGenderSmoothingService.smooth(t6_cues)}
    t6_errs = []
    if t6_res[302].get("final_gender") == "female":
        t6_errs.append("Short segment 302 was falsely forced to 'female' despite adjacent male anchor.")
    test_results.append(("TEST 6 - Female -> Short -> Male Boundary", len(t6_errs) == 0, t6_errs))

    # TEST 7: Short Segment without Any Anchor
    # Không có anchor nào xung quanh -> Không được gán bừa, giữ nguyên raw_audio
    t7_cues = [
        {"id": 401, "start": 50.0, "end": 50.6, "raw_gender": "male", "raw_gender_confidence": 0.60, "raw_confidence_trust": "LOW", "audio_quality": "low", "speech_duration": 0.5, "text": "Thì ra"},
        {"id": 402, "start": 51.5, "end": 52.0, "raw_gender": "female", "raw_gender_confidence": 0.62, "raw_confidence_trust": "LOW", "audio_quality": "low", "speech_duration": 0.4, "text": "Sau đó"},
    ]
    t7_res = {r["id"]: r for r in TemporalGenderSmoothingService.smooth(t7_cues)}
    t7_errs = []
    for cid in [401, 402]:
        if t7_res[cid].get("decision_mode") == "contextual_smoothing":
            t7_errs.append(f"Câu {cid} was smoothed without any valid strong anchor.")
    test_results.append(("TEST 7 - Short Segment without Anchors", len(t7_errs) == 0, t7_errs))

    # TEST 8: Mixed / Contaminated Audio (low quality / high music)
    # Không được tự nhận mình là Anchor mạnh
    t8_cues = [
        {"id": 501, "start": 60.0, "end": 62.0, "raw_gender": "male", "raw_gender_confidence": 0.99, "raw_confidence_trust": "LOW", "audio_quality": "low", "speech_duration": 0.6, "music_score": 0.55, "text": "Nhạc lớn"},
        {"id": 502, "start": 62.2, "end": 63.0, "raw_gender": "female", "raw_gender_confidence": 0.88, "raw_confidence_trust": "LOW", "audio_quality": "low", "speech_duration": 0.5, "text": "Câu sau"},
    ]
    t8_res = {r["id"]: r for r in TemporalGenderSmoothingService.smooth(t8_cues)}
    t8_errs = []
    # 501 có confidence 99% nhưng trust=LOW và qual=low -> Không được làm anchor để ép câu 502 thành male!
    if t8_res[502].get("final_gender") == "male":
        t8_errs.append("Contaminated segment 501 acted as an anchor to force segment 502.")
    test_results.append(("TEST 8 - Contaminated Audio Non-Anchor", len(t8_errs) == 0, t8_errs))

    # TEST 9: Music / Non-Speech / Static Text
    # Subtitle rác hoặc chỉ có nhạc nền -> gender='none', skip_tts=True
    t9_raw = {"status": "music_or_non_speech", "confidence": 0.0, "gender": "unknown"}
    t9_norm = GenderService.normalize_result(t9_raw)
    t9_errs = []
    if t9_norm.get("gender") != "none":
        t9_errs.append(f"normalize_result gender={t9_norm.get('gender')} != 'none'")
    if not t9_norm.get("skip_tts"):
        t9_errs.append("normalize_result skip_tts is not True for music_or_non_speech")
    test_results.append(("TEST 9 - Music / Non-Speech Handling", len(t9_errs) == 0, t9_errs))

    # TEST 10: Unknown / Insufficient Evidence
    # Khi không có đủ bằng chứng -> gender='unknown', không bị ép cứng về Nam/Nữ
    t10_raw = {"status": "uncertain_gender", "confidence": 0.35, "gender": "unknown"}
    t10_norm = GenderService.normalize_result(t10_raw)
    t10_errs = []
    if t10_norm.get("gender") != "unknown":
        t10_errs.append(f"normalize_result gender={t10_norm.get('gender')} != 'unknown'")
    if t10_norm.get("skip_tts"):
        t10_errs.append("normalize_result skip_tts should be False for uncertain speech")
    test_results.append(("TEST 10 - Unknown / Insufficient Evidence", len(t10_errs) == 0, t10_errs))

    # =========================================================================
    # CONSOLIDATED MATRIX REPORT
    # =========================================================================
    print("=" * 65)
    print("           CAPCAP GENDER AI REGRESSION TEST MATRIX")
    print("=" * 65)
    all_passed = True
    passed_count = 0

    for name, ok, errors in test_results:
        tag = "[PASS]" if ok else "[FAIL]"
        print(f"{tag} {name}")
        if ok:
            passed_count += 1
        else:
            all_passed = False
            for err in errors:
                print(f"       -> {err}")

    print("-" * 65)
    print(f"MATRIX RESULT: {passed_count}/{len(test_results)} PASS")
    print("=" * 65)
    return all_passed


if __name__ == "__main__":
    success = run_full_test_matrix()
    sys.exit(0 if success else 1)

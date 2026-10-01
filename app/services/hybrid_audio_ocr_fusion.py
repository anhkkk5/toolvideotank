"""Confidence-aware fusion of hardcoded OCR subtitles, audio ASR, and VAD speech activity.

Implements the Multimodal Fusion Architecture:
- Spatial / Temporal Tracking (BBox Persistence & Text repetition)
- Silero VAD Speech Coverage
- ASR Alignment Evidence
- Rule Guard with 3 States: CONFIRMED, REVIEW, REJECT (Preserving raw data)
"""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Any, List, Dict, Tuple, Optional

_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# Narrative / Contextual Cues: tuyệt đối không được REJECT dù speech = 0
_NARRATIVE_CUE_RE = re.compile(
    r"(?:"
    r"^\d+[\s年天月日小时分秒]后|"
    r"几天后|三天后|三年后|次日|隔天|翌日|早晨|傍晚|深夜|此时|与此同时|另一边|后来|最终|"
    r"未完待续|全剧终|第[\d一二三四五六七八九十]+[集话期]|"
    r"[\u4e00-\u9fff]{2,8}(?:市|省|区|县|镇|村|国|路|街|巷|公馆|府|山|庄)|"
    r"3\s*ngày\s*sau|hôm\s*sau|sáng\s*hôm\s*sau|vài\s*ngày\s*sau|năm\s*\d+|tập\s*\d+|"
    r"chương\s*\d+|hết|còn\s*tiếp"
    r")",
    re.IGNORECASE,
)


def _normalized_text(text: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]+", "", str(text or "")).lower()


def _text_similarity(left: str, right: str) -> float:
    a, b = _normalized_text(left), _normalized_text(right)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def _overlap_ratio(left: dict, right: dict) -> float:
    ls, le = float(left.get("start", 0.0)), float(left.get("end", 0.0))
    rs, re_ = float(right.get("start", 0.0)), float(right.get("end", 0.0))
    overlap = max(0.0, min(le, re_) - max(ls, rs))
    return overlap / max(0.05, min(le - ls, re_ - rs))


def _looks_corrupt_ocr(text: str) -> bool:
    value = str(text or "").strip()
    if not _normalized_text(value):
        return True
    if re.search(r"[\u3400-\u9fff]\s*[0-9]{1,2}$", value):
        return True
    cjk, latin = len(_CJK_RE.findall(value)), len(_LATIN_RE.findall(value))
    return cjk > 0 and latin >= 5 and latin > cjk


def is_narrative_contextual_cue(text: str) -> bool:
    """Kiểm tra xem văn bản có phải là phụ đề dẫn chuyện/thời gian/địa danh không."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    return bool(_NARRATIVE_CUE_RE.search(cleaned))


def _compute_bbox_iou(box1: Optional[List[float]], box2: Optional[List[float]]) -> float:
    """Tính toán IoU giữa 2 bounding boxes dạng [x_min, y_min, x_max, y_max]."""
    if not box1 or not box2 or len(box1) < 4 or len(box2) < 4:
        return 0.0
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0

    area1 = max(0.0, (box1[2] - box1[0]) * (box1[3] - box1[1]))
    area2 = max(0.0, (box2[2] - box2[0]) * (box2[3] - box2[1]))
    union = area1 + area2 - inter_area
    return inter_area / union if union > 0 else 0.0


def _compute_bbox_center_dist(box1: Optional[List[float]], box2: Optional[List[float]]) -> float:
    """Khoảng cách Euclidean chuẩn hóa giữa tâm 2 bbox."""
    if not box1 or not box2 or len(box1) < 4 or len(box2) < 4:
        return 1.0
    c1_x = (box1[0] + box1[2]) / 2.0
    c1_y = (box1[1] + box1[3]) / 2.0
    c2_x = (box2[0] + box2[2]) / 2.0
    c2_y = (box2[1] + box2[3]) / 2.0
    return ((c1_x - c2_x) ** 2 + (c1_y - c2_y) ** 2) ** 0.5


def compute_speech_coverage(
    seg_start: float,
    seg_end: float,
    speech_intervals: List[Any],
) -> float:
    """Tính tỷ lệ bao phủ của giọng nói (speech_coverage) qua VAD intervals."""
    seg_dur = max(0.05, seg_end - seg_start)
    if not speech_intervals:
        return 0.0

    total_speech_overlap = 0.0
    for v in speech_intervals:
        if isinstance(v, dict):
            v_start, v_end = float(v.get("start", 0.0)), float(v.get("end", 0.0))
        elif isinstance(v, (tuple, list)) and len(v) >= 2:
            v_start, v_end = float(v[0]), float(v[1])
        else:
            continue
        overlap = max(0.0, min(seg_end, v_end) - max(seg_start, v_start))
        total_speech_overlap += overlap

    return min(1.0, round(total_speech_overlap / seg_dur, 3))


def classify_ocr_segments_multimodal(
    ocr_segments: List[Dict[str, Any]],
    speech_intervals: Optional[List[Any]] = None,
    asr_segments: Optional[List[Dict[str, Any]]] = None,
    *,
    vad_speech_intervals: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Phân loại đa phương thức 3 trạng thái cho từng segment OCR.

    Rule Guard & Evidence Scoring:
    - CONFIRMED: Đủ bằng chứng xử lý tự động (Speech cao hoặc ASR khớp).
    - REVIEW: Giữ lại kiểm tra, tuyệt đối không tự xóa (Chữ dẫn chuyện, thoại nhỏ trong nhạc, mixed_audio).
    - REJECT: Đánh dấu static_text/is_noise nhưng BẢO TOÀN raw data, gán gender="none", skip TTS.
    """
    if not ocr_segments:
        return []

    raw_intervals = vad_speech_intervals if vad_speech_intervals is not None else (speech_intervals or [])
    norm_speech_intervals: List[Tuple[float, float]] = []
    for v in raw_intervals:
        if isinstance(v, dict):
            norm_speech_intervals.append((float(v.get("start", 0.0)), float(v.get("end", 0.0))))
        elif isinstance(v, (tuple, list)) and len(v) >= 2:
            norm_speech_intervals.append((float(v[0]), float(v[1])))

    speech_intervals = norm_speech_intervals
    asr_list = asr_segments or []
    classified: List[Dict[str, Any]] = []

    # 1. Tính toán Spatial Persistence (Phát hiện chữ bám dính / lặp lại qua nhiều frame)
    # So sánh từng segment với các segment lân cận trong bán kính +/- 6 giây
    n = len(ocr_segments)
    persistence_scores = [0.0] * n

    for i in range(n):
        curr = ocr_segments[i]
        curr_text = curr.get("text", "")
        curr_box = curr.get("bbox")
        repeats = 0

        for j in range(max(0, i - 4), min(n, i + 5)):
            if i == j:
                continue
            other = ocr_segments[j]
            t_sim = _text_similarity(curr_text, other.get("text", ""))
            box_iou = _compute_bbox_iou(curr_box, other.get("bbox"))
            center_dist = _compute_bbox_center_dist(curr_box, other.get("bbox"))

            # Chữ giống nhau và vị trí bám dính (hoặc di chuyển nhẹ theo người)
            if t_sim >= 0.75 and (box_iou >= 0.30 or center_dist <= 0.20):
                repeats += 1

        persistence_scores[i] = min(1.0, repeats / 3.0)

    # 2. Đánh giá từng segment theo Evidence Scoring + Rule Guard
    for idx, seg in enumerate(ocr_segments):
        item = dict(seg)
        start = float(item.get("start", 0.0))
        end = float(item.get("end", 0.0))
        text = str(item.get("text", "")).strip()

        # A. Tính Audio Evidence
        speech_cov = compute_speech_coverage(start, end, speech_intervals)
        item["speech_coverage"] = speech_cov

        # Tìm ASR trùng khớp thời gian
        best_asr_text = ""
        best_asr_align = 0.0
        for asr in asr_list:
            as_start, as_end = float(asr.get("start", 0.0)), float(asr.get("end", 0.0))
            if min(end, as_end) > max(start, as_start):  # có giao thoa thời gian
                align_ratio = _text_similarity(text, asr.get("text", ""))
                if align_ratio > best_asr_align:
                    best_asr_align = align_ratio
                    best_asr_text = asr.get("text", "")

        item["asr_text"] = best_asr_text
        item["asr_alignment"] = round(best_asr_align, 3)

        # B. Tính Spatial & Context Evidence
        spatial_pers = round(persistence_scores[idx], 3)
        item["bbox_persistence"] = spatial_pers
        is_narrative = is_narrative_contextual_cue(text)
        item["contextual_cue"] = is_narrative

        # C. Evidence Scoring
        # Trọng số: VAD 0.45, ASR 0.30, Spatial inverse 0.15, Context 0.10
        score = (
            0.45 * speech_cov +
            0.30 * best_asr_align +
            0.15 * (1.0 - spatial_pers) +
            0.10 * (1.0 if is_narrative else 0.0)
        )
        item["fusion_score"] = round(min(1.0, max(0.0, score)), 3)

        # D. RULE GUARD (Luật cứng phân định trạng thái cuối cùng)
        status = "review"
        reason = ""
        is_noise = False
        gender = item.get("gender", "unknown")

        # Kiểm tra dấu hiệu chữ rác trên màn hình điện thoại / app giải toán / tài liệu học tập
        STRONG_SCREEN_NOISE = (
            "题目解答", "去搜书", "参考答案", "答案来源", "关键考查点",
            "日期跨度的计算", "日两图时计算", "讲解中 月从月日到", "秒出解题步骤", "加错题本",
            "平均每天花餐饮费", "平均商的色用", "解颐核心思路", "求平均每天的餐饮费",
        )
        PHONE_UI_KEYWORDS = (
            "题目解答", "去搜书", "参考答案", "答案来源", "解析", "关键考查点", "考查点",
            "解题步骤", "核心思路", "加错题本", "相关解答", "单元测试", "试卷",
            "日期跨度", "分段计算", "讲解中", "秒出解题步骤", "平均商", "餐饮费", "日两图",
            "图时计算", "日日示购", "总费用除", "求平均", "除以总天数",
        )
        cjk_chars = re.findall(r"[\u3400-\u9fff]", text)
        cjk_len = len(cjk_chars)
        dur = max(0.2, end - start)
        rate = cjk_len / dur

        is_strong_noise = any(kw in text for kw in STRONG_SCREEN_NOISE)
        ui_kw_count = sum(1 for kw in PHONE_UI_KEYWORDS if kw in text)
        is_screen_doc_noise = (
            is_strong_noise
            or ui_kw_count >= 2
            or (ui_kw_count >= 1 and (cjk_len >= 18 or rate >= 10.0))
        )

        # LUẬT 1: Chữ dẫn chuyện / địa danh (Narrative Cue) ➔ Tuyệt đối KHÔNG REJECT
        if is_narrative:
            status = "review"
            reason = "narrative_context_no_speech" if speech_cov < 0.20 else "narrative_cue_with_speech"
            is_noise = False

        # LUẬT 1.5: Rác màn hình điện thoại / app giải toán / tài liệu không khớp ASR ➔ REJECT
        elif is_screen_doc_noise and best_asr_align < 0.25:
            status = "static_text"
            reason = "screen_document_ui_noise"
            is_noise = True
            gender = "none"
            item["skip_tts"] = True

        # LUẬT 2: Bằng chứng giọng nói vững chắc ➔ CONFIRMED (Đủ bằng chứng tự động)
        elif speech_cov >= 0.50 or (speech_cov >= 0.25 and best_asr_align >= 0.35):
            status = "confirmed_speech"
            reason = "high_speech_coverage" if speech_cov >= 0.50 else "speech_and_asr_aligned"
            is_noise = False

        # LUẬT 3: Chữ tĩnh lặp lại / Logo thương hiệu / Không hề có tiếng nói ➔ REJECT (Nhưng bảo toàn raw data)
        elif speech_cov < 0.10 and (spatial_pers >= 0.40 or (_looks_corrupt_ocr(text) and not best_asr_text)):
            status = "static_text"
            reason = "persistent_bbox_without_speech" if spatial_pers >= 0.40 else "non_speech_isolated_text"
            is_noise = True
            gender = "none"

        # LUẬT 4: Vùng biên / Thoại nhỏ trong nhạc to / Âm thanh hỗn hợp ➔ REVIEW (Giữ lại để người dùng xem)
        else:
            status = "review"
            if 0.10 <= speech_cov < 0.50:
                reason = "possible_speech_with_music"
            else:
                reason = "low_evidence_needs_review"
            is_noise = False

        item["status"] = status
        item["fusion_reason"] = reason
        item["is_noise"] = is_noise
        item["gender"] = gender

        classified.append(item)

    return classified


def _asr_is_reliable(segment: dict) -> bool:
    text = str(segment.get("text", "") or "").strip()
    if len(_normalized_text(text)) < 2:
        return False
    if float(segment.get("no_speech_prob", 0.0) or 0.0) > 0.55:
        return False
    if float(segment.get("avg_logprob", -1.0) or -1.0) < -0.95:
        return False
    words = re.findall(r"[A-Za-z]+", text.lower())
    if len(words) >= 5 and len(set(words)) <= max(2, len(words) // 3):
        return False
    return True


def _merge_near_duplicate_ocr(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse successive OCR samples of the same on-screen caption."""
    ordered = sorted((dict(item) for item in segments), key=lambda x: float(x.get("start", 0.0)))
    merged: list[dict[str, Any]] = []
    for item in ordered:
        item["source"] = item.get("source") or "ocr"
        if not merged:
            merged.append(item)
            continue
        previous = merged[-1]
        gap = float(item.get("start", 0.0)) - float(previous.get("end", 0.0))
        similarity = _text_similarity(previous.get("text", ""), item.get("text", ""))
        if gap <= 0.65 and similarity >= 0.84:
            previous["end"] = max(float(previous.get("end", 0.0)), float(item.get("end", 0.0)))
            old_text, new_text = str(previous.get("text", "")), str(item.get("text", ""))
            if (_looks_corrupt_ocr(old_text) and not _looks_corrupt_ocr(new_text)) or len(new_text) > len(old_text):
                previous["text"] = new_text
            continue
        merged.append(item)
    return merged


def _normalize_timeline(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make cues monotonic and remove accidental OCR/ASR overlap."""
    result: list[dict[str, Any]] = []
    for raw in sorted(segments, key=lambda x: float(x.get("start", 0.0))):
        item = dict(raw)
        start = max(0.0, float(item.get("start", 0.0)))
        end = max(start + 0.05, float(item.get("end", start + 0.05)))
        if result and start < float(result[-1]["end"]):
            start = float(result[-1]["end"])
        if end <= start + 0.04:
            continue
        item["start"], item["end"] = round(start, 3), round(end, 3)
        result.append(item)
    return result


def extract_audio_speech_and_asr(
    audio_path: str,
    *,
    whisper_model_name: str = "small",
) -> Tuple[List[Tuple[float, float]], List[Dict[str, Any]]]:
    """Trích xuất danh sách VAD speech_intervals và ASR segments từ audio stream."""
    speech_intervals: List[Tuple[float, float]] = []
    asr_segments: List[Dict[str, Any]] = []

    if not audio_path or not os.path.isfile(audio_path):
        return speech_intervals, asr_segments

    # 1. Thử dùng Silero VAD từ app.vad_processor trước
    try:
        import soundfile as sf
        from app.vad_processor import get_speech_segments
        audio, sr = sf.read(audio_path, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr == 16000:
            vad_res = get_speech_segments(audio, sr=16000)
            for seg in vad_res:
                speech_intervals.append((float(seg.get("start", 0.0)), float(seg.get("end", 0.0))))
            print(f"[Multimodal Fusion] Silero VAD detected {len(speech_intervals)} speech interval(s).")
    except Exception as e:
        print(f"[Multimodal Fusion] Silero VAD notice: {e}, falling back to Whisper VAD.")

    # 2. Chạy Faster-Whisper để lấy ASR và fallback VAD
    try:
        from faster_whisper import WhisperModel
        requested_model = str(whisper_model_name or "small").strip()
        if requested_model.lower().startswith("ggml-"):
            requested_model = requested_model[5:].removesuffix(".bin")

        model = WhisperModel(requested_model, device="cpu", compute_type="int8")
        trans_segs, _ = model.transcribe(
            audio_path,
            language="zh",
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            condition_on_previous_text=False,
        )

        for ts in trans_segs:
            st = round(float(ts.start), 3)
            en = round(float(ts.end), 3)
            if not speech_intervals:
                speech_intervals.append((st, en))

            candidate = {
                "start": st,
                "end": en,
                "text": str(ts.text or "").strip(" -_.,;:!?|/\\[]{}()<>'\"`~"),
                "words": [],
                "source": "asr_supplement",
                "avg_logprob": float(getattr(ts, "avg_logprob", -1.0) or -1.0),
                "no_speech_prob": float(getattr(ts, "no_speech_prob", 0.0) or 0.0),
            }
            if _asr_is_reliable(candidate):
                asr_segments.append(candidate)

        print(f"[Multimodal Fusion] Whisper ASR generated {len(asr_segments)} segment(s).")
    except Exception as exc:
        print(f"[Multimodal Fusion] Whisper ASR error: {exc}")

    return speech_intervals, asr_segments


def fill_ocr_gaps_with_speech(
    audio_path: str,
    ocr_segments: list[dict[str, Any]],
    *,
    min_gap_seconds: float = 2.0,
    whisper_model_name: str = "small",
) -> list[dict[str, Any]]:
    """Module 2: Bổ sung câu thoại ASR bị OCR bỏ sót hoàn toàn (Gap filling)."""
    if not audio_path or not os.path.isfile(audio_path) or not ocr_segments:
        return ocr_segments

    speech_intervals, asr_segments = extract_audio_speech_and_asr(
        audio_path, whisper_model_name=whisper_model_name
    )

    combined = list(ocr_segments)
    additions = 0

    for asr in asr_segments:
        overlaps = [(index, _overlap_ratio(ocr, asr)) for index, ocr in enumerate(combined)]
        best_index, best_overlap = max(overlaps, key=lambda pair: pair[1], default=(-1, 0.0))

        # Chỉ thêm nếu hoàn toàn không có OCR nào bao phủ vùng này
        if best_overlap < 0.25:
            combined.append(asr)
            additions += 1

    combined = _normalize_timeline(_merge_near_duplicate_ocr(combined))
    print(f"[Multimodal Fusion] Gap fill added {additions} missing speech turn(s).")
    return combined


def align_cues_with_asr_and_vad(
    cues: List[Dict[str, Any]],
    asr_segments: Optional[List[Dict[str, Any]]] = None,
    vad_intervals: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Căn chỉnh ranh giới thời gian (start & end) của từng phụ đề bằng SenseVoice ASR & Silero VAD.
    
    Giải quyết triệt để:
    1. Cắt âm thanh đúng từng câu, loại bỏ hiện tượng câu trước bị kéo dài nuốt sang câu sau (chữ lưu trên màn hình).
    2. Bảo toàn trọn vẹn câu sau không bị mất đoạn đầu.
    3. Giúp mô hình Gender AI nhận diện chuẩn 100% âm học của từng nhân vật mà không bị lọt giọng đối phương.
    4. Giúp chức năng Nghe và Tải MP3 phát đúng trọn vẹn câu thoại.
    """
    if not cues:
        return []

    # 1. Chuẩn hóa VAD speech intervals
    raw_intervals = vad_intervals or []
    norm_vad: List[Tuple[float, float]] = []
    for v in raw_intervals:
        if isinstance(v, dict):
            vs, ve = float(v.get("start", 0.0)), float(v.get("end", 0.0))
        elif isinstance(v, (tuple, list)) and len(v) >= 2:
            vs, ve = float(v[0]), float(v[1])
        else:
            continue
        if ve > vs:
            norm_vad.append((vs, ve))
    norm_vad.sort(key=lambda x: x[0])

    # 2. Chuẩn hóa ASR segments
    norm_asr: List[Dict[str, Any]] = []
    for asr in (asr_segments or []):
        if not isinstance(asr, dict):
            continue
        txt = str(asr.get("text", "")).strip()
        as_s = float(asr.get("start", 0.0))
        as_e = float(asr.get("end", as_s))
        if as_e > as_s and txt:
            norm_asr.append({
                "start": as_s,
                "end": as_e,
                "text": txt,
                "cjk": "".join(_CJK_RE.findall(txt)),
            })
    norm_asr.sort(key=lambda x: x["start"])

    aligned_cues: List[Dict[str, Any]] = []

    for idx, cue in enumerate(cues):
        item = dict(cue)
        c_start = float(item.get("start", 0.0))
        c_end = float(item.get("end", c_start + 0.1))
        t_raw = str(item.get("text", "") or item.get("original_text", "")).strip()
        t_cjk = "".join(_CJK_RE.findall(t_raw))
        num_cjk = len(t_cjk) if t_cjk else len(t_raw)

        # Thời lượng nói ước tính dựa trên số lượng chữ tiếng Trung (trung bình 3 - 4 chữ Hán / giây)
        est_dur = max(0.8, num_cjk * 0.32 + 0.35)

        best_asr = None
        best_asr_score = 0.0

        # --- A. TÌM KIẾM ASR KHỚP TỐT NHẤT ---
        for asr in norm_asr:
            as_s, as_e = asr["start"], asr["end"]
            # Khoảng thời gian trong phạm vi +/- 2.5s
            if as_e < c_start - 2.5 or as_s > c_end + 2.5:
                continue

            as_cjk = asr["cjk"]
            if not as_cjk:
                continue

            # Độ tương đồng ký tự Hán
            sim = SequenceMatcher(None, t_cjk, as_cjk).ratio()

            # Substring match (Một bên chứa bên kia)
            is_sub = (t_cjk in as_cjk) or (as_cjk in t_cjk)
            sub_bonus = 0.35 if is_sub and min(len(t_cjk), len(as_cjk)) >= 2 else 0.0

            # Điểm thời gian giao thoa
            time_overlap = max(0.0, min(c_end, as_e) - max(c_start, as_s))
            time_score = min(0.3, time_overlap / max(0.1, min(c_end - c_start, as_e - as_s)))

            total_score = sim + sub_bonus + time_score

            if total_score > best_asr_score and (sim >= 0.50 or is_sub):
                best_asr_score = total_score
                best_asr = asr

        new_start = c_start
        new_end = c_end

        if best_asr and best_asr_score >= 0.70:
            as_s = float(best_asr["start"])
            as_e = float(best_asr["end"])
            as_cjk = best_asr["cjk"]
            total_dur = max(0.4, as_e - as_s)
            total_chars = max(1, len(as_cjk))

            # Tìm vị trí xuất hiện của t_cjk trong as_cjk
            pos = as_cjk.find(t_cjk)
            matched_len = len(t_cjk)

            # Nếu không tìm thấy exact substring, tìm chuỗi con chung dài nhất (LCS)
            if pos == -1:
                matcher = SequenceMatcher(None, t_cjk, as_cjk)
                match = matcher.find_longest_match(0, len(t_cjk), 0, len(as_cjk))
                if match.size >= 2:
                    pos = match.b
                    matched_len = match.size

            # Chỉ áp dụng nội suy vị trí nếu chunk ASR ngắn (<= 6.0s).
            # Với các chunk dài do nhạc nền, nội suy ký tự tuyến tính có thể gây lệch hàng chục giây!
            if pos != -1 and total_chars > 0 and total_dur <= 6.0:
                start_ratio = max(0.0, pos / total_chars)
                end_ratio = min(1.0, (pos + num_cjk) / total_chars)

                sub_s = as_s + total_dur * start_ratio
                sub_e = as_s + total_dur * end_ratio

                if (sub_e - sub_s) < est_dur * 0.75:
                    sub_e = sub_s + est_dur

                if abs(sub_s - c_start) <= 0.85:
                    new_start = sub_s
                new_end = sub_e
            else:
                # Với chunk ASR dài, snap nhẹ vào VAD interval gần nhất nếu có
                close_vad = [v for v in norm_vad if abs(v[0] - c_start) <= 0.60]
                if close_vad:
                    new_start = close_vad[0][0]

            item["aligned_source"] = "asr"
            item["asr_matched"] = best_asr["text"]
        else:
            # --- B. CĂN CHỈNH BẰNG VAD INTERVALS ---
            slot_vad = [v for v in norm_vad if max(c_start - 0.2, v[0]) < min(c_end + 0.2, v[1])]
            if slot_vad:
                first_vs = min(v[0] for v in slot_vad)
                last_ve = max(v[1] for v in slot_vad)

                if abs(first_vs - c_start) <= 0.60:
                    new_start = max(0.0, first_vs - 0.05)

                if (c_end - c_start) > est_dur + 0.9:
                    suitable_ve = c_end
                    for v in slot_vad:
                        if v[1] <= c_start + est_dur + 0.6:
                            suitable_ve = v[1]
                    new_end = max(new_start + 0.6, suitable_ve + 0.1)
                else:
                    new_end = min(c_end, last_ve + 0.1)

                item["aligned_source"] = "vad"

        # RÀNG BUỘC BẤT BIẾN (Hard Anchor Invariant):
        # Mốc OCR xuất hiện trên video là sự thật thị giác, tuyệt đối không cho phép
        # bất kỳ phép tính nào kéo trôi start lệch quá 0.8s so với c_start gốc!
        if abs(new_start - c_start) > 0.80:
            new_start = c_start

        # Giới hạn thời lượng tối đa an toàn theo số chữ Hán (tránh chữ rác bìa sách kéo dài 10-15s)
        max_dur = max(1.0, min(4.5, num_cjk * 0.38 + 0.50))
        new_end = min(max(new_start + 0.45, new_end), new_start + max_dur)

        item["start"] = round(new_start, 2)
        item["end"] = round(new_end, 2)
        aligned_cues.append(item)

    # --- C. CHỐNG CHỒNG LẤN AN TOÀN - TUYỆT ĐỐI KHÔNG GÂY HIỆU ỨNG THÁC LỆCH THỜI GIAN ---
    # Nguyên tắc: start của câu sau (next_s) được neo bởi frame xuất hiện trên video.
    # Khi câu trước bị chồng lấn, chỉ cắt bớt phần đuôi của câu trước,
    # TUYỆT ĐỐI KHÔNG đẩy lùi next_s về tương lai (tránh domino xô lệch 40-50s).
    aligned_cues.sort(key=lambda x: float(x.get("start", 0.0)))
    for i in range(len(aligned_cues) - 1):
        cur_c = aligned_cues[i]
        next_c = aligned_cues[i + 1]

        cur_s = float(cur_c.get("start", 0.0))
        cur_e = float(cur_c.get("end", 0.0))
        next_s = float(next_c.get("start", 0.0))

        if cur_e >= next_s:
            safe_cur_e = max(cur_s + 0.35, next_s - 0.04)
            cur_c["end"] = round(safe_cur_e, 2)

    return aligned_cues


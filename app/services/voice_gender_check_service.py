"""Standalone burned-subtitle to acoustic voice-gender inspection."""

from __future__ import annotations

import os
import re
import tempfile
from typing import Any, Callable

from services.engine_runtime import EngineRuntime
from services.gender_service import GenderService
from services.subtitle_merge_service import SubtitleMergeService
from services.subtitle_translation_service import SubtitleTranslationService


class VoiceGenderCheckService:
    """Orchestrate audio extraction, OCR reading, deduplication, translation, and gender AI."""

    def run(
        self,
        video_path: str,
        *,
        existing_cues: list[dict[str, Any]] | None = None,
        progress: Callable[[str], None] | None = None,
        ocr_rect: tuple[float, float, float, float] | list[float] | None = None,
    ) -> dict[str, Any]:
        if not video_path or not os.path.isfile(video_path):
            raise RuntimeError("Không tìm thấy video gốc để kiểm tra.")
        if ocr_rect and len(ocr_rect) == 4:
            try:
                rx, ry, rw, rh = [float(x) for x in ocr_rect]
                if rw > 0 and rh > 0:
                    os.environ["OCR_SUBTITLE_RECT"] = f"{rx:.4f},{ry:.4f},{rw:.4f},{rh:.4f}"
            except Exception:
                pass
        notify = progress or (lambda _message: None)
        engine = EngineRuntime()

        with tempfile.TemporaryDirectory(prefix="capcap_voice_gender_") as temp_dir:
            audio_path = os.path.join(temp_dir, "source_audio.wav")
            notify("Đang tách âm thanh gốc…")
            if not engine.extract_audio(video_path, audio_path) or not os.path.isfile(audio_path):
                raise RuntimeError("Không thể tách âm thanh từ video gốc.")

            vad_intervals: list[dict[str, Any]] = []
            asr_segments: list[dict[str, Any]] = []
            raw_cues: list[dict[str, Any]] = []

            # Định nghĩa hàm xử lý âm thanh (VAD + SenseVoice ASR)
            def _process_audio_features():
                local_vad = []
                local_asr = []
                try:
                    import soundfile as sf
                    from vad_processor import get_speech_segments
                    audio_data, sr = sf.read(audio_path, dtype="float32")
                    if audio_data.ndim > 1:
                        audio_data = audio_data.mean(axis=-1)
                    local_vad = get_speech_segments(audio_data, sr=sr)
                    print(f"[Voice Gender Check] VAD detected {len(local_vad)} speech intervals.")
                except Exception as e:
                    print(f"[Voice Gender Check] VAD notice: {e}")
                    local_vad = []

                try:
                    from runtime_paths import models_path
                    sensevoice_dir = str(models_path("sensevoice"))
                    raw = engine.transcribe_audio_sensevoice(audio_path, sensevoice_dir, language="zh")
                    local_asr = [dict(s) for s in (raw or [])]
                    print(f"[Voice Gender Check] ASR SenseVoice detected {len(local_asr)} segments.")
                except Exception as e:
                    print(f"[Voice Gender Check] ASR SenseVoice notice: {e}")
                    local_asr = []

                return local_vad, local_asr

            # Định nghĩa hàm đọc phụ đề video qua OCR
            def _process_video_ocr():
                region = str(os.getenv("OCR_SUBTITLE_REGION", "bottom") or "bottom")
                return list(engine.transcribe_video_ocr(video_path, region=region) or [])

            # Tối ưu hóa: Nếu đã có existing_cues hợp lệ, tái sử dụng ngay và chỉ phân tích audio
            has_valid_existing = bool(
                existing_cues and isinstance(existing_cues, list) and len(existing_cues) > 0
                and any(str(c.get("text", "") or "").strip() for c in existing_cues)
            )

            if has_valid_existing:
                notify("Tái sử dụng phụ đề đã nhận diện, đang phân tích giọng nói (ASR + VAD)…")
                raw_cues = [dict(c) for c in (existing_cues or []) if str(c.get("text", "") or "").strip()]
                vad_intervals, asr_segments = _process_audio_features()
            else:
                # Chạy SONG SONG tác vụ Audio (VAD + ASR) và Video (OCR) để giảm 50% thời gian chờ
                notify("Đang xử lý song song: Đọc phụ đề video (OCR) và nhận diện giọng nói (ASR/VAD)…")
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    fut_audio = executor.submit(_process_audio_features)
                    fut_ocr = executor.submit(_process_video_ocr)

                    vad_intervals, asr_segments = fut_audio.result()
                    raw_cues = fut_ocr.result()

            cues = [dict(cue) for cue in raw_cues if str(cue.get("text", "") or "").strip()]
            cues = self._filter_ocr_noise(cues)

            # 1. OCR Merge / Dedup with adaptive max_gap and strict text rules
            cues = SubtitleMergeService.merge_cues(cues)
            from services.fuzzy_duplicate_service import FuzzyDuplicateService
            cues = FuzzyDuplicateService.merge_fuzzy_cues(cues, vad_intervals=vad_intervals)
            if not cues:
                raise RuntimeError(
                    "Không đọc được phụ đề gốc. Hãy bấm OCR, đặt khung đúng vùng phụ đề rồi chạy lại."
                )

            # 2. Multimodal Fusion (OCR + ASR + VAD) loại bỏ chữ rác bao bì/logo
            notify("Đang kết hợp OCR, ASR và VAD (Multimodal Fusion)…")
            from services.hybrid_audio_ocr_fusion import classify_ocr_segments_multimodal, align_cues_with_asr_and_vad
            cues = classify_ocr_segments_multimodal(cues, vad_speech_intervals=vad_intervals, asr_segments=asr_segments)

            # 2.1 Căn chỉnh ranh giới giọng nói bằng SenseVoice ASR & Silero VAD (Cắt audio chuẩn xác)
            notify("Đang căn chỉnh thời gian âm thanh phụ đề bằng SenseVoice ASR & VAD…")
            cues = align_cues_with_asr_and_vad(cues, asr_segments=asr_segments, vad_intervals=vad_intervals)

            # Assign consecutive IDs for tracking
            indexed_cues = [
                {**cue, "id": cue.get("id", index)}
                for index, cue in enumerate(cues, start=1)
            ]

            # 3. Audio-First: Nhận diện giọng nói vật lý bằng Gender AI offline trước
            notify("Đang nhận diện âm học giọng nói (Gender AI Audio-First)…")
            speech_cues = [c for c in indexed_cues if c.get("status") != "static_text" and not c.get("is_noise")]
            static_cues = [c for c in indexed_cues if c.get("status") == "static_text" or c.get("is_noise")]
            for sc in static_cues:
                sc["gender"] = "none"
                sc["skip_tts"] = True
                sc["confidence"] = 1.0

            if speech_cues:
                try:
                    detected_speech = GenderService().detect_cues(
                        audio_path,
                        speech_cues,
                        vad_intervals=vad_intervals,
                        progress=notify,
                    )
                except Exception as g_err:
                    print(f"[Voice Gender Check] GenderService acoustic fallback: {g_err}")
                    from services.speaker_gender import detect_speaker_gender_aggregated
                    detected_speech = []
                    for cue in speech_cues:
                        res = detect_speaker_gender_aggregated(audio_path, [cue])
                        g = res.get("gender", "unknown")
                        detected_speech.append({
                            **cue,
                            "gender": g,
                            "confidence": res.get("confidence", 0.7),
                            "raw_gender": g,
                            "raw_gender_confidence": res.get("confidence", 0.7),
                            "final_gender": g,
                        })
            else:
                detected_speech = []

            id_to_cue = {}
            for c in (detected_speech + static_cues):
                raw_id = c.get("id")
                rg = str(c.get("raw_gender") or c.get("gender") or "unknown").lower().strip()
                rc = float(c.get("raw_gender_confidence") or c.get("confidence") or 0.0)
                if rc > 1.0:
                    rc /= 100.0
                c["raw_gender"] = rg
                c["raw_gender_confidence"] = rc
                if rg in {"male", "female"}:
                    c["gender"] = rg
                id_to_cue[raw_id] = c
                id_to_cue[str(raw_id)] = c

            detected = []
            for c in indexed_cues:
                cid = c.get("id")
                matched = id_to_cue.get(cid) or id_to_cue.get(str(cid))
                detected.append(matched if matched else c)

            # 4. Xác lập Mốc Âm Học (Acoustic Anchors) & Quán tính lời thoại (Continuation Inertia)
            TURN_TAKING_TRIGGERS = (
                "对不起", "抱歉", "不好意思", "我错了", "我不是", "我没有", "我不太懂", "我不知道",
                "不要", "凭什么", "为什么", "算了", "行了", "别说了", "没关系", "怎么了",
                "好的", "恩", "嗯", "真的吗", "不是吧", "你干嘛", "你别", "放开", "救命"
            )

            for i, c in enumerate(detected):
                dur = float(c.get("end", 0.0)) - float(c.get("start", 0.0))
                c["duration"] = round(dur, 2)
                curr_txt = str(c.get("text", "") or c.get("original_text", "")).strip()
                is_turn_taking = any(trig in curr_txt for trig in TURN_TAKING_TRIGGERS)
                c["is_turn_taking"] = is_turn_taking

                if i > 0 and not is_turn_taking:
                    prev = detected[i - 1]
                    gap = round(float(c.get("start", 0.0)) - float(prev.get("end", 0.0)), 3)
                    prev_g = str(prev.get("raw_gender") or prev.get("gender") or "").lower()
                    prev_conf = float(prev.get("raw_gender_confidence") or prev.get("confidence") or 0.0)
                    if prev_conf > 1.0:
                        prev_conf /= 100.0
                    curr_g = str(c.get("raw_gender") or c.get("gender") or "").lower()
                    curr_conf = float(c.get("raw_gender_confidence") or c.get("confidence") or 0.0)
                    if curr_conf > 1.0:
                        curr_conf /= 100.0

                    # Quán tính lời thoại: Chỉ áp dụng khi câu này cùng giới tính hoặc âm học câu này yếu/unknown (< 75%)
                    # Tuyệt đối không ép quán tính khi câu này đã có âm thanh đối lập rõ rệt (>= 75%) hoặc câu đối đáp
                    is_opposing = (curr_g in {"male", "female"} and curr_g != prev_g and curr_conf >= 0.75)
                    if gap <= 0.60 and dur <= 1.2 and prev_g in {"male", "female"} and prev_conf >= 0.85:
                        if not is_opposing:
                            c["continuation_gender"] = prev_g

                # Liên kết tiến (Forward Linking): Nếu câu này là câu đối đáp/xin lỗi/câu ngắn,
                # và câu tiếp theo là câu có âm học rõ ràng cùng lượt nói (gap <= 0.8s)
                if is_turn_taking and i + 1 < len(detected):
                    nxt = detected[i + 1]
                    nxt_g = str(nxt.get("raw_gender") or nxt.get("gender") or "").lower()
                    nxt_conf = float(nxt.get("raw_gender_confidence") or nxt.get("confidence") or 0.0)
                    if nxt_conf > 1.0:
                        nxt_conf /= 100.0
                    nxt_gap = round(float(nxt.get("start", 0.0)) - float(c.get("end", 0.0)), 3)
                    if nxt_gap <= 0.80 and nxt_g in {"male", "female"} and nxt_conf >= 0.70:
                        c["continuation_gender"] = nxt_g

                # Gán nhãn sơ bộ cho DeepSeek: Ưu tiên Từ vựng Xưng hô Tuyệt đối -> Âm học tin cậy (ngưỡng động theo duration) -> Quán tính
                from services.decision_fusion_service import DecisionFusionService
                voc_res = DecisionFusionService.detect_vocative_gender(curr_txt, "")
                voc_g = voc_res[0] if (isinstance(voc_res, (list, tuple)) and len(voc_res) > 0) else None

                rg = str(c.get("raw_gender") or c.get("gender") or "").lower()
                rc = float(c.get("raw_gender_confidence") or c.get("confidence") or 0.0)
                if rc > 1.0:
                    rc /= 100.0
                cont_g = c.get("continuation_gender")

                # FIX THUẬT TOÁN: Ngưỡng tin cậy âm học ĐỘNG theo duration
                # Câu ngắn < 1.5s: Mô hình ECAPA/AST cần nhiều chu kỳ thanh môn hơn → yêu cầu >= 0.85
                # Câu dài >= 1.5s: Đủ tín hiệu âm học → chấp nhận >= 0.72
                min_acoustic_conf = 0.85 if dur < 1.5 else 0.72

                # Xác định mức tin cậy âm học (acoustic trust level) để gửi cho DeepSeek
                raw_trust = c.get("raw_confidence_trust", "")
                if not raw_trust:
                    if rc >= 0.85 and dur >= 1.2:
                        raw_trust = "HIGH"
                    elif rc >= min_acoustic_conf:
                        raw_trust = "MEDIUM"
                    else:
                        raw_trust = "LOW"

                # Tạo acoustic_hint chi tiết để DeepSeek biết mức tin cậy thực tế
                if rg in {"male", "female"}:
                    c["acoustic_hint"] = f"{rg} {rc*100:.1f}% ({dur:.2f}s, {raw_trust} trust)"
                else:
                    c["acoustic_hint"] = f"unknown ({dur:.2f}s, không đủ tín hiệu)"

                if voc_g in {"male", "female"}:
                    c["speaker_label"] = "Nam" if voc_g == "male" else "Nữ"
                    c["gender"] = voc_g
                elif rg in {"male", "female"} and rc >= min_acoustic_conf:
                    c["speaker_label"] = "Nam" if rg == "male" else "Nữ"
                    c["gender"] = rg
                elif cont_g in {"male", "female"} and (rc < 0.65 or rg == "unknown"):
                    c["speaker_label"] = "Nam" if cont_g == "male" else "Nữ"
                    c["gender"] = cont_g
                else:
                    # FIX: Không gán nhãn cứng khi confidence thấp → để DeepSeek tự phán đoán
                    c["speaker_label"] = "Chưa rõ"
                    c["gender"] = "unknown"

            # 4.5 Tự động ghép nối các vế câu dở dang nói liền nhau (Incomplete Split Clauses)
            detected = SubtitleMergeService.merge_incomplete_split_dialogues(detected)
            for new_idx, c in enumerate(detected, start=1):
                c["id"] = new_idx

            # 4.6 3D-Speaker Voiceprint Clustering (Alibaba ERes2Net Embeddings)
            notify("Đang phân tích vector giọng nói & gom cụm nhân vật (3D-Speaker Clustering)…")
            try:
                from services.speaker_embedding_clusterer import SpeakerEmbeddingClusterer
                detected = SpeakerEmbeddingClusterer().cluster_cues(audio_path, detected, similarity_threshold=0.35)
            except Exception as cluster_err:
                print(f"[Voice Gender Check] Speaker clustering notice: {cluster_err}")

            # 4.7 Đồng bộ nhãn sơ bộ cho DeepSeek dựa trên cụm âm sắc ERes2Net
            for c in detected:
                cl_f = float(c.get("cluster_female_ratio", 0.5) or 0.5)
                cl_m = float(c.get("cluster_male_ratio", 0.5) or 0.5)
                rc = float(c.get("raw_gender_confidence", 0.0) or 0.0)
                if rc > 1.0:
                    rc /= 100.0
                if cl_f >= 0.75 and rc < 0.70:
                    c["speaker_label"] = "Nữ"
                    c["gender"] = "female"
                elif cl_m >= 0.75 and rc < 0.70:
                    c["speaker_label"] = "Nam"
                    c["gender"] = "male"

            # 5. Dịch kịch bản & phân vai ngữ cảnh (Hỗ trợ đa mô hình: Gemini, ChatGPT, DeepSeek, Ollama)
            from services.deepseek_service import DeepSeekService
            llm_svc = DeepSeekService()
            llm_name = llm_svc.display_name
            notify(f"Đang dịch kịch bản & phân tích vai nhân vật ({llm_name})…")

            translated_cues = []
            llm_genders: dict[int, str] = {}

            from services.subtitle_translation_service import SubtitleTranslationService
            if llm_svc.is_configured():
                try:
                    sub_trans_svc = SubtitleTranslationService(llm_svc)
                    translated_cues, _ = sub_trans_svc.translate_with_deepseek(
                        detected,
                        overwrite_manual=True,
                        progress=lambda msg, cur, tot: notify(f"{llm_name} đang dịch & phân vai ngữ cảnh ({cur}/{tot})…"),
                    )
                    for tc in translated_cues:
                        cid = tc.get("id")
                        g = str(tc.get("gender", "") or "").lower().strip()
                        if g in {"male", "female"}:
                            llm_genders[cid] = g
                except Exception as llm_err:
                    print(f"[Voice Gender Check] {llm_name} translation warning: {llm_err}")
                    translated_cues = []
            else:
                print(f"[Voice Gender Check] Chưa cấu hình API Key cho {llm_name}, chuyển sang bộ dịch dự phòng.")

            if not translated_cues:
                translated_cues = SubtitleTranslationService().translate_cues(
                    detected,
                    target_lang="vi",
                    progress=notify,
                )

            # Ghép lại bản dịch vào detected
            trans_by_id = {c.get("id"): c for c in translated_cues}
            merged_cues = []
            for c in detected:
                cid = c.get("id")
                tc = trans_by_id.get(cid) or {}
                merged_cues.append({
                    **c,
                    "translated_text": tc.get("translated_text", c.get("translated_text", "")),
                    "is_noise": tc.get("is_noise", c.get("is_noise", False)),
                    "deepseek_gender": llm_genders.get(cid, ""),
                    "llm_gender": llm_genders.get(cid, ""),
                })

            # 6. Anchor-Based Temporal Smoothing kết hợp LLM Continuity (Gemini/ChatGPT/DeepSeek)
            from services.temporal_gender_smoothing import TemporalGenderSmoothingService
            continuity_groups = []
            if llm_genders:
                cur_grp = []
                cur_g = None
                for cue in merged_cues:
                    cid = cue.get("id")
                    lg = llm_genders.get(cid)
                    if lg and lg == cur_g:
                        cur_grp.append(cid)
                    else:
                        if len(cur_grp) >= 2:
                            continuity_groups.append({"ids": cur_grp, "same_speaker_likelihood": 0.95})
                        cur_grp = [cid] if lg else []
                        cur_g = lg
                if len(cur_grp) >= 2:
                    continuity_groups.append({"ids": cur_grp, "same_speaker_likelihood": 0.95})

            smoothed_detected = TemporalGenderSmoothingService.smooth(
                merged_cues,
                continuity_groups=continuity_groups
            )

            # 7. Decision Fusion Logic (Nơi DUY NHẤT quyết định final_gender)
            from services.decision_fusion_service import DecisionFusionService
            final_fused_cues = DecisionFusionService.fuse(
                smoothed_detected,
                deepseek_genders=llm_genders,
                deepseek_continuity=continuity_groups,
                llm_genders=llm_genders,
                llm_continuity=continuity_groups,
                llm_provider_name=llm_name,
            )

            # 7. Assemble Voice Check Result
            rows: list[dict[str, Any]] = []
            counts = {"male": 0, "female": 0, "none": 0, "unknown": 0}
            for index, cue in enumerate(final_fused_cues, start=1):
                gender = str(cue.get("final_gender") or cue.get("gender", "unknown") or "unknown").lower()
                source = str(cue.get("source", "gender-ai-windows") or "gender-ai-windows")
                confidence = float(cue.get("final_decision_confidence") or cue.get("confidence", 0.0) or 0.0)
                # If confidence is in [0, 1], express as percentage (e.g. 98.7)
                confidence_pct = round(confidence * 100.0 if confidence <= 1.0 else confidence, 1)

                raw_g = str(cue.get("raw_gender", gender) or gender).lower()
                raw_c = float(cue.get("raw_gender_confidence", 0.0) or 0.0)
                raw_c_pct = round(raw_c * 100.0 if raw_c <= 1.0 else raw_c, 1)

                if gender not in {"male", "female", "none"}:
                    gender = "unknown"
                counts[gender] += 1

                cue_text = str(cue.get("text", "") or cue.get("original_text", "") or "").strip()
                translated_text = str(cue.get("translated_text", "") or "").strip()
                merged_from = list(cue.get("merged_from") or [cue.get("id", index)])

                raw_id = str(cue.get("id", index) or index).split(":", 1)[0]
                try:
                    cue_id = int(raw_id)
                except (ValueError, TypeError):
                    cue_id = index

                rows.append({
                    "id": cue_id,
                    "index": index,
                    "start": round(float(cue.get("start", 0.0) or 0.0), 3),
                    "end": round(float(cue.get("end", 0.0) or 0.0), 3),
                    "original_text": cue_text,
                    "text": cue_text,
                    "translated_text": translated_text,
                    "speaker": str(cue.get("speaker", "") or "").strip(),
                    "gender": gender,
                    "confidence": confidence_pct,
                    "raw_gender": raw_g,
                    "raw_gender_confidence": raw_c_pct,
                    "final_gender": gender,
                    "final_decision_confidence": confidence_pct,
                    "decision_mode": str(cue.get("decision_mode", "raw_audio")),
                    "audio_quality": str(cue.get("audio_quality", "clean")),
                    "speech_duration": float(cue.get("speech_duration", 0.0) or 0.0),
                    "speech_ratio": float(cue.get("speech_ratio", 0.0) or 0.0),
                    "music_score": float(cue.get("music_score", 0.0) or 0.0),
                    "gender_reason": list(cue.get("gender_reason", []) or []),
                    "alignment_confidence": 1.0,
                    "source": source,
                    "status": str(cue.get("status", "ok") or "ok"),
                    "merged_from": merged_from,
                    "skip_tts": bool(cue.get("skip_tts", False)),
                })

        return {
            "video_path": os.path.abspath(video_path),
            "rows": rows,
            "counts": counts,
            "speaker_profiles": {},
        }

    @staticmethod
    def _filter_ocr_noise(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove Latin hallucinations when the burned subtitles are CJK.

        OCR can interpret clothing, railings, compression blocks, or an overlay
        behind the subtitle as long English phrases. This filter is deliberately
        enabled only when CJK is clearly the dominant subtitle script.
        """
        texts = [str(cue.get("text", "") or "").strip() for cue in cues]
        cjk_chars = sum(len(re.findall(r"[\u3400-\u9fff]", text)) for text in texts)
        cjk_cues = sum(bool(re.search(r"[\u3400-\u9fff]", text)) for text in texts)
        cjk_dominant = cjk_chars >= 6 and cjk_cues >= max(2, len(texts) * 0.5)
        if not cjk_dominant:
            return cues

        # Pattern nhận diện bìa sách giáo khoa, bài tập, poster tài liệu học sinh trên bàn
        book_cover_keywords = (
            "名师", "课时", "助力学生", "学生得优", "情境设", "真题", "养提升", "提升",
            "创新", "视频精讲", "五年级", "六年级", "七年级", "八年级", "九年级", "小学数学",
            "同步练习", "模拟卷", "必刷题", "重难点", "单元测试", "学年", "测试卷",
        )

        # Pattern nhận diện màn hình app điện thoại / bài giải toán app Zuoyebang
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
        PREFIX_CLEAN_PATTERNS = [
            r"^观看视频讲\s*如何统计人数[？?]\s*我\s*",
            r"^你知道统计人数的方\s*怎样记录书哥偏好人数[？?]\s*厨配统计表\s*",
        ]

        cleaned: list[dict[str, Any]] = []
        for cue in cues:
            item = dict(cue)
            text = str(item.get("text", "") or "").strip()
            if not re.search(r"[\u3400-\u9fff]", text):
                continue

            # 1. Clean prefix rác UI dính ở đầu phụ đề (ví dụ app Zuoyebang trên điện thoại)
            for pat in PREFIX_CLEAN_PATTERNS:
                text = re.sub(pat, "", text).strip()

            cjk_chars = re.findall(r"[\u3400-\u9fff]", text)
            cjk_len = len(cjk_chars)
            if cjk_len == 0:
                continue

            st = float(item.get("start", 0.0) or 0.0)
            en = float(item.get("end", 0.0) or 0.0)
            dur = max(0.2, en - st)
            rate = cjk_len / dur

            # 2. Lọc bỏ tuyệt đối các cụm từ đặc trưng chỉ có trên màn hình điện thoại / bìa sách / app giải toán
            is_strong_noise = any(kw in text for kw in STRONG_SCREEN_NOISE)
            if is_strong_noise:
                continue

            ui_kw_count = sum(1 for kw in PHONE_UI_KEYWORDS if kw in text)
            if ui_kw_count >= 2:
                continue
            if ui_kw_count >= 1 and (cjk_len >= 18 or rate >= 10.0):
                continue

            if re.search(r"(?:克创新|究创新|农究创新|视频精讲|山东名师|课时证|得优|真题度|助力学生|五年级|六年级|七年级|八年级|九年级)", text):
                continue
            if re.search(r"(?:数学|语文|英语|物理|化学|生物)\s*$", text) and cjk_len <= 8 and not any(w in text for w in ["学", "做", "考", "上", "教", "读", "题", "课"]):
                continue

            # Đếm số từ khóa sách vở/giáo trình
            book_kw_count = sum(1 for kw in book_cover_keywords if kw in text)
            if book_kw_count >= 2 or (cjk_len >= 18 and book_kw_count >= 1):
                continue

            text = re.sub(r"[A-Za-z]+(?:[ '\u2019-][A-Za-z]+)*", " ", text)
            text = re.sub(r"\s+", " ", text).strip(" ,.;:|_-")
            if text:
                item["text"] = text
                item["original_text"] = text
                cleaned.append(item)
        return cleaned

    @staticmethod
    def _merge_fuzzy_duplicate_cues(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Ủy quyền sang FuzzyDuplicateService độc lập theo kiến trúc Clean Architecture."""
        from services.fuzzy_duplicate_service import FuzzyDuplicateService
        return FuzzyDuplicateService.merge_fuzzy_cues(cues)

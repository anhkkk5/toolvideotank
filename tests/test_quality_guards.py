import os
import sys
import types
import unittest
import os
import tempfile
import wave
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "app"))

# The quality parsers do not need optional runtime/API dependencies.
if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub
if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    sys.modules["openai"] = openai_stub

from app.services.hybrid_audio_ocr_fusion import (  # noqa: E402
    _asr_is_reliable,
    _looks_corrupt_ocr,
    _merge_near_duplicate_ocr,
    _normalize_timeline,
)
from app.services.subtitle_speaker_aligner import align_subtitles_to_speakers  # noqa: E402
from app.services.speaker_diarization_service import SpeakerDiarizationService  # noqa: E402
from app.services.openai_speaker_analysis_service import OpenAISpeakerAnalysisService  # noqa: E402
from app.services.character_voice_resolver import CharacterVoiceResolver  # noqa: E402
from app.services.character_segment_splitter import CharacterSegmentSplitter  # noqa: E402
from app.services.character_correction_service import CharacterCorrectionService  # noqa: E402
from app.services.character_integrity_gate import CharacterIntegrityGate  # noqa: E402
from app.services.post_ocr_character_resolver import PostOCRCharacterResolver  # noqa: E402
from app.services.smart_cast import auto_cast_speakers  # noqa: E402
from app.core.models.segment import Segment  # noqa: E402
from app.services.segment_service import SegmentService  # noqa: E402
from app.translation.errors import TranslationValidationError  # noqa: E402
from app.translation.providers.gemini_polisher import (  # noqa: E402
    parse_translation_response,
    validate_target_language_lines,
)


class HybridQualityGuardTests(unittest.TestCase):
    def test_temporal_continuity_repairs_only_bracketed_unknown_turn(self):
        turns, count = PostOCRCharacterResolver.apply_temporal_continuity([
            {"start": 18.0, "end": 20.1, "character_id": "CHAR_00", "character_gender": "female", "character_confidence": 0.9},
            {"start": 20.5, "end": 21.5, "character_id": "UNKNOWN", "character_gender": "unknown", "character_confidence": 0.0},
            {"start": 21.53, "end": 22.5, "character_id": "CHAR_00", "character_gender": "female", "character_confidence": 0.9},
        ])
        self.assertEqual(1, count)
        self.assertEqual("CHAR_00", turns[1]["character_id"])
        self.assertEqual("female", turns[1]["character_gender"])
        self.assertEqual("temporal_continuity", turns[1]["character_source"])

    def test_temporal_continuity_does_not_cross_character_change(self):
        turns, count = PostOCRCharacterResolver.apply_temporal_continuity([
            {"start": 0.0, "end": 1.0, "character_id": "CHAR_00", "character_gender": "female", "character_confidence": 0.9},
            {"start": 1.1, "end": 1.5, "character_id": "UNKNOWN"},
            {"start": 1.6, "end": 2.0, "character_id": "CHAR_01", "character_gender": "male", "character_confidence": 0.9},
        ])
        self.assertEqual(0, count)
        self.assertEqual("UNKNOWN", turns[1]["character_id"])

    def test_detects_trailing_digit_and_mixed_script_ocr_damage(self):
        self.assertTrue(_looks_corrupt_ocr("你要是有钱就好7"))
        self.assertTrue(_looks_corrupt_ocr("担心 最后的拥抱 wthe op ae o romanic People"))
        self.assertFalse(_looks_corrupt_ocr("我们在一起吧"))

    def test_rejects_low_confidence_or_repetitive_asr(self):
        self.assertFalse(_asr_is_reliable({"text": "hello hello hello hello hello", "avg_logprob": -0.2}))
        self.assertFalse(_asr_is_reliable({"text": "正常句子", "avg_logprob": -1.2}))
        self.assertFalse(_asr_is_reliable({"text": "正常句子", "avg_logprob": -0.2, "no_speech_prob": 0.8}))
        self.assertTrue(_asr_is_reliable({"text": "我们在一起吧", "avg_logprob": -0.2, "no_speech_prob": 0.1}))

    def test_merges_near_duplicate_ocr_and_makes_timeline_monotonic(self):
        merged = _merge_near_duplicate_ocr([
            {"start": 0.0, "end": 1.0, "text": "我们在一起吧"},
            {"start": 0.5, "end": 1.5, "text": "我们在一起吧。"},
        ])
        self.assertEqual(1, len(merged))
        normalized = _normalize_timeline(merged + [{"start": 1.0, "end": 2.0, "text": "下一句"}])
        self.assertGreaterEqual(normalized[1]["start"], normalized[0]["end"])

    def test_low_confidence_speaker_fallback_is_not_presented_as_certain(self):
        result = align_subtitles_to_speakers(
            [{"start": 5.0, "end": 6.0, "text": "x"}],
            [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_01"}],
        )
        self.assertLess(result[0]["speaker_confidence"], 0.35)

    def test_meaningful_overlap_wins_over_nearer_previous_speaker(self):
        # Regression from the real project: the female turn covers 0.67s of a
        # 2s OCR cue. The old 0.35 ratio threshold rejected it and incorrectly
        # selected the temporally nearer male turn.
        result = align_subtitles_to_speakers(
            [{"start": 6.5, "end": 8.5, "text": "什么事啊"}],
            [
                {"start": 4.91, "end": 6.06, "speaker": "SPEAKER_00"},
                {"start": 6.24, "end": 7.17, "speaker": "SPEAKER_01"},
            ],
        )
        self.assertEqual("SPEAKER_01", result[0]["speaker"])

    def test_character_id_replaces_temporary_audio_speaker(self):
        result = align_subtitles_to_speakers(
            [{"start": 1.0, "end": 2.0, "text": "x"}],
            [{
                "start": 0.9,
                "end": 2.1,
                "speaker": "SPEAKER_00",
                "character_id": "CHAR_04",
                "character_gender": "female",
                "character_confidence": 0.91,
            }],
        )
        self.assertEqual("CHAR_04", result[0]["speaker"])
        self.assertEqual("SPEAKER_00", result[0]["audio_speaker"])
        self.assertEqual("female", result[0]["character_gender"])

    def test_character_assignment_survives_segment_round_trip(self):
        source = {
            "start": 1.0,
            "end": 2.0,
            "text": "x",
            "speaker": "CHAR_04",
            "audio_speaker": "SPEAKER_00",
            "speaker_confidence": 0.72,
            "character_id": "CHAR_04",
            "character_gender": "female",
            "character_confidence": 0.91,
            "character_source": "visual_active_speaker",
        }
        restored = Segment.from_transcript_dict(source, segment_id=1).to_original_subtitle_dict()
        for key in (
            "speaker", "audio_speaker", "speaker_confidence", "character_id",
            "character_gender", "character_confidence", "character_source",
        ):
            self.assertEqual(source[key], restored[key])

    def test_character_assignment_survives_translation_merge(self):
        source = Segment.from_transcript_dict({
            "start": 1.0, "end": 2.0, "text": "x", "speaker": "CHAR_02",
            "audio_speaker": "SPEAKER_03", "speaker_confidence": 0.8,
            "character_id": "CHAR_02", "character_gender": "male",
            "character_confidence": 0.9, "character_source": "visual",
        }, segment_id=1)
        translated = SegmentService().apply_translations(
            [source], [{"start": 1.0, "end": 2.0, "text": "xin chao", "speaker": "CHAR_02"}]
        )[0].to_subtitle_dict()
        self.assertEqual(0.9, translated["character_confidence"])
        self.assertEqual("male", translated["character_gender"])
        self.assertEqual("SPEAKER_03", translated["audio_speaker"])


class SmartCastTests(unittest.TestCase):
    def test_all_speakers_of_same_gender_share_one_voice(self):
        segments = [
            {"start": 0, "end": 1, "speaker": "SPEAKER_00", "speaker_confidence": 1.0},
            {"start": 1, "end": 2, "speaker": "SPEAKER_01", "speaker_confidence": 1.0},
            {"start": 2, "end": 3, "speaker": "SPEAKER_02", "speaker_confidence": 1.0},
            {"start": 3, "end": 4, "speaker": "SPEAKER_03", "speaker_confidence": 1.0},
        ]
        mapping, _profiles = auto_cast_speakers(
            segments,
            gender_overrides={
                "SPEAKER_00": "male",
                "SPEAKER_01": "female",
                "SPEAKER_02": "female",
                "SPEAKER_03": "female",
            },
        )
        self.assertEqual("vieneu_thanhnientutin", mapping["SPEAKER_00"])
        self.assertEqual(
            {"vieneu_cogaihoatbat"},
            {mapping[key] for key in ("SPEAKER_01", "SPEAKER_02", "SPEAKER_03")},
        )


class OpenAISpeakerAnalysisTests(unittest.TestCase):
    def test_merges_singleton_fragment_surrounded_by_same_speaker(self):
        turns = [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
            {"start": 1.1, "end": 1.7, "speaker": "SPEAKER_03"},
            {"start": 1.8, "end": 3.0, "speaker": "SPEAKER_00"},
        ]
        fixed = OpenAISpeakerAnalysisService._stabilize_singleton_speakers(turns)
        self.assertEqual({"SPEAKER_00"}, {x["speaker"] for x in fixed})

    def test_normalizes_diarized_response_and_counts_speakers(self):
        handle, audio_path = tempfile.mkstemp(suffix=".wav")
        os.close(handle)
        try:
            with wave.open(audio_path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(b"\x00\x00" * 32000)

            response = type("Response", (), {"segments": [
                {"speaker": "A", "start": 0.0, "end": 1.0, "text": "one"},
                {"speaker": "B", "start": 1.0, "end": 2.0, "text": "two"},
            ]})()
            create = mock.Mock(return_value=response)
            fake_client = type("Client", (), {
                "audio": type("Audio", (), {
                    "transcriptions": type("Transcriptions", (), {"create": create})()
                })()
            })()
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}, clear=False), \
                    mock.patch("openai.OpenAI", return_value=fake_client):
                result = OpenAISpeakerAnalysisService().analyze(audio_path)

            self.assertEqual(2, result["summary"]["speaker_count"])
            self.assertEqual(["SPEAKER_00", "SPEAKER_01"], [x["speaker"] for x in result["turns"]])
            self.assertEqual("diarized_json", create.call_args.kwargs["response_format"])
            self.assertEqual("auto", create.call_args.kwargs["chunking_strategy"])
        finally:
            os.unlink(audio_path)

    def test_character_resolver_batches_vision_requests(self):
        turns = [
            {"start": float(index), "end": float(index + 1), "speaker": f"SPEAKER_{index % 2:02d}", "text": "x"}
            for index in range(5)
        ]
        payloads = [
            {"turns": [{"turn_index": 0, "character_id": "CHAR_01", "voice_category": "male", "confidence": 0.9},
                       {"turn_index": 1, "character_id": "CHAR_02", "voice_category": "female", "confidence": 0.9}]},
            {"turns": [{"turn_index": 2, "character_id": "CHAR_01", "voice_category": "male", "confidence": 0.9},
                       {"turn_index": 3, "character_id": "CHAR_02", "voice_category": "female", "confidence": 0.9}]},
            {"turns": [{"turn_index": 4, "character_id": "CHAR_01", "voice_category": "male", "confidence": 0.9}]},
        ]
        responses = [
            type("Response", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": __import__('json').dumps(payload)})()})()]})()
            for payload in payloads
        ]
        create = mock.Mock(side_effect=responses)
        fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": type("Completions", (), {"create": create})()})()})()
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video, \
                mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-only", "OPENAI_CHARACTER_BATCH_SIZE": "2"}, clear=False), \
                mock.patch("openai.OpenAI", return_value=fake_client), \
                mock.patch.object(OpenAISpeakerAnalysisService, "_frame_data_url", return_value="data:image/jpeg;base64,AA=="):
            result = OpenAISpeakerAnalysisService().resolve_characters(
                video.name, {"summary": {}, "turns": turns}
            )
        self.assertEqual(3, create.call_count)
        self.assertEqual(5, len(result["turns"]))
        self.assertEqual(2, result["character_summary"]["character_count"])
        self.assertEqual(3, result["character_summary"]["version"])

    def test_short_ocr_lead_in_inherits_immediately_following_character(self):
        turns, count = PostOCRCharacterResolver.apply_temporal_continuity([
            {"start": 107.5, "end": 108.5, "character_id": "UNKNOWN", "character_gender": "unknown", "character_source": "visual_active_speaker"},
            {"start": 108.5, "end": 111.5, "character_id": "CHAR_01", "character_gender": "female", "character_confidence": 0.9},
        ])
        self.assertEqual(1, count)
        self.assertEqual("CHAR_01", turns[0]["character_id"])
        self.assertEqual("female", turns[0]["character_gender"])

    def test_contiguous_unknown_ocr_chain_propagates_back_from_anchor(self):
        turns, count = PostOCRCharacterResolver.apply_temporal_continuity([
            {"start": 107.5, "end": 108.5, "character_id": "UNKNOWN", "character_source": "visual_active_speaker"},
            {"start": 108.5, "end": 111.5, "character_id": "UNKNOWN", "character_source": "visual_active_speaker"},
            {"start": 111.5, "end": 113.5, "character_id": "CHAR_00", "character_gender": "female", "character_confidence": 0.9},
        ])
        self.assertEqual(2, count)
        self.assertEqual(["CHAR_00", "CHAR_00", "CHAR_00"], [item["character_id"] for item in turns])


class CharacterCorrectionServiceTests(unittest.TestCase):
    def test_phase4_manual_correction_overrides_matching_turn(self):
        result = {
            "turns": [
                {"start": 5.0, "end": 6.5, "speaker": "SPEAKER_00", "character_id": "CHAR_01", "character_gender": "male"},
                {"start": 7.0, "end": 8.0, "speaker": "SPEAKER_00", "character_id": "CHAR_01", "character_gender": "male"},
            ],
            "characters": [
                {"character_id": "CHAR_01", "gender": "male"},
                {"character_id": "CHAR_02", "gender": "female"},
            ],
            "character_summary": {"version": 3},
        }
        corrections = [{"start": 5.1, "end": 6.4, "character_id": "CHAR_02", "character_gender": "female"}]
        corrected = CharacterCorrectionService.apply(result, corrections)
        self.assertEqual("CHAR_02", corrected["turns"][0]["character_id"])
        self.assertEqual("manual_correction", corrected["turns"][0]["character_source"])
        self.assertEqual(1.0, corrected["turns"][0]["character_confidence"])
        self.assertEqual("CHAR_01", corrected["turns"][1]["character_id"])
        self.assertEqual(4, corrected["character_summary"]["version"])

    def test_phase4_upsert_replaces_same_timed_correction(self):
        corrections = CharacterCorrectionService.upsert([], {
            "start": 1.0, "end": 2.0, "character_id": "CHAR_01"
        })
        corrections = CharacterCorrectionService.upsert(corrections, {
            "start": 1.01, "end": 2.01, "character_id": "CHAR_02"
        })
        self.assertEqual(1, len(corrections))
        self.assertEqual("CHAR_02", corrections[0]["character_id"])

    def test_phase4_review_queue_only_contains_uncertain_rows(self):
        queue = CharacterCorrectionService.build_review_queue([
            {"start": 0, "end": 1, "character_id": "CHAR_01", "character_confidence": 0.95, "text": "ok"},
            {"start": 1, "end": 2, "character_id": "UNKNOWN", "character_confidence": 0.1, "text": "unknown"},
            {"start": 2, "end": 3, "character_id": "CHAR_02", "character_confidence": 0.70, "text": "weak"},
            {"start": 3, "end": 4, "character_id": "CHAR_02", "character_confidence": 1.0, "character_source": "manual_correction"},
        ])
        self.assertEqual([1, 2], [item["segment_index"] for item in queue])


class PostOCRCharacterResolverTests(unittest.TestCase):
    def test_creates_turn_only_for_cue_missed_by_diarization(self):
        cues = [
            {"start": 0.0, "end": 1.0, "text": "covered"},
            {"start": 5.0, "end": 6.0, "text": "missing"},
        ]
        turns = [{"start": 0.1, "end": 0.9, "speaker": "SPEAKER_00"}]
        combined, report = PostOCRCharacterResolver.augment_turns(cues, turns)
        self.assertEqual(1, report["gap_count"])
        self.assertEqual(2, len(combined))
        gap = next(item for item in combined if item.get("turn_origin") == "post_ocr_gap")
        self.assertEqual("OCR_GAP_0001", gap["speaker"])
        self.assertEqual("missing", gap["text"])
        self.assertEqual("UNKNOWN", gap["character_id"])

    def test_partial_overlap_above_threshold_is_covered(self):
        cues = [{"start": 10.0, "end": 12.0, "text": "dialogue"}]
        turns = [{"start": 10.0, "end": 10.6, "speaker": "SPEAKER_00"}]
        _, report = PostOCRCharacterResolver.augment_turns(cues, turns)
        self.assertEqual(0, report["gap_count"])


class CharacterIntegrityGateTests(unittest.TestCase):
    def test_passes_resolved_gendered_consistent_character(self):
        report = CharacterIntegrityGate.inspect([{
            "start": 0.0,
            "end": 1.0,
            "character_id": "CHAR_01",
            "character_gender": "male",
            "character_confidence": 0.91,
            "voice_name": "male_voice",
        }])
        self.assertTrue(report["passed"])
        self.assertEqual(0, report["issue_count"])

    def test_blocks_unknown_and_same_character_with_two_voices(self):
        report = CharacterIntegrityGate.inspect([
            {
                "start": 0.0, "end": 1.0, "character_id": "UNKNOWN",
                "character_gender": "unknown", "character_confidence": 0.0,
            },
            {
                "start": 1.0, "end": 2.0, "character_id": "CHAR_01",
                "character_gender": "female", "character_confidence": 0.9,
                "voice_name": "voice_a",
            },
            {
                "start": 2.0, "end": 3.0, "character_id": "CHAR_01",
                "character_gender": "female", "character_confidence": 0.9,
                "voice_name": "voice_b",
            },
        ])
        self.assertFalse(report["passed"])
        self.assertEqual(2, report["issue_count"])
        self.assertIn("character_voice_conflict", report["issues"][1]["reasons"])


class CharacterSegmentSplitterTests(unittest.TestCase):
    def test_phase3_splits_one_audio_turn_between_two_active_characters(self):
        turns = [{"start": 10.0, "end": 15.0, "speaker": "SPEAKER_00", "text": "dialogue"}]
        assignments = {0: {"spans": [
            {"start": 10.0, "end": 12.1, "character_id": "CHAR_02", "voice_category": "female", "confidence": 0.93},
            {"start": 12.1, "end": 15.0, "character_id": "CHAR_04", "voice_category": "female", "confidence": 0.91},
        ]}}
        split, stats = CharacterSegmentSplitter.split_turns(turns, assignments)
        self.assertEqual(2, len(split))
        self.assertEqual(["CHAR_02", "CHAR_04"], [item["character_id"] for item in split])
        self.assertEqual({"SPEAKER_00"}, {item["speaker"] for item in split})
        self.assertEqual(1, stats["split_turn_count"])

    def test_phase3_preserves_unknown_gap_for_phase2(self):
        turns = [{"start": 0.0, "end": 4.0, "speaker": "SPEAKER_00"}]
        assignments = {0: {"spans": [
            {"start": 0.0, "end": 1.5, "character_id": "CHAR_01", "voice_category": "male", "confidence": 0.9},
            {"start": 2.5, "end": 4.0, "character_id": "CHAR_02", "voice_category": "female", "confidence": 0.9},
        ]}}
        split, _ = CharacterSegmentSplitter.split_turns(turns, assignments)
        self.assertEqual(["CHAR_01", "UNKNOWN", "CHAR_02"], [item["character_id"] for item in split])
        self.assertEqual("unresolved", split[1]["character_source"])


class CharacterVoiceResolverTests(unittest.TestCase):
    def test_phase2_resolves_unknown_with_clear_voice_match(self):
        result = {
            "turns": [
                {"start": 0, "end": 1, "character_id": "CHAR_01", "character_gender": "male", "character_confidence": 0.95},
                {"start": 1, "end": 2, "character_id": "CHAR_02", "character_gender": "female", "character_confidence": 0.92},
                {"start": 2, "end": 3, "character_id": "UNKNOWN", "character_confidence": 0.1},
            ],
            "characters": [
                {"character_id": "CHAR_01", "gender": "male"},
                {"character_id": "CHAR_02", "gender": "female"},
            ],
        }
        resolver = CharacterVoiceResolver(similarity_threshold=0.70, margin_threshold=0.08)
        resolved, artifact = resolver.resolve_from_embeddings(
            result, {0: [1.0, 0.0], 1: [0.0, 1.0], 2: [0.03, 0.99]}
        )
        self.assertEqual("CHAR_02", resolved["turns"][2]["character_id"])
        self.assertEqual("female", resolved["turns"][2]["character_gender"])
        self.assertEqual("voice_embedding", resolved["turns"][2]["character_source"])
        self.assertEqual(1, resolved["character_summary"]["voice_resolved_turn_count"])
        self.assertEqual(2, len(artifact["prototypes"]))

    def test_phase2_keeps_ambiguous_turn_unknown(self):
        result = {
            "turns": [
                {"start": 0, "end": 1, "character_id": "CHAR_01", "character_confidence": 0.95},
                {"start": 1, "end": 2, "character_id": "CHAR_02", "character_confidence": 0.95},
                {"start": 2, "end": 3, "character_id": "UNKNOWN", "character_confidence": 0.0},
            ],
            "characters": [
                {"character_id": "CHAR_01", "gender": "male"},
                {"character_id": "CHAR_02", "gender": "female"},
            ],
        }
        resolver = CharacterVoiceResolver(similarity_threshold=0.60, margin_threshold=0.15)
        resolved, _ = resolver.resolve_from_embeddings(
            result, {0: [1.0, 0.0], 1: [0.0, 1.0], 2: [0.7, 0.7]}
        )
        self.assertEqual("UNKNOWN", resolved["turns"][2]["character_id"])
        self.assertEqual(0, resolved["character_summary"]["voice_resolved_turn_count"])

    def test_phase2_rerun_does_not_train_on_its_own_prediction(self):
        result = {
            "turns": [
                {"start": 0, "end": 1, "character_id": "CHAR_01", "character_confidence": 0.95, "character_source": "visual"},
                {"start": 1, "end": 2, "character_id": "CHAR_02", "character_confidence": 0.95, "character_source": "visual"},
                {"start": 2, "end": 3, "character_id": "CHAR_02", "character_confidence": 0.94, "character_source": "voice_embedding"},
            ],
            "characters": [
                {"character_id": "CHAR_01", "gender": "male"},
                {"character_id": "CHAR_02", "gender": "female"},
            ],
        }
        resolver = CharacterVoiceResolver(similarity_threshold=0.70, margin_threshold=0.08)
        resolved, artifact = resolver.resolve_from_embeddings(
            result, {0: [1.0, 0.0], 1: [0.0, 1.0], 2: [0.02, 0.99]}
        )
        char2 = next(item for item in artifact["prototypes"] if item["character_id"] == "CHAR_02")
        self.assertEqual(1, char2["sample_count"])
        self.assertEqual("CHAR_02", resolved["turns"][2]["character_id"])
        self.assertEqual(1, resolved["character_summary"]["voice_resolved_turn_count"])


class TranslationValidationTests(unittest.TestCase):
    def test_partial_numbered_response_is_rejected(self):
        with self.assertRaises(TranslationValidationError):
            parse_translation_response("1. Dòng duy nhất", 2)

    def test_complete_numbered_response_is_accepted(self):
        self.assertEqual(
            ["Một", "Hai"],
            parse_translation_response("1. Một\n2. Hai", 2),
        )

    def test_untranslated_chinese_line_is_rejected_for_vietnamese(self):
        with self.assertRaises(TranslationValidationError):
            validate_target_language_lines(["没出啥事吧"], ["没出啥事吧"], "vi")

    def test_vietnamese_translation_is_accepted(self):
        validate_target_language_lines(["没出啥事吧"], ["Không có chuyện gì chứ?"], "vi")


if __name__ == "__main__":
    unittest.main()

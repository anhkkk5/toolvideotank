from unittest.mock import patch

from services.voice_gender_check_service import VoiceGenderCheckService


def test_voice_gender_check_aligns_original_ocr_text_to_gender(tmp_path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")

    cues = [
        {"start": 0.0, "end": 1.0, "text": "你好"},
        {"start": 1.0, "end": 2.0, "text": "再见"},
    ]
    def fake_extract(_self, _video_path, audio_path):
        with open(audio_path, "wb") as handle:
            handle.write(b"wav")
        return True

    with (
        patch("services.voice_gender_check_service.EngineRuntime.extract_audio", fake_extract),
        patch("services.voice_gender_check_service.EngineRuntime.transcribe_video_ocr", return_value=cues),
        patch("services.voice_gender_check_service.GenderService") as gender_class,
    ):
        gender_class.return_value.detect_cues.return_value = [
            {**cues[0], "id": 1, "gender": "male", "confidence": 0.99, "source": "gender-ai-windows"},
            {**cues[1], "id": 2, "gender": "female", "confidence": 0.98, "source": "gender-ai-windows"},
        ]
        result = VoiceGenderCheckService().run(str(video))

    assert [row["text"] for row in result["rows"]] == ["你好", "再见"]
    assert [row["gender"] for row in result["rows"]] == ["male", "female"]
    assert result["counts"] == {"male": 1, "female": 1, "none": 0, "unknown": 0}


def test_voice_gender_check_reuses_existing_cues(tmp_path):
    video = tmp_path / "source2.mp4"
    video.write_bytes(b"video2")

    existing = [
        {"start": 0.5, "end": 1.5, "text": "现有字幕1"},
        {"start": 4.0, "end": 5.0, "text": "现有字幕2"},
    ]
    def fake_extract(_self, _video_path, audio_path):
        with open(audio_path, "wb") as handle:
            handle.write(b"wav")
        return True

    with (
        patch("services.voice_gender_check_service.EngineRuntime.extract_audio", fake_extract),
        patch("services.voice_gender_check_service.EngineRuntime.transcribe_video_ocr") as mock_ocr,
        patch("services.voice_gender_check_service.GenderService") as gender_class,
    ):
        gender_class.return_value.detect_cues.return_value = [
            {**existing[0], "id": 1, "gender": "male", "confidence": 0.95, "source": "gender-ai-windows"},
            {**existing[1], "id": 2, "gender": "female", "confidence": 0.92, "source": "gender-ai-windows"},
        ]
        result = VoiceGenderCheckService().run(str(video), existing_cues=existing)

        # Đảm bảo KHÔNG gọi OCR khi đã có existing_cues
        mock_ocr.assert_not_called()

    assert len(result["rows"]) == 2
    assert result["rows"][0]["text"] == "现有字幕1"

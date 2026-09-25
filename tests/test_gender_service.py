from services.gender_service import GenderService


def test_music_is_normalized_to_none():
    result = GenderService.normalize_result({
        "gender": "unknown",
        "confidence": 0.0,
        "status": "music_or_non_speech",
    })
    assert result["gender"] == "none"
    assert result["skip_tts"] is True


def test_window_consensus_requires_two_non_conflicting_votes(tmp_path):
    package = tmp_path / "gender"
    package.mkdir()
    (package / "gender_classifier.joblib").write_bytes(b"model")
    (package / "runtime_models").mkdir()
    service = GenderService(package)
    predictions = [
        {"id": "1:exact", "gender": "unknown", "confidence": 0.7, "status": "uncertain_gender"},
        {"id": "1:w1.00", "gender": "female", "confidence": 0.99, "status": "ok"},
        {"id": "1:w1.25", "gender": "female", "confidence": 0.98, "status": "ok"},
    ]
    result = service._resolve("1", predictions)
    assert result["gender"] == "female"
    assert result["status"] == "window_consensus"
    assert result["skip_tts"] is False


def test_conflicting_windows_stay_unknown(tmp_path):
    package = tmp_path / "gender"
    package.mkdir()
    (package / "gender_classifier.joblib").write_bytes(b"model")
    (package / "runtime_models").mkdir()
    service = GenderService(package)
    result = service._resolve("1", [
        {"id": "1:w1.00", "gender": "female", "confidence": 0.99, "status": "ok"},
        {"id": "1:w1.25", "gender": "male", "confidence": 0.99, "status": "ok"},
    ])
    assert result["gender"] == "unknown"
    assert result["skip_tts"] is False

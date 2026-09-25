from services.whissle_gender_service import WhissleGenderService


class _Client:
    base_url = "http://test"

    def health_check(self):
        return True


def test_segment_selector_rejects_overlap_and_short_segments():
    service = WhissleGenderService(_Client())
    turns = [
        {"speaker": "SPEAKER_00", "start": 0.0, "end": 3.0},
        {"speaker": "SPEAKER_01", "start": 2.5, "end": 4.0},
        {"speaker": "SPEAKER_00", "start": 5.0, "end": 5.5},
        {"speaker": "SPEAKER_00", "start": 6.0, "end": 9.0},
    ]
    selected = service._select(turns)
    assert len(selected["SPEAKER_00"]) == 1
    assert selected["SPEAKER_00"][0]["start"] == 6.0
    assert "SPEAKER_01" not in selected


def test_whissle_labels_are_not_model_probabilities():
    service = WhissleGenderService(_Client())
    assert service.min_consensus == 0.65

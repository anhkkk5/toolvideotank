import pytest
from services.subtitle_merge_service import SubtitleMergeService


def test_merge_exact_duplicate_cues():
    cues = [
        {"id": 38, "start": 87.50, "end": 88.20, "text": "抱抱我"},
        {"id": 39, "start": 88.38, "end": 89.10, "text": "抱抱我"},
    ]
    # Sample interval 0.67s -> max_gap = max(0.7, 0.67 + 0.2) = 0.87s
    # Gap here is 88.38 - 88.20 = 0.18s <= 0.87s
    merged = SubtitleMergeService.merge_cues(cues, sample_interval=0.67)
    assert len(merged) == 1
    assert merged[0]["start"] == 87.50
    assert merged[0]["end"] == 89.10
    assert merged[0]["text"] == "抱抱我"
    assert merged[0]["merged_from"] == [38, 39]


def test_merge_triple_duplicate_cues():
    cues = [
        {"id": 42, "start": 92.50, "end": 93.00, "text": "是最后的拥抱吗"},
        {"id": 43, "start": 93.50, "end": 94.00, "text": "是最后的拥抱吗"},
        {"id": 44, "start": 94.38, "end": 95.00, "text": "是最后的拥抱吗"},
    ]
    # Sample interval 1.0s -> max_gap = max(0.7, 1.0 + 0.2) = 1.2s
    # Gap 93.50 - 93.00 = 0.5s <= 1.2s; gap 94.38 - 94.00 = 0.38s <= 1.2s
    merged = SubtitleMergeService.merge_cues(cues, sample_interval=1.0)
    assert len(merged) == 1
    assert merged[0]["start"] == 92.50
    assert merged[0]["end"] == 95.00
    assert merged[0]["text"] == "是最后的拥抱吗"
    assert merged[0]["merged_from"] == [42, 43, 44]


def test_distinct_cues_not_merged_by_substring():
    # Crucial test: '我喜欢你' and '我真的很喜欢你' must NOT be merged despite substring containment
    cues = [
        {"id": 1, "start": 10.0, "end": 11.0, "text": "我喜欢你"},
        {"id": 2, "start": 11.2, "end": 12.5, "text": "我真的很喜欢你"},
    ]
    merged = SubtitleMergeService.merge_cues(cues, sample_interval=0.67)
    assert len(merged) == 2
    assert merged[0]["text"] == "我喜欢你"
    assert merged[0]["merged_from"] == [1]
    assert merged[1]["text"] == "我真的很喜欢你"
    assert merged[1]["merged_from"] == [2]


def test_adaptive_max_gap_respects_interval():
    # Gap is 1.0s. At 0.5s sampling (max_gap=0.7s), it should NOT merge.
    # At 1.0s sampling (max_gap=1.2s), it SHOULD merge.
    cues = [
        {"id": 1, "start": 0.0, "end": 1.0, "text": "测试"},
        {"id": 2, "start": 2.0, "end": 3.0, "text": "测试"},
    ]
    not_merged = SubtitleMergeService.merge_cues(cues, sample_interval=0.5)
    assert len(not_merged) == 2

    merged = SubtitleMergeService.merge_cues(cues, sample_interval=1.0)
    assert len(merged) == 1
    assert merged[0]["merged_from"] == [1, 2]

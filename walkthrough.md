# Tổng kết triển khai: Hệ thống Nhận diện Giới tính Đa tầng (Hybrid Multi-Layer Gender AI)

## 1. Kết quả thực thi các Phase

### Phase 1: Khôi phục 100% nguyên bản `gender_detector.py`
- Đã gỡ bỏ toàn bộ can thiệp F0 vào xác suất của classifier.
- Giữ nguyên mô hình AI gốc bạn đã train: **SpeechBrain ECAPA 192D $\rightarrow$ StandardScaler $\rightarrow$ LogisticRegression**.

### Phase 2: VAD-aware Speech Extraction & Audio Quality Assessment
- [gender_service.py](file:///d:/capcap/CapCap/app/services/gender_service.py) được nâng cấp để nhận `vad_intervals`.
- Tự động cắt đúng vùng có giọng nói bên trong slot phụ đề, loại bỏ hoàn toàn các đoạn chỉ có nhạc nền dạo đầu / kết thúc (như đoạn 1.7s piano ở câu 27 được rút gọn từ 2.0s còn 1.04s).
- Tính toán đầy đủ: `speech_duration`, `speech_ratio = speech_duration / subtitle_duration`.
- Đánh giá `audio_quality` (`clean` / `low`) và phân tầng `raw_confidence_trust` (`HIGH` / `MEDIUM` / `LOW`).

### Phase 3: Minh bạch dữ liệu trong `SubtitleSegment`
- Đã bổ sung các trường độc lập vào [subtitle_segment.py](file:///d:/capcap/CapCap/app/models/subtitle_segment.py):
  - `raw_gender`, `raw_gender_confidence`, `raw_confidence_trust`
  - `final_gender`, `final_decision_confidence`, `decision_mode`
  - `audio_quality`, `speech_duration`, `speech_ratio`, `music_score`, `gender_reason`

### Phase 4 & 5: Anchor-Based Temporal Smoothing Service
- Tạo service độc lập [app/services/temporal_gender_smoothing.py](file:///d:/capcap/CapCap/app/services/temporal_gender_smoothing.py) và tích hợp vào [voice_gender_check_service.py](file:///d:/capcap/CapCap/app/services/voice_gender_check_service.py).
- **Quy tắc an toàn**:
  - Chỉ các câu có `audio_quality == clean`, `trust == HIGH` và độ tin cậy $\ge 85\%$ mới được làm **Anchor**.
  - Các câu yếu/ngắn ở giữa (như câu 23, 25, 27) được neo theo các Anchor Nam mạnh (câu 24 = 99.5%, câu 26 = 99.8%).
  - Độ tin cậy `final_decision_confidence` được tính toán động theo độ mạnh của Anchor.
  - **Bảo vệ Test D (Rapid Dialogue Switch)**: Khi có cả Anchor Nam và Anchor Nữ trong cụm (đối đáp nhanh), hệ thống bảo lưu độc lập kết quả của từng câu, cấm làm mượt gộp bừa.

### Phase 6: Hiển thị minh bạch trên giao diện CapCap
- Cập nhật [ui/main_window_parts/voice_gender_mixin.py](file:///d:/capcap/CapCap/ui/main_window_parts/voice_gender_mixin.py):
  - Cột **Giọng**: Hiển thị `final_gender` ("Nam" / "Nữ").
  - Cột **Đồng thuận**: Hiển thị `final_decision_confidence` (kèm ký hiệu `🔧` nếu đã qua hiệu chỉnh).
  - **Tooltip chi tiết**: Khi rê chuột vào sẽ thấy rõ kết quả nguyên bản của model âm thanh gốc, phần trăm raw và lý do hiệu chỉnh.

---

## 2. Bảng đối chiếu kết quả kiểm thử thực tế

| Câu | Mốc thời gian | Model âm thanh gốc (Raw AI) | Kết quả sau Smoothing (Final) | Chế độ quyết định | Phụ đề |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Câu 1** | 00:00.0 – 00:01.5 | **Nam (99.9%)** | **Nam (99.9%)** | `raw_audio` | 你介意你喜欢的女生 |
| **Câu 2** | 00:01.5 – 00:03.5 | **Nam (99.8%)** | **Nam (99.8%)** | `raw_audio` | 和其他男生走的很近吗 |
| **Câu 3** | 00:03.5 – 00:05.5 | **Nam (97.9%)** | **Nam (97.9%)** | `raw_audio` | 那天离开后 |
| **Câu 5** | 00:09.5 – 00:13.5 | **Nữ (100.0%)** | **Nữ (100.0%)** | `raw_audio` | 王宇你这两天怎么回事 |
| **Câu 6** | 00:13.5 – 00:16.5 | **Nữ (62.5%)** | **Nữ (62.5%)** | `raw_audio` | 你到底想干嘛 |
| **Câu 22** | 01:13.5 – 01:15.5 | **Nam (59.3%)** | **Nam (59.3%)** | `raw_audio` | 看着她离开的背影 |
| **Câu 23** | 01:15.5 – 01:16.5 | ❌ Nữ (96.0%) |  **Nam (90.6%)** | `contextual_smoothing` 🔧 | 我再一次的怀疑自己 |
| **Câu 24** | 01:16.5 – 01:18.5 | **Nam (99.5%)** | **Nam (99.5%)** | `raw_audio` (Anchor) | 是不是误会她了 |
| **Câu 25** | 01:18.5 – 01:19.5 | ❌ Nữ (92.1%) |  **Nam (90.6%)** | `contextual_smoothing` 🔧 | 我开始反思我自己 |
| **Câu 26** | 01:19.5 – 01:21.5 | **Nam (99.8%)** | **Nam (99.8%)** | `raw_audio` (Anchor) | 最近对她的态度 |
| **Câu 27** | 01:21.5 – 01:23.5 | ❌ Nữ (99.9%) |  **Nam (90.6%)** | `contextual_smoothing` 🔧 | 直到 |

# CapCap – Trạng thái hệ thống nhận diện nhân vật và lồng tiếng

## 1. Kết luận ngắn

Hệ thống hiện đã có đủ các khối OCR, chép lời âm thanh, phân cụm người nói, phân tích hình ảnh, dịch và TTS. Tuy nhiên, hệ thống **chưa tự động chính xác hoàn toàn** với video phim ngắn có nhiều nhân vật.

Lỗi chính hiện tại không nằm ở DeepSeek hay chất lượng giọng TTS. Lỗi nằm ở bước nối ba loại dữ liệu:

- câu phụ đề OCR;
- lượt nói trong âm thanh;
- nhân vật xuất hiện trong hình.

Nếu OpenAI không tạo được một lượt nói tại thời gian có phụ đề OCR, Character Resolver không nhận được đoạn đó để phân tích. Vì vậy câu vẫn có chữ nhưng không có bằng chứng nhân vật đáng tin cậy, dẫn đến thiếu nhân vật, sai giới tính hoặc gán nhầm voice.

Trạng thái hiện tại: **pipeline chạy được, nhưng chưa đạt mức tự động hóa production cho video nhiều nhân vật**.

## 2. Luồng hệ thống hiện tại

```text
Video
 ├─> Trích xuất âm thanh
 │    └─> OpenAI diarization
 │         └─> các audio turn + SPEAKER_x
 │              ├─> Character Resolver bằng hình ảnh
 │              ├─> Phase 2: dấu vân tay giọng nói
 │              ├─> Phase 3: tách lượt đổi người nói
 │              └─> Phase 4: áp dụng sửa tay
 │
 └─> OCR phụ đề cháy
      └─> Hybrid OCR/ASR sửa hoặc bổ sung chữ

Audio turn + OCR cue
 └─> Căn thời gian và truyền metadata nhân vật
      └─> DeepSeek dịch nội dung
           └─> Smart Cast chọn voice theo giới tính
                └─> TTS tạo audio và ghép timeline
```

Điểm quan trọng: DeepSeek chỉ dịch và làm mượt nội dung. DeepSeek không trực tiếp nghe giọng, không diarize và không quyết định nhân vật nào đang nói.

## 3. Các thành phần đang có

| Thành phần | Vai trò hiện tại | Giới hạn |
|---|---|---|
| OpenAI audio diarization | Tách âm thanh thành các lượt nói và nhãn `SPEAKER_x` | Có thể bỏ sót lượt ngắn, nhiễu hoặc bị nhạc che; một cluster không luôn tương ứng một nhân vật |
| Character Resolver hình ảnh | Xem khung hình quanh audio turn, tạo `CHAR_x`, giới tính và độ tin cậy | Chỉ phân tích những turn đã có từ nhánh âm thanh; có thể nhập nhầm người qua cảnh/trang phục |
| Phase 2 voice fingerprint | Dùng embedding giọng để nhận lại nhân vật từ anchor đã chắc chắn | Không cứu được câu OCR nếu câu đó chưa có audio turn đầu vào |
| Phase 3 splitter | Tách một turn khi phát hiện đổi người nói giữa đoạn | Kết quả `0 lượt` chỉ có nghĩa chưa tìm thấy điểm tách, không chứng minh phân vai đúng |
| Phase 4 correction | Ghi nhớ và áp dụng các sửa tay | `0 sửa tay` là bình thường khi chưa có correction |
| OCR | Đọc phụ đề cháy trong vùng đã chọn | Có thể dính chữ trên áo, watermark hoặc chữ tiêu đề nếu vùng OCR quá rộng |
| Hybrid OCR/ASR | Bổ sung khoảng trống OCR và thay chữ OCR hỏng | Không phải bộ nhận diện danh tính nhân vật |
| DeepSeek | Dịch Trung–Việt và làm mượt câu | Không chịu trách nhiệm nhận diện người nói |
| Smart Cast | Chọn voice nam/nữ theo metadata nhân vật | Nếu metadata nhân vật hoặc giới tính sai thì voice cũng sai theo |
| TTS/cache | Tạo từng file giọng và ghép thành track | Cần ép làm mới khi speaker, voice hoặc nội dung thay đổi |

## 4. Những phần đã triển khai

- Đã dùng OpenAI diarization cho âm thanh.
- Đã có Character Resolver bằng khung hình và registry `CHAR_x`.
- Đã truyền các trường `audio_speaker`, `character_id`, `character_gender`, `character_confidence` và `character_source` qua phần lớn pipeline.
- Đã có Phase 2 nhận lại giọng bằng Sherpa-ONNX embedding.
- Đã có Phase 3 tách lượt nói và Phase 4 correction.
- Đã có Hybrid OCR/ASR để giảm câu OCR sai hoặc thiếu.
- Đã có Smart Cast tự chọn giọng nam/nữ.
- Đã sửa luồng “Làm mới và tạo lại từ đầu” để xóa chữ ký cache cũ và ép tạo lại TTS.
- Đã có thông tin tổng kết Character Resolver trong giao diện.
- Bộ kiểm thử gần nhất của phần đã sửa: `24/24` test đạt.

Các mục trên xác nhận hệ thống có nền tảng cần thiết, nhưng không có nghĩa kết quả phân vai đã đúng 100%.

## 5. Các lỗi còn tồn tại

### P0 – Resolve các câu chỉ có OCR (đã triển khai bản đầu)

Đây là lỗi kiến trúc quan trọng nhất.

Ví dụ video kiểm thử có thoại khoảng `107–113 giây`, OCR nhìn thấy câu nhưng OpenAI diarization không trả audio turn tương ứng. Character Resolver hiện chạy trên danh sách audio turn nên không bao giờ xem đoạn này. Kết quả là nhân vật thứ tư có thể bị bỏ mất hoàn toàn.

Pipeline hiện đã bổ sung bước sau OCR:

```text
OCR cue không có audio turn phù hợp
 └─> cắt audio đúng thời gian cue
 ├─> lấy khung hình quanh cue
 ├─> nhận diện active speaker/voice fingerprint
 └─> ghép vào character registry hiện có
```

### P0 – Cổng kiểm tra trước TTS (đã triển khai)

Hệ thống hiện chặn TTS khi câu có:

- `character_id` rỗng hoặc `UNKNOWN`;
- giới tính chưa chắc chắn;
- độ tin cậy bằng 0 hoặc bị mất;
- mâu thuẫn giữa hình, giọng và character registry.

Các câu này được đưa vào “Cần kiểm tra”; hệ thống không còn âm thầm chọn voice mặc định.

### P1 – Character ID vẫn có thể bị nhập hoặc tách sai

Cùng một nhân vật thay quần áo hoặc đổi bối cảnh có thể bị tách thành nhiều `CHAR_x`. Hai nhân vật giống cảnh, đứng cạnh nhau hoặc nói ngoài hình có thể bị nhập thành một nhân vật.

Registry hiện cần thêm face embedding/face track và continuity theo cảnh, kết hợp với voice fingerprint, thay vì phụ thuộc nhiều vào từng batch khung hình.

### P1 – Tự retry khi OpenAI báo 429 (đã triển khai)

Log trước đây đã xuất hiện giới hạn TPM. Đây không phải lỗi API key hay hết tiền; request bị từ chối vì vượt giới hạn token theo phút. Pipeline hiện đọc thời gian `try again` do OpenAI trả về, tự chờ và retry tối đa 5 lần với backoff. Việc tối ưu tiếp theo là lưu tiến độ từng batch để không gọi lại các batch đã thành công.

### P1 – `AI 0%` đang gây hiểu nhầm

`AI 0%` hiện thường có nghĩa là giao diện không nhận được `character_confidence`, không phải OpenAI khẳng định độ tin cậy bằng 0%.

Nếu câu đã có `CHAR_01`, `CHAR_02` nhưng vẫn hiện `AI 0%`, cần kiểm tra artifact đó có được tạo trước bản vá metadata hay không và confidence có bị mất ở bước merge/rehydrate hay không.

## 6. Test case chuẩn của video hiện tại

Ground truth hợp lý cho video `SnapTikTok.to_7299770837106806026_hd.mp4`:

| Character | Nhân vật | Giới tính | Voice mong muốn |
|---|---|---|---|
| `CHAR_01` | Hạ Kiêu – nam chính | Nam | Thanh niên tự tin |
| `CHAR_02` | Nữ chính tóc tết | Nữ | Cô gái hoạt bát |
| `CHAR_03` | Shipper áo vàng | Nam | Voice nam, có thể dùng Thanh niên tự tin |
| `CHAR_04` | Lý Thi Vũ | Nữ | Voice nữ, có thể dùng Cô gái hoạt bát |

Video có **4 nhân vật có thoại: 2 nam, 2 nữ**. Người xuất hiện trong hình nhưng không có thoại không được tính là speaker.

Các mốc quan trọng để kiểm thử:

- khoảng `12.5–14.4s`: Hạ Kiêu, phải là nam;
- khoảng `31–40.8s`: Hạ Kiêu và shipper, cả hai đều là nam;
- khoảng `81.5–103s`: nhiều câu của Hạ Kiêu, phải là nam;
- khoảng `107–113s`: Lý Thi Vũ, phải được phát hiện dù nhánh diarization có thể bỏ sót;
- khoảng `120–122s` và `127.5–130s`: câu nữ;
- khoảng `123–127s` và khoảng `133.5s`: Hạ Kiêu, phải là nam.

Nếu kết quả chỉ có 3 nhân vật thì chưa đạt ground truth của video này.

## 7. Ý nghĩa thông báo Phase

Ví dụ:

```text
Character Resolver: 3 nhân vật — 1 nam, 2 nữ
Phase 3 tách 0 lượt đổi người nói
Phase 2 nhận lại 0 lượt qua dấu vân tay giọng
Phase 4 áp dụng 0 sửa tay
```

Nó chỉ mô tả những gì pipeline đã tìm được:

- `3 nhân vật` không có nghĩa video thật chỉ có 3 nhân vật;
- `Phase 2 = 0` nghĩa không có turn nào được phục hồi bằng fingerprint;
- `Phase 3 = 0` nghĩa không phát hiện turn cần tách;
- `Phase 4 = 0` nghĩa không có sửa tay được áp dụng.

Đây là báo cáo hoạt động, không phải chứng nhận kết quả chính xác.

## 8. OCR nên chọn như thế nào

- Chỉ khoanh vùng phụ đề hội thoại cố định ở dưới màn hình.
- Không bao phủ chữ tiêu đề phía trên, watermark hoặc chữ trên áo shipper.
- Chữ trên áo chỉ “dính” khi nó đi vào vùng OCR và tồn tại đủ lâu để OCR coi là subtitle.
- OCR giúp lấy chữ và mốc thời gian; OCR không tự xác định người nói.

## 9. Cache và giọng bị chồng

Khi chỉ bấm chạy lại thông thường, hệ thống có thể tái sử dụng audio nếu signature không đổi. Khi thay phân vai, gender, voice hoặc muốn kiểm thử lại thuật toán, phải dùng “Làm mới và tạo lại từ đầu”.

Một lần làm mới đúng phải:

- xóa artifact nhận diện và phụ đề cũ của project;
- xóa chữ ký voiceover tổng;
- ép `force=True` khi tạo TTS;
- thay track TTS cũ, không chèn thêm một track chồng lên;
- chỉ giữ cache segment nếu signature của chính segment vẫn đúng.

Log `cache_hits` ở cấp segment không tự động là lỗi. Lỗi là khi toàn bộ `voice_vi.wav` cũ được dùng lại dù speaker/voice/text đã thay đổi, hoặc khi track TTS cũ không được thay thế.

## 10. Hướng sửa tiếp theo

Thứ tự ưu tiên:

1. Thêm Post-OCR Gap Resolver cho mọi cue chưa có audio turn hoặc chưa có character đáng tin cậy.
2. Thêm Integrity Gate trước Smart Cast/TTS; không tạo giọng nếu còn cue `UNKNOWN`, thiếu gender hoặc confidence thấp.
3. Thêm retry/backoff và chia batch khi OpenAI trả 429.
4. Nâng character registry bằng face embedding, face tracking, scene continuity và voice fingerprint.
5. Làm rõ UI: tách “voice group” khỏi “character thực”, hiển thị nguồn và lý do của confidence.
6. Thêm báo cáo cuối quy trình: tổng cue, cue đã resolve, cue cần kiểm tra, số character theo giới tính và các mốc bị mâu thuẫn.

## 11. Tiêu chí hoàn thành

Pipeline chỉ được coi là đạt với video kiểm thử khi:

- nhận đúng 4 nhân vật có thoại, gồm 2 nam và 2 nữ;
- mọi subtitle cue có `audio_speaker` hoặc bằng chứng thay thế, `character_id`, gender, confidence và source;
- đoạn shipper `31–40.8s` không còn voice nữ;
- đoạn `107–113s` được gán cho Lý Thi Vũ;
- câu đã resolve không còn hiển thị `AI 0%` do mất metadata;
- không tạo hai track TTS chồng lên nhau sau khi làm mới;
- thay speaker/voice phải làm thay đổi TTS tương ứng;
- DeepSeek chỉ xử lý dịch, không được dùng như bằng chứng nhận diện speaker.

## 12. Các file code chính

- `app/workflows/prepare_workflow.py`: điều phối toàn bộ quy trình chuẩn bị.
- `app/services/openai_speaker_analysis_service.py`: diarization âm thanh và Character Resolver.
- `app/services/character_voice_resolver.py`: Phase 2 voice fingerprint.
- `app/services/character_segment_splitter.py`: Phase 3 tách lượt nói.
- `app/services/character_correction_service.py`: Phase 4 correction.
- `app/services/hybrid_audio_ocr_fusion.py`: kết hợp OCR và ASR.
- `app/services/subtitle_speaker_aligner.py`: căn cue với speaker/character.
- `app/services/smart_cast.py`: chọn voice theo nhân vật và giới tính.
- `app/services/gui_project_bridge.py`: chuyển dữ liệu workflow vào project GUI.
- `app/core/models/segment.py`: model segment và metadata.
- `ui/controllers/pipeline_controller.py`: điều khiển chạy workflow từ GUI.
- `ui/main_window.py`: hành động Tạo, Làm mới, TTS và cache.
- `ui/views/subtitle_list_view.py`: hiển thị cue, character và `AI %`.

## 13. Lưu ý bảo mật

API key chỉ được đặt trong `.env`, không ghi vào README, source code hoặc log được commit. Nếu key từng được gửi công khai hoặc dán vào hội thoại, nên thu hồi key cũ và tạo key mới.

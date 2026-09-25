# TÍCH HỢP GENDER AI VÀO TOOL CAPCAP

## 1. Mục tiêu

Module Gender AI chỉ làm một việc:

```text
Audio của từng câu thoại
        ↓
Gender AI
        ↓
male / female / none / unknown
        ↓
Chọn giọng TTS phù hợp
```

Không nhận diện nhân vật M1/M2/F1/F2, không diarization, không clustering speaker.

Quy ước:
- `male` → giọng TTS nam
- `female` → giọng TTS nữ
- `none` → bỏ TTS
- `unknown` → chưa đủ chắc, fallback hoặc sửa tay

> Lưu ý: `gender_detector.py` hiện tại trả `unknown` với `status="music_or_non_speech"`. Ở lớp tích hợp của CapCap nên map trường hợp này thành `none / skip_tts`.

---

## 2. Cấu trúc thư mục đề xuất

```text
capcap/
│
├── ai_models/
│   └── gender_ai/
│       ├── gender_detector.py
│       ├── gender_classifier.joblib
│       └── runtime_models/
│           ├── ecapa/
│           │   ├── hyperparams.yaml
│           │   ├── embedding_model.ckpt
│           │   ├── mean_var_norm_emb.ckpt
│           │   ├── classifier.ckpt
│           │   └── label_encoder.ckpt
│           └── ast/
│               └── models--MIT--ast-finetuned-audioset-10-10-0.4593/
│                   ├── blobs/
│                   └── snapshots/
│
├── services/
│   └── gender_service.py
│
└── ...
```

Đúng:

```text
ai_models/gender_ai/gender_detector.py
```

Sai:

```text
ai_models/gender_ai/gender_voice_ai_windows_package/gender_detector.py
```

---

## 3. Thư viện Python cần có

```bash
pip install torch torchaudio speechbrain transformers joblib numpy
```

Module đã test chạy CPU và offline.

---

## 4. Khởi tạo GenderDetector

Nên tạo **một instance duy nhất khi app khởi động**.

```python
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
GENDER_AI_DIR = ROOT / "ai_models" / "gender_ai"

sys.path.insert(0, str(GENDER_AI_DIR))

from gender_detector import GenderDetector

gender_detector = GenderDetector(
    gender_model_path=GENDER_AI_DIR / "gender_classifier.joblib",
    cache_dir=GENDER_AI_DIR / "runtime_models",
    device="cpu",
)
```

Không tạo lại model cho từng subtitle.

---

## 5. API có sẵn

### Nhận diện nguyên file

```python
result = gender_detector.detect_file("sample.wav")
```

### Nhận diện theo timestamp

```python
result = gender_detector.detect_segment(
    audio_path="movie_audio.wav",
    start=43.60,
    end=46.10,
)
```

Ví dụ:

```python
{
    "gender": "female",
    "confidence": 0.9997,
    "status": "ok",
    "male_probability": 0.0003,
    "female_probability": 0.9997,
    "speech_score": ...,
    "music_score": ...,
    "singing_score": ...,
    "dialogue_score": ...
}
```

### Nhận diện batch nhiều subtitle

```python
segments = [
    {"id": 1, "start": 1.20, "end": 2.80},
    {"id": 2, "start": 3.10, "end": 4.40},
]

results = gender_detector.detect_segments(
    "movie_audio.wav",
    segments,
)
```

Nên ưu tiên cách này vì audio chỉ load một lần.

---

## 6. Lớp kết nối đề xuất

Tạo:

```text
services/gender_service.py
```

Pseudo-code:

```python
class GenderService:
    def __init__(self, detector):
        self.detector = detector

    def normalize_result(self, result):
        if result["status"] == "music_or_non_speech":
            return {
                "gender": "none",
                "skip_tts": True,
                "confidence": 0.0,
            }

        if result["gender"] == "male":
            return {
                "gender": "male",
                "skip_tts": False,
                "confidence": result["confidence"],
            }

        if result["gender"] == "female":
            return {
                "gender": "female",
                "skip_tts": False,
                "confidence": result["confidence"],
            }

        return {
            "gender": "unknown",
            "skip_tts": False,
            "confidence": result.get("confidence", 0.0),
        }
```

---

## 7. Luồng tích hợp vào pipeline

```text
VIDEO
  ↓
Tách audio 16 kHz mono
  ↓
OCR phụ đề Trung
  ↓
Sinh SRT: id/start/end/text
  ↓
GenderService
  ↓
male / female / none / unknown
  ↓
DeepSeek dịch Trung → Việt
  ↓
Map voice
  ↓
TTS
  ↓
Ghép audio về video
```

Dữ liệu subtitle nên có dạng:

```python
{
    "id": 25,
    "start": 24.33,
    "end": 25.00,
    "text_zh": "...",
    "text_vi": "...",
    "gender": "female",
    "gender_confidence": 0.9959,
    "tts_voice": "female_default",
    "skip_tts": False,
}
```

---

## 8. Map Gender → Voice

```python
VOICE_MAP = {
    "male": "male_default",
    "female": "co_gai_hoat_ngon",
}
```

```python
if subtitle["gender"] == "none":
    subtitle["skip_tts"] = True

elif subtitle["gender"] == "male":
    subtitle["tts_voice"] = VOICE_MAP["male"]

elif subtitle["gender"] == "female":
    subtitle["tts_voice"] = VOICE_MAP["female"]

else:
    subtitle["tts_voice"] = None
```

---

## 9. Xử lý unknown

Không ép `unknown` thành nam/nữ nếu model đang mâu thuẫn.

Fallback đề xuất:

```text
1. Chạy timestamp SRT gốc
2. Nếu confidence >= 95% → dùng luôn
3. Nếu chưa chắc → thử 1.00s / 1.25s / 1.50s
4. Nếu ít nhất 2 window high-confidence cùng giới tính
   và không có giới tính đối lập → dùng consensus
5. Nếu tất cả window là music/non-speech → none
6. Nếu vẫn mâu thuẫn → unknown
```

Không nên dùng window 2.0s mặc định vì dễ ăn sang người nói kế bên.

---

## 10. Không nên làm

```text
❌ tạo GenderDetector mới cho từng subtitle
❌ load audio lại hàng trăm lần nếu có detect_segments()
❌ ép mọi đoạn lên 1.5 giây
❌ hạ threshold chỉ để giảm unknown
❌ lấy 1 strong vote rồi gán luôn
❌ biến music thành male/female
❌ dùng Gender AI để nhận diện danh tính nhân vật
```

Gender AI chỉ phân loại:

```text
nam / nữ / không thoại / không chắc
```

---

## 11. Hiệu năng

Package khoảng ~700 MB, chủ yếu do AST + ECAPA.

Máy không có GPU rời:

```python
device="cpu"
```

Khuyến nghị:
- Khởi tạo model một lần
- Load audio một lần mỗi video
- Xử lý batch subtitle
- Chạy ở worker/thread riêng để UI không bị đứng
- Cache kết quả theo `video_hash + start + end`

Nếu user chỉ sửa text dịch nhưng timestamp không đổi thì không cần detect lại gender.

---

## 12. UI nên hiển thị

```text
Nam         → male
Nữ          → female
Không thoại → none
Chưa rõ     → unknown
```

Cho phép user sửa tay:

```text
Nam | Nữ | Không thoại
```

Sửa tay chỉ đổi metadata subtitle, không cần chạy model lại.

---

## 13. Offline

Package đã test thành công với:

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

Kết quả:

```text
Models loaded OFFLINE
Detection OK
Exit code: 0
```

Nếu giữ đúng:
- `gender_classifier.joblib`
- `runtime_models/ecapa`
- `runtime_models/ast`

thì runtime không cần Internet.

---

## 14. Kiến trúc cuối

```text
OCR/SRT
  ↓
GenderService
  ↓
GenderDetector
  ├─ AST
  ├─ ECAPA
  └─ LogisticRegression
  ↓
male / female / none / unknown
  ↓
Voice Mapping
  ↓
TTS
```

---

## 15. Phần bạn cần code tiếp

Chỉ cần tập trung vào:

```text
1. Khởi tạo GenderDetector đúng 1 lần
2. Đưa timestamp SRT vào detect_segments()
3. Chuẩn hóa:
   male    → voice nam
   female  → voice nữ
   none    → skip TTS
   unknown → fallback / sửa tay
4. Gắn kết quả vào subtitle model của CapCap
5. Cho TTS đọc theo gender
```

Không cần quay lại Colab để train nữa nếu chỉ dùng model hiện tại.

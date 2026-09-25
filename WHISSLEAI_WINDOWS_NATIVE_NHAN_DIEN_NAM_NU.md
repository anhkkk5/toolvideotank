# TÍCH HỢP WHISSLEAI NHẬN DIỆN GIỌNG NAM/NỮ — WINDOWS NATIVE

> **Mục tiêu:** tích hợp trực tiếp WhissleAI vào tool Python chạy trên **Windows 11**, không WSL, không Ubuntu, không Docker và không cần chạy HTTP server riêng.
>
> **Model:** `WhissleAI/STT-zh-mandarin-ONNX`
>
> **Cách tích hợp:** dùng **Python + ONNX Runtime trực tiếp trong process của tool**.
>
> **Thiết bị:** CPU, không yêu cầu GPU rời.
>
> **Lưu ý quan trọng:** repo chính thức có script `setup.sh` hướng tới macOS/Linux, nhưng package Python của repo được khai báo là `Operating System :: OS Independent` và engine chủ yếu dùng `onnxruntime`, `librosa`, `numpy`, `scipy`, `soundfile`, `sentencepiece`, `huggingface_hub`. Vì vậy trên Windows ta **không chạy `setup.sh`**, mà cài package Python trực tiếp rồi tải model bằng Python.

---

# 1. KIẾN TRÚC ĐÚNG CHO TOOL WINDOWS

Không dùng:

```text
Windows Tool
   ↓ HTTP
Ubuntu / WSL
   ↓
Whissle
```

Mà dùng:

```text
┌────────────────────── WINDOWS 11 ──────────────────────┐
│                                                       │
│  Tool Python                                          │
│      │                                                │
│      ├── Speaker Diarization                          │
│      │       ↓                                        │
│      │   SPEAKER_00 / SPEAKER_01 / ...               │
│      │                                                │
│      ├── Segment Selector                             │
│      │       ↓                                        │
│      │   audio sạch theo từng speaker                 │
│      │                                                │
│      ├── WhissleGenderService                         │
│      │       ↓                                        │
│      │   ASREngine của Whissle                        │
│      │       ↓                                        │
│      │   ONNX Runtime CPU                             │
│      │       ↓                                        │
│      │   model.onnx + tag_classifier.onnx             │
│      │                                                │
│      ├── Gender Resolver                              │
│      │       ↓                                        │
│      │   male / female / unknown                      │
│      │                                                │
│      └── Auto-Cast → TTS                              │
│                                                       │
└───────────────────────────────────────────────────────┘
```

Không cần:

```text
WSL
Ubuntu
Docker
FastAPI
localhost:8002
HTTP request
```

Whissle chạy **ngay trong Python process của tool**.

---

# 2. VAI TRÒ CỦA TỪNG THÀNH PHẦN

## 2.1. Diarization

Chịu trách nhiệm:

```text
Ai đang nói ở thời điểm nào?
```

Ví dụ:

```text
00:01.20 → 00:04.30   SPEAKER_00
00:04.50 → 00:07.80   SPEAKER_01
00:09.10 → 00:12.40   SPEAKER_00
```

## 2.2. WhissleAI

Chịu trách nhiệm:

```text
Đoạn giọng của SPEAKER_X là Nam hay Nữ?
```

Output mong muốn:

```text
MALE
FEMALE
NONE
```

Chuẩn hóa trong tool:

```text
MALE   → male
FEMALE → female
NONE   → unknown
```

## 2.3. Gender Resolver

Không tin tuyệt đối vào một segment.

Ví dụ:

```text
SPEAKER_00

segment 1 → FEMALE
segment 2 → FEMALE
segment 3 → MALE
segment 4 → FEMALE
segment 5 → FEMALE
```

Kết quả cuối:

```text
SPEAKER_00 = female
```

## 2.4. Auto-Cast

Sau khi biết:

```text
SPEAKER_00 = female
SPEAKER_01 = male
SPEAKER_02 = male
SPEAKER_03 = female
```

mới xếp:

```text
Nam nói nhiều nhất → Nam chính → Anh Dũng
Nam tiếp theo      → Nam phụ   → Minh Quang

Nữ nói nhiều nhất → Nữ chính  → Cô Gái Hoạt Ngôn
Nữ tiếp theo       → Nữ phụ    → Ngọc Huyền
```

---

# 3. MODEL WHISSLE SẼ DÙNG

Model:

```text
WhissleAI/STT-zh-mandarin-ONNX
```

Đặc điểm chính:

```text
Language: Mandarin Chinese
Format: ONNX
Sample rate: 16 kHz mono
Architecture: Conformer-CTC + metadata/tag classifier
Gender labels:
- MALE
- FEMALE
- NONE
```

Các file chính của model thường gồm:

```text
config.json
model.onnx
tag_classifier.json
tag_classifier.onnx
tokenizer.model
vocabulary.json
```

`model.onnx` tạo encoder features.

`tag_classifier.onnx` dùng encoder features để dự đoán metadata/tag, trong đó có gender.

Không được chỉ chạy `tag_classifier.onnx` trực tiếp với file WAV.

---

# 4. LICENSE VÀ QUYỀN TRUY CẬP MODEL

Model là gated model trên Hugging Face.

Trước khi tải:

1. Đăng nhập Hugging Face.
2. Mở model:

```text
https://huggingface.co/WhissleAI/STT-zh-mandarin-ONNX
```

3. Chấp nhận quyền truy cập/license nếu trang model yêu cầu.
4. Tạo Hugging Face Access Token có quyền đọc.
5. Chỉ dùng token để tải model.

Ví dụ token:

```text
hf_xxxxxxxxxxxxxxxxxxxx
```

Không:

```text
- commit token lên Git
- hard-code token vào source
- gửi token cho người khác
```

---

# 5. PYTHON NÊN DÙNG

Repo yêu cầu Python hiện đại; với Windows nên dùng:

```text
Python 3.11 x64
```

Kiểm tra các bản Python đã cài:

```powershell
py -0p
```

Kiểm tra Python 3.11:

```powershell
py -3.11 --version
```

---

# 6. CLONE REPO TRÊN WINDOWS

Ví dụ project của bạn nằm ở:

```text
D:\YourTool
```

Mở PowerShell:

```powershell
cd D:\YourTool
mkdir third_party
cd third_party

git clone https://github.com/WhissleAI/whissle_stt_inference.git
```

Kết quả:

```text
D:\YourTool\
│
├── third_party\
│   └── whissle_stt_inference\
│       ├── src\
│       ├── pyproject.toml
│       ├── requirements.txt
│       ├── setup.sh
│       └── ...
│
└── ...
```

**Không chạy:**

```text
setup.sh
```

vì đó là shell helper dành cho macOS/Linux.

---

# 7. TẠO VIRTUAL ENVIRONMENT WINDOWS

Nếu tool hiện tại đã có `.venv`, có thể dùng môi trường đó.

Nếu chưa:

```powershell
cd D:\YourTool

py -3.11 -m venv .venv
```

Kích hoạt:

```powershell
.\.venv\Scripts\Activate.ps1
```

Nếu PowerShell chặn script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Sau đó mở PowerShell mới rồi:

```powershell
.\.venv\Scripts\Activate.ps1
```

Upgrade pip:

```powershell
python -m pip install --upgrade pip setuptools wheel
```

---

# 8. CÀI WHISSLE PYTHON ENGINE TRÊN WINDOWS

Đi tới repo đã clone:

```powershell
cd D:\YourTool\third_party\whissle_stt_inference
```

Cài editable:

```powershell
pip install -e .
```

Các dependency chính của package gồm:

```text
onnxruntime
librosa
soundfile
numpy
scipy
sentencepiece
pyctcdecode
huggingface_hub
```

Không cần:

```text
NeMo
CUDA
WSL
Ubuntu
Docker
```

Nếu `pip install -e .` gặp lỗi dependency, kiểm tra Python đang là 3.11 x64 trước.

---

# 9. KIỂM TRA ONNX RUNTIME

Chạy:

```powershell
python -c "import onnxruntime as ort; print(ort.__version__); print(ort.get_available_providers())"
```

Máy không có GPU rời thường thấy:

```text
['CPUExecutionProvider']
```

Đây là bình thường.

---

# 10. TẢI MODEL TRỰC TIẾP TRÊN WINDOWS

Tạo file:

```text
D:\YourTool\scripts\download_whissle_zh.py
```

Nội dung:

```python
import os
from pathlib import Path

from huggingface_hub import snapshot_download


REPO_ID = "WhissleAI/STT-zh-mandarin-ONNX"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODEL_DIR = (
    PROJECT_ROOT
    / "models"
    / "whissle_zh"
)


def main():
    token = os.getenv("HF_TOKEN")

    if not token:
        raise RuntimeError(
            "Chưa có HF_TOKEN. "
            "Hãy set biến môi trường HF_TOKEN trước."
        )

    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("Đang tải Whissle Mandarin...")

    snapshot_download(
        repo_id=REPO_ID,
        local_dir=str(MODEL_DIR),
        token=token,
    )

    print("Tải xong:", MODEL_DIR)


if __name__ == "__main__":
    main()
```

Trong PowerShell, set token cho phiên terminal hiện tại:

```powershell
$env:HF_TOKEN="hf_xxxxxxxxxxxxxxxxx"
```

Chạy:

```powershell
python scripts\download_whissle_zh.py
```

Sau khi tải, thư mục sẽ có dạng:

```text
D:\YourTool\models\whissle_zh\
│
├── config.json
├── model.onnx
├── tag_classifier.json
├── tag_classifier.onnx
├── tokenizer.model
├── vocabulary.json
└── ...
```

Sau khi model đã được tải local, inference không cần tải model lại mỗi lần chạy tool.

---

# 11. KHÔNG HARD-CODE TOKEN

Không làm:

```python
HF_TOKEN = "hf_abc123"
```

Nếu dùng `.env`, phải thêm vào `.gitignore`:

```gitignore
.env
```

Token chỉ phục vụ download model.

---

# 12. TEST WHISSLE TRỰC TIẾP TRÊN WINDOWS

Tạo:

```text
tests\test_whissle_windows.py
```

Ví dụ:

```python
from pathlib import Path

from src import ASREngine


ROOT = Path(__file__).resolve().parents[1]

MODEL_DIR = ROOT / "models" / "whissle_zh"

AUDIO = ROOT / "test_data" / "female_zh.wav"


engine = ASREngine(
    model_dir=str(MODEL_DIR),
    device="cpu",
    default_language="zh",
)

result = engine.transcribe(
    str(AUDIO),
    use_lm=False,
)

print(result)

tags = result.get("tags") or {}

print(
    "Gender:",
    tags.get("gender")
)
```

Chạy:

```powershell
python tests\test_whissle_windows.py
```

Có thể nhận:

```text
Gender: FEMALE
```

hoặc:

```text
Gender: MALE
```

hoặc kết quả không xác định.

---

# 13. TẠI SAO DÙNG `use_lm=False`?

Mục tiêu chính của module này là:

```text
gender
```

không phải tối ưu transcription.

`use_lm=False` giúp dùng đường greedy decoding và tránh phụ thuộc vào language model ngoài không cần thiết.

Tag classifier vẫn lấy đặc trưng từ encoder.

---

# 14. LOAD MODEL MỘT LẦN

Sai:

```python
for segment in segments:
    engine = ASREngine(...)
    result = engine.transcribe(...)
```

Vì mỗi segment lại khởi tạo model.

Đúng:

```python
engine = ASREngine(...)

for segment in segments:
    result = engine.transcribe(...)
```

Trong app desktop nên tạo một service/singleton dùng suốt phiên xử lý.

---

# 15. CẤU TRÚC PROJECT WINDOWS ĐỀ XUẤT

```text
D:\YourTool\
│
├── ai\
│   │
│   ├── diarization\
│   │   └── diarization_service.py
│   │
│   ├── gender\
│   │   ├── __init__.py
│   │   ├── whissle_gender_service.py
│   │   ├── segment_selector.py
│   │   ├── gender_resolver.py
│   │   └── gender_pipeline.py
│   │
│   └── autocast\
│       ├── role_ranker.py
│       └── voice_mapper.py
│
├── audio\
│   ├── extractor.py
│   ├── cropper.py
│   └── audio_quality.py
│
├── models\
│   └── whissle_zh\
│       ├── config.json
│       ├── model.onnx
│       ├── tag_classifier.json
│       ├── tag_classifier.onnx
│       ├── tokenizer.model
│       └── vocabulary.json
│
├── third_party\
│   └── whissle_stt_inference\
│
├── temp\
│   └── gender_segments\
│
├── cache\
│   └── gender\
│
├── scripts\
│   └── download_whissle_zh.py
│
├── tests\
│   ├── test_whissle_windows.py
│   └── test_gender_pipeline.py
│
└── main.py
```

Không bắt buộc project của bạn phải giống hệt cấu trúc này. Quan trọng là tách rõ:

```text
Whissle engine
Segment selection
Gender resolution
Auto-Cast
```

---

# 16. TẠO `WhissleGenderService`

File:

```text
ai\gender\whissle_gender_service.py
```

Ví dụ:

```python
from __future__ import annotations

from pathlib import Path
from threading import Lock

from src import ASREngine


class WhissleGenderService:
    """
    Windows-native Whissle gender detector.

    Model được load một lần rồi tái sử dụng
    cho tất cả segment của video.
    """

    def __init__(
        self,
        model_dir: str,
    ):
        self.model_dir = str(
            Path(model_dir).resolve()
        )

        self._engine = None
        self._lock = Lock()

    def load(self):
        if self._engine is not None:
            return

        with self._lock:
            if self._engine is not None:
                return

            self._engine = ASREngine(
                model_dir=self.model_dir,
                device="cpu",
                default_language="zh",
            )

    def predict(
        self,
        audio_path: str,
    ) -> dict:
        self.load()

        result = self._engine.transcribe(
            audio_path,
            use_lm=False,
        )

        tags = result.get("tags") or {}

        raw_gender = tags.get("gender")

        if raw_gender:
            raw_gender = str(
                raw_gender
            ).upper()
        else:
            raw_gender = "NONE"

        if raw_gender == "MALE":
            gender = "male"

        elif raw_gender == "FEMALE":
            gender = "female"

        else:
            gender = "unknown"

        return {
            "gender": gender,
            "raw_gender": raw_gender,
            "transcript": result.get(
                "transcript",
                result.get("text", ""),
            ),
            "duration": result.get(
                "duration",
                0.0,
            ),
            "processing_time": result.get(
                "processing_time",
                0.0,
            ),
        }
```

---

# 17. KHỞI TẠO SERVICE TRONG TOOL

Ví dụ:

```python
from pathlib import Path

from ai.gender.whissle_gender_service import (
    WhissleGenderService
)


ROOT = Path(__file__).resolve().parent

gender_service = WhissleGenderService(
    model_dir=str(
        ROOT
        / "models"
        / "whissle_zh"
    )
)
```

Không nhất thiết load ngay khi mở app.

Có thể chỉ load khi user bấm:

```text
Phân tích nhân vật
```

hoặc:

```text
Nhận diện giới tính
```

---

# 18. VIDEO 2 PHÚT KHÔNG ĐƯỢC CẮT CỨ 5 GIÂY

Sai:

```text
00:00–00:05
00:05–00:10
00:10–00:15
```

Vì một đoạn có thể chứa:

```text
2 giây nam
+
3 giây nữ
```

Whissle không nên nhận đoạn có hai người khác nhau.

Đúng:

```text
Speaker diarization
      ↓
segment theo lượt nói
```

Ví dụ:

```text
00:00.5–00:03.8 SPEAKER_00
00:04.0–00:06.1 SPEAKER_01
00:06.4–00:10.2 SPEAKER_00
```

Whissle nhận từng segment do diarization tạo ra.

---

# 19. Ý NGHĨA CỦA `2–8 GIÂY`

`2–8 giây` **không phải** cách chia video.

Nó chỉ là khoảng độ dài ta **ưu tiên** sau khi đã biết segment thuộc về một speaker.

Đề xuất:

```text
< 1 giây
→ bỏ nếu có sample khác

1–2 giây
→ dùng dự phòng

2–8 giây
→ ưu tiên

> 8 giây
→ vẫn có thể dùng nếu chắc chắn chỉ một speaker,
  hoặc cắt tiếp tại khoảng im lặng
```

---

# 20. OVERLAP — HAI NGƯỜI NÓI CHỒNG NHAU

Ví dụ:

```text
SPEAKER_00: 20.0 → 23.0
SPEAKER_01: 22.1 → 24.5
```

Khoảng:

```text
22.1 → 23.0
```

có hai người nói.

Không nên dùng phần này làm bằng chứng gender.

Phiên bản đầu:

```text
segment có overlap đáng kể
→ loại khỏi gender sample
```

Phiên bản tốt hơn:

```text
giữ phần sạch trước overlap
+
giữ phần sạch sau overlap
```

---

# 21. SEGMENT SELECTOR

File:

```text
ai\gender\segment_selector.py
```

Ví dụ:

```python
from collections import defaultdict


MIN_DURATION = 1.0
PREFERRED_MIN = 2.0
PREFERRED_MAX = 8.0
MAX_SAMPLES_PER_SPEAKER = 5


def get_duration(segment):
    return max(
        0.0,
        float(segment["end"])
        - float(segment["start"])
    )


def select_gender_segments(
    segments,
):
    grouped = defaultdict(list)

    for segment in segments:
        duration = get_duration(
            segment
        )

        if duration < MIN_DURATION:
            continue

        if segment.get(
            "is_overlap",
            False,
        ):
            continue

        grouped[
            segment["speaker"]
        ].append({
            **segment,
            "duration": duration,
        })

    selected = {}

    for speaker, items in (
        grouped.items()
    ):
        preferred = [
            x for x in items
            if (
                PREFERRED_MIN
                <= x["duration"]
                <= PREFERRED_MAX
            )
        ]

        fallback = [
            x for x in items
            if x not in preferred
        ]

        # Ưu tiên sample gần khoảng 4 giây.
        preferred.sort(
            key=lambda x:
            abs(x["duration"] - 4.0)
        )

        # Nếu phải dùng fallback,
        # ưu tiên đoạn dài hơn.
        fallback.sort(
            key=lambda x:
            x["duration"],
            reverse=True,
        )

        selected[speaker] = (
            preferred + fallback
        )[:MAX_SAMPLES_PER_SPEAKER]

    return selected
```

---

# 22. CẮT AUDIO THÀNH WAV 16 KHZ MONO

Dùng FFmpeg.

Tạo:

```text
audio\cropper.py
```

Ví dụ:

```python
import subprocess
from pathlib import Path


def crop_to_whissle_wav(
    source_audio: str,
    output_path: str,
    start: float,
    end: float,
):
    duration = end - start

    output = Path(output_path)

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{start:.3f}",
        "-t", f"{duration:.3f}",
        "-i", source_audio,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(output),
    ]

    subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
```

---

# 23. WHISSLE TỰ XỬ LÝ FEATURE EXTRACTION

Nếu dùng `ASREngine`, bạn không cần tự viết:

```text
mel spectrogram
normalization
STFT
pre-emphasis
padding
```

Repo có preprocessor riêng đọc cấu hình model và tạo input phù hợp cho ONNX.

Do đó:

```python
engine.transcribe(...)
```

an toàn hơn nhiều so với tự tạo tensor đầu vào.

---

# 24. PIPELINE CHO MỘT SPEAKER

Ví dụ diarization cho:

```text
SPEAKER_00
```

12 lượt thoại.

Không cần chạy tất cả 12.

Segment selector chọn:

```text
3.2s
4.0s
5.1s
2.8s
4.6s
```

Whissle:

```text
FEMALE
FEMALE
FEMALE
MALE
FEMALE
```

Resolver:

```text
female = 4 sample
male   = 1 sample
```

Kết luận:

```text
SPEAKER_00 = female
```

---

# 25. KHÔNG GÁN GENDER THEO TỪNG SUBTITLE

Sai:

```text
subtitle 1 → female
subtitle 2 → female
subtitle 3 → male
subtitle 4 → female
```

Điều này làm cùng một nhân vật đổi voice giữa video.

Đúng:

```text
nhiều sample của SPEAKER_00
        ↓
Gender Resolver
        ↓
SPEAKER_00 = female
        ↓
mọi subtitle mang SPEAKER_00
đều kế thừa female
```

---

# 26. RESOLVER THEO THỜI LƯỢNG

File:

```text
ai\gender\gender_resolver.py
```

Ví dụ:

```python
def resolve_gender(
    predictions: list[dict],
    min_consensus: float = 0.65,
):
    male_seconds = 0.0
    female_seconds = 0.0

    for item in predictions:
        gender = item.get(
            "gender",
            "unknown",
        )

        duration = float(
            item.get(
                "duration",
                0.0,
            )
        )

        if gender == "male":
            male_seconds += duration

        elif gender == "female":
            female_seconds += duration

    total = (
        male_seconds
        + female_seconds
    )

    if total <= 0:
        return {
            "gender": "unknown",
            "consensus": 0.0,
            "male_seconds": 0.0,
            "female_seconds": 0.0,
        }

    if male_seconds > female_seconds:
        winner = "male"
        winning_seconds = male_seconds

    elif female_seconds > male_seconds:
        winner = "female"
        winning_seconds = (
            female_seconds
        )

    else:
        return {
            "gender": "unknown",
            "consensus": 0.5,
            "male_seconds": male_seconds,
            "female_seconds": female_seconds,
        }

    consensus = (
        winning_seconds / total
    )

    if consensus < min_consensus:
        winner = "unknown"

    return {
        "gender": winner,
        "consensus": consensus,
        "male_seconds": male_seconds,
        "female_seconds": female_seconds,
    }
```

`consensus` ở đây là:

```text
độ đồng thuận giữa nhiều segment
```

Không nên gọi nó là:

```text
confidence do Whissle trả
```

nếu engine chỉ trả tag label mà không trả xác suất classifier.

---

# 27. GENDER PIPELINE HOÀN CHỈNH

Ví dụ:

```python
from pathlib import Path

from ai.gender.segment_selector import (
    select_gender_segments,
)

from ai.gender.gender_resolver import (
    resolve_gender,
)

from audio.cropper import (
    crop_to_whissle_wav,
)


class GenderPipeline:

    def __init__(
        self,
        whissle_service,
        temp_dir,
    ):
        self.whissle = (
            whissle_service
        )

        self.temp_dir = Path(
            temp_dir
        )

    def analyze(
        self,
        source_audio,
        diarization_segments,
    ):
        selected = (
            select_gender_segments(
                diarization_segments
            )
        )

        profiles = {}

        for speaker, segments in (
            selected.items()
        ):
            predictions = []

            for index, segment in (
                enumerate(segments)
            ):
                output_path = (
                    self.temp_dir
                    / speaker
                    / f"{index:03d}.wav"
                )

                crop_to_whissle_wav(
                    source_audio,
                    str(output_path),
                    segment["start"],
                    segment["end"],
                )

                result = (
                    self.whissle.predict(
                        str(output_path)
                    )
                )

                predictions.append({
                    **segment,
                    **result,
                })

            resolved = (
                resolve_gender(
                    predictions
                )
            )

            profiles[speaker] = {
                **resolved,
                "samples": predictions,
                "source": "whissle_zh",
                "manual_override": False,
            }

        return profiles
```

---

# 28. SPEAKER PROFILE CUỐI CÙNG

Ví dụ:

```json
{
  "SPEAKER_00": {
    "gender": "female",
    "consensus": 0.88,
    "male_seconds": 2.1,
    "female_seconds": 15.7,
    "source": "whissle_zh",
    "manual_override": false
  },
  "SPEAKER_01": {
    "gender": "male",
    "consensus": 0.95,
    "male_seconds": 18.2,
    "female_seconds": 1.0,
    "source": "whissle_zh",
    "manual_override": false
  }
}
```

---

# 29. ÁP GENDER VÀO SUBTITLE

Ví dụ:

```python
def apply_gender_to_subtitles(
    subtitles,
    speaker_profiles,
):
    for subtitle in subtitles:
        speaker = subtitle.get(
            "speaker"
        )

        profile = (
            speaker_profiles.get(
                speaker,
                {},
            )
        )

        subtitle["gender"] = (
            profile.get(
                "gender",
                "unknown",
            )
        )

    return subtitles
```

Sau đó một speaker không tự đổi giới tính giữa video.

---

# 30. AUTO-CAST

Sau khi gender xong mới tính:

```text
total speaking time
utterance count
```

Ví dụ:

```text
SPEAKER_00 female 43s
SPEAKER_01 male   55s
SPEAKER_02 male   14s
SPEAKER_03 female 16s
```

Gán:

```text
SPEAKER_01
→ Nam chính
→ Anh Dũng

SPEAKER_02
→ Nam phụ
→ Minh Quang

SPEAKER_00
→ Nữ chính
→ Cô Gái Hoạt Ngôn

SPEAKER_03
→ Nữ phụ
→ Ngọc Huyền
```

---

# 31. MANUAL OVERRIDE

Dù model tốt vẫn nên cho user sửa:

```text
Nam
Nữ
Không xác định
```

Nếu user sửa:

```text
SPEAKER_00
AI: female
User: male
```

lưu:

```json
{
  "gender": "male",
  "source": "manual",
  "manual_override": true
}
```

Lần phân tích sau không tự overwrite nếu:

```text
manual_override = true
```

---

# 32. CACHE

Không chạy model lại mỗi lần mở video.

Ví dụ:

```text
cache\
└── gender\
    └── project_x_gender.json
```

Dữ liệu:

```json
{
  "video_hash": "....",
  "gender_model": "WhissleAI/STT-zh-mandarin-ONNX",
  "profiles": {
    "SPEAKER_00": {
      "gender": "female",
      "consensus": 0.88,
      "manual_override": false
    }
  }
}
```

Chỉ phân tích lại khi:

```text
video đổi
diarization đổi
model đổi
user bấm Phân tích lại
```

---

# 33. UI KHÔNG ĐƯỢC FREEZE

Whissle chạy CPU nên không chạy inference trên UI thread.

Nếu dùng PyQt/PySide:

```text
Main UI
   ↓
QThread / Worker
   ↓
GenderPipeline
```

Worker có thể emit:

```text
progress
speaker_finished
finished
error
```

UI hiển thị:

```text
Đang nhận diện giới tính...
Speaker 2/4
Sample 3/5
```

---

# 34. TEST TRƯỚC KHI NỐI VỚI DIARIZATION

Chuẩn bị:

```text
male_01.wav
female_01.wav
male_02.wav
female_02.wav
```

Từng file chỉ có một người.

Ví dụ:

```python
files = [
    "male_01.wav",
    "female_01.wav",
    "male_02.wav",
    "female_02.wav",
]

for path in files:
    print(
        path,
        gender_service.predict(path)
    )
```

Chỉ khi test riêng Whissle ổn mới nối vào pipeline lớn.

---

# 35. BỘ TEST VIDEO

Nên test ít nhất:

```text
1. 1 nam
2. 1 nữ
3. 1 nam + 1 nữ
4. 2 nam + 2 nữ
5. nữ giọng trầm
6. nam giọng cao
7. video có BGM
8. video có SFX
9. hai người nói chồng
10. nhân vật phụ chỉ nói 1 câu
```

Đánh giá cuối theo:

```text
speaker
```

chứ không chỉ từng segment.

---

# 36. PHÂN BIỆT 3 LOẠI LỖI

## Lỗi A — Diarization

Thực tế:

```text
Nữ chính
Nữ phụ
```

nhưng diarization:

```text
SPEAKER_00
```

Whissle trả:

```text
female
```

Whissle không sai.

Sai ở speaker separation.

## Lỗi B — Gender

Diarization đúng:

```text
SPEAKER_01 = một người nam
```

nhưng Whissle trên nhiều sample lại thường trả female.

Đây mới là lỗi gender.

## Lỗi C — Auto-Cast

Gender đúng:

```text
SPEAKER_01 = male
```

nhưng tool lại gán voice nữ.

Đây là lỗi mapping/Auto-Cast.

---

# 37. TRƯỜNG HỢP `NONE`

Map:

```text
NONE
→ unknown
```

Không ép thành:

```text
male
```

hoặc:

```text
female
```

Có thể lấy thêm sample khác của cùng speaker.

Nếu vẫn không rõ:

```text
để user chọn thủ công
```

---

# 38. LOGGING

Nên log kiểu:

```text
[Gender] Loading Whissle model...
[Gender] Whissle model loaded.

[Gender] SPEAKER_00: selected 5 samples
[Gender] sample_01 3.2s -> FEMALE
[Gender] sample_02 4.1s -> FEMALE
[Gender] sample_03 5.0s -> FEMALE
[Gender] sample_04 2.8s -> MALE
[Gender] sample_05 4.5s -> FEMALE

[Gender] SPEAKER_00 final = female
[Gender] consensus = 0.86
```

Nhờ vậy debug được:

```text
Whissle sai?
segment sai?
diarization sai?
resolver sai?
auto-cast sai?
```

---

# 39. TỐI ƯU HIỆU NĂNG

Ví dụ video có:

```text
120 lượt thoại
4 speaker
```

Không cần 120 lần inference.

Chỉ lấy:

```text
5 sample × 4 speaker
= khoảng 20 inference
```

Sau khi khóa gender:

```text
không chạy Whissle cho 100 câu còn lại
```

Điều này rất quan trọng vì bạn chạy CPU.

---

# 40. CHỌN SAMPLE THÔNG MINH HƠN Ở V2

Có thể chấm điểm:

```text
sample_score =
    duration_score
  + speech_ratio_score
  + volume_score
  - overlap_penalty
  - noise_penalty
  - music_penalty
```

Sau đó lấy Top 3–5 segment mỗi speaker.

---

# 41. NẾU SPEAKER CHỈ CÓ 1 ĐOẠN NGẮN

Ví dụ nhân vật phụ chỉ nói:

```text
0.7 giây
```

Không nên kết luận quá mạnh.

Có thể:

```text
gender = unknown
```

Nếu 1.5–2 giây và âm thanh rất rõ, có thể dùng nhưng đánh dấu:

```text
low evidence
```

---

# 42. MODEL LOAD / MEMORY

Model ONNX khá lớn.

Do đó:

```text
load một lần
reuse nhiều lần
```

Không:

```text
load/unload cho từng segment
```

Khi user đóng project, bạn có thể giữ service nếu còn xử lý video khác.

Nếu muốn giải phóng RAM:

```text
del engine
gc.collect()
```

nhưng chỉ làm khi thật sự cần.

---

# 43. CÁCH KHỞI TẠO KHI MỞ TOOL

Khuyến nghị lazy load.

Khi mở tool:

```text
chưa load Whissle
```

Khi user chạy:

```text
Phân tích nhân vật
```

thì:

```text
Đang tải model nhận diện giới tính...
```

Sau khi load xong:

```text
Đang phân tích SPEAKER_00...
```

Như vậy app mở nhanh hơn.

---

# 44. VÌ SAO WINDOWS NATIVE NÀY HỢP VỚI TOOL CỦA BẠN

Bạn đang cần tool desktop:

```text
1 file .exe / app Windows
```

Nếu bắt user:

```text
cài Ubuntu
mở WSL
chạy server
giữ terminal
```

thì deployment rất bất tiện.

Windows-native:

```text
tool.exe
  ↓
Python runtime / packaged runtime
  ↓
ONNX Runtime
  ↓
Whissle model local
```

phù hợp hơn cho sản phẩm desktop.

---

# 45. KHI BUILD `.EXE`

Khi chức năng đã chạy tốt bằng Python mới build.

Không build ngay từ đầu.

Các phần cần đóng gói/chỉ đường dẫn:

```text
models\whissle_zh\...
Whissle Python package/source
onnxruntime DLLs
sentencepiece
librosa/soundfile dependencies
FFmpeg nếu app bundle FFmpeg
```

Nên để model ngoài executable:

```text
Tool.exe
models\
  whissle_zh\
```

Không nhét model ~600 MB vào một file `.exe` duy nhất nếu không cần.

---

# 46. THỨ TỰ TRIỂN KHAI

## Bước 1

Tạo branch:

```bash
git checkout -b feature/windows-whissle-gender
```

## Bước 2

Clone repo Whissle trên Windows.

## Bước 3

Tạo/activate Python 3.11 venv.

## Bước 4

```powershell
pip install -e .
```

## Bước 5

Accept model license trên Hugging Face.

## Bước 6

Download model bằng `snapshot_download`.

## Bước 7

Test 1 file giọng nam.

## Bước 8

Test 1 file giọng nữ.

## Bước 9

Tạo `WhissleGenderService`.

## Bước 10

Nối output diarization.

## Bước 11

Viết segment selector.

## Bước 12

Loại overlap.

## Bước 13

Crop WAV 16k mono.

## Bước 14

Chạy 3–5 sample / speaker.

## Bước 15

Gender resolver.

## Bước 16

Speaker profile.

## Bước 17

Cache.

## Bước 18

Manual override.

## Bước 19

Auto-Cast.

## Bước 20

Test video 2–5 phút thật.

---

# 47. ACCEPTANCE CRITERIA V1

Chức năng coi là hoàn thành khi:

- [ ] Không WSL.
- [ ] Không Ubuntu.
- [ ] Không Docker.
- [ ] Không local HTTP server.
- [ ] Whissle chạy trực tiếp trong Python trên Windows.
- [ ] ONNX Runtime chạy bằng CPU.
- [ ] Model load một lần.
- [ ] Audio đưa vào chuẩn 16 kHz mono.
- [ ] Không cắt video cố định mỗi vài giây.
- [ ] Segment lấy từ diarization.
- [ ] Segment overlap không dùng cho gender.
- [ ] Mỗi speaker dùng nhiều sample nếu có thể.
- [ ] Gender resolve theo `SPEAKER_ID`.
- [ ] `NONE` hoặc thiếu kết quả → `unknown`.
- [ ] Không ép `unknown` thành nam/nữ.
- [ ] Không đổi giới tính ở từng subtitle.
- [ ] Có manual override.
- [ ] Có cache.
- [ ] Auto-Cast chạy sau gender resolution.
- [ ] UI không freeze.
- [ ] Log phân biệt được diarization/gender/autocast error.

---

# 48. GIAI ĐOẠN SAU

Whissle chỉ giải quyết:

```text
Nam / Nữ / Unknown
```

Nếu vấn đề còn lại là:

```text
Nữ chính + Nữ phụ
→ bị diarization gộp thành SPEAKER_00
```

thì nâng cấp bằng:

```text
speaker embedding
speaker re-clustering
face tracking
lip activity
```

Không nên cố bắt Whissle giải quyết identity.

---

# 49. NGUỒN CHÍNH

Repo inference:

```text
https://github.com/WhissleAI/whissle_stt_inference
```

Model Mandarin ONNX:

```text
https://huggingface.co/WhissleAI/STT-zh-mandarin-ONNX
```

Các file source đặc biệt quan trọng trong repo:

```text
src/__init__.py
src/engine.py
src/preprocessor.py
src/decoder.py
pyproject.toml
```

---

# 50. KẾT LUẬN

Đối với tool của bạn, hướng nên dùng là:

```text
Windows 11
   ↓
Python tool
   ↓
Whissle ASREngine
   ↓
ONNX Runtime CPU
   ↓
Whissle Mandarin model local
   ↓
MALE / FEMALE / NONE
```

Không cần:

```text
Ubuntu
WSL
Docker
FastAPI
HTTP localhost
```

Sau khi model đã tải về, phần nhận diện gender có thể chạy local trực tiếp:

```python
result = engine.transcribe(
    segment_wav,
    use_lm=False,
)

gender = (
    result.get("tags", {})
    .get("gender")
)
```

Đây là kiến trúc phù hợp nhất để tích hợp chức năng nhận diện nam/nữ vào tool desktop Windows của bạn.

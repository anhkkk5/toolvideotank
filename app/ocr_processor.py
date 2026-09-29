import os
import re
import subprocess
import time

import cv2
import numpy as np

from runtime_paths import bin_path, subprocess_hidden_kwargs, subprocess_text_kwargs

_OCR_ENGINE = None
_OCR_ENGINE_LOCK = None


class _ReusableDetectorPreProcess:
    """RapidOCR detector preprocessing with reusable numeric work buffers.

    The arithmetic intentionally mirrors RapidOCR's DetPreProcess: the input
    is converted/scaled in float32, then mean/std operations occur in float64
    because RapidOCR's mean/std arrays are float64, and the final NCHW tensor
    is float32.  Only temporary allocations are changed; tensor shape, dtype,
    channel order, and numerical values remain equivalent.
    """

    def __init__(self, target, shared_buffers):
        self._target = target
        self._shared_buffers = shared_buffers

    def __getattr__(self, name):
        return getattr(self._target, name)

    def __call__(self, image):
        resized = self._target.resize(image)
        if resized is None:
            return None

        shape = tuple(resized.shape)
        buffers = self._shared_buffers.get(shape)
        if buffers is None:
            height, width, channels = shape
            buffers = {
                "float32": np.empty(shape, dtype=np.float32),
                "float64": np.empty(shape, dtype=np.float64),
                "output": np.empty((1, channels, height, width), dtype=np.float32),
            }
            self._shared_buffers[shape] = buffers

        float32_buffer = buffers["float32"]
        float64_buffer = buffers["float64"]
        output = buffers["output"]

        np.copyto(float32_buffer, resized, casting="unsafe")
        float32_buffer *= self._target.scale
        np.copyto(float64_buffer, float32_buffer, casting="unsafe")
        float64_buffer -= self._target.mean
        float64_buffer /= self._target.std
        np.copyto(output[0], float64_buffer.transpose((2, 0, 1)), casting="unsafe")
        return output


def _enable_reusable_detector_preprocess(engine):
    """Install the validated detector-only optimization on one OCR engine."""
    detector = getattr(engine, "text_det", None)
    if detector is None or getattr(detector, "_capcap_reusable_preprocess", False):
        return engine
    original_get_preprocess = detector.get_preprocess
    shared_buffers = {}

    def get_preprocess(max_side):
        target = original_get_preprocess(max_side)
        return _ReusableDetectorPreProcess(target, shared_buffers)

    detector.get_preprocess = get_preprocess
    detector._capcap_reusable_preprocess = True
    return engine

MAX_CROP_WIDTH = 960
EMPTY_TOLERANCE = 2
EXACT_HASH_THRESHOLD = 5.0
_OCR_MODEL_SETS = (
    (
        "PP-OCRv4",
        (
            "ch_PP-OCRv4_det_mobile.onnx",
            "ch_PP-OCRv4_rec_mobile.onnx",
            "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
            "ppocr_keys_v1.txt",
        ),
    ),
    (
        "PP-OCRv6",
        (
            "PP-OCRv6_det_small.onnx",
            "PP-OCRv6_rec_small.onnx",
            "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        ),
    ),
)
_OCR_HANDLE_RE = re.compile(r"@\s*[A-Za-z0-9_\-\u3400-\u9fff]{1,24}")
_OCR_WATERMARK_PATTERNS = [
    re.compile(r"[\u3400-\u9fff]{1,6}漫(?:剧|居|刷)"),
    re.compile(r"专店"),
    re.compile(r"剧情(?:需要)?\s*请勿模仿"),
    re.compile(r"请勿模仿"),
    re.compile(r"全剧(?:纯属)?虚构"),
    re.compile(r"请勿当真"),
    re.compile(r"仅供娱乐"),
    re.compile(r"谨防上当受骗"),
    re.compile(r"备注\s*[:：].*"),
]


def _onnx_cuda_provider_ready() -> tuple[bool, str]:
    """Return whether ONNX Runtime's CUDA provider can actually load.

    ``get_available_providers`` only reports that the provider was compiled
    into the installed package.  It does not verify dependent CUDA DLLs.
    RapidOCR otherwise tries every model with CUDA, emits repeated loader
    errors, then silently runs each one on CPU.
    """
    try:
        import onnxruntime
        if "CUDAExecutionProvider" not in onnxruntime.get_available_providers():
            return False, "CUDAExecutionProvider is not installed"
        if os.name == "nt":
            import ctypes
            provider_dll = os.path.join(
                os.path.dirname(onnxruntime.__file__), "capi", "onnxruntime_providers_cuda.dll"
            )
            if not os.path.isfile(provider_dll):
                return False, "onnxruntime CUDA provider DLL is not installed"
            try:
                ctypes.WinDLL(provider_dll)
            except OSError as exc:
                return False, str(exc)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _get_lock():
    global _OCR_ENGINE_LOCK
    if _OCR_ENGINE_LOCK is None:
        import threading
        _OCR_ENGINE_LOCK = threading.Lock()
    return _OCR_ENGINE_LOCK


def _ffmpeg_path():
    return os.path.join(bin_path("ffmpeg"), "ffmpeg.exe")


def _ocr_model_variant(model_dir):
    """Return the complete PP-OCR model family installed in ``model_dir``."""
    for variant, required_files in _OCR_MODEL_SETS:
        if all(os.path.isfile(os.path.join(model_dir, name)) for name in required_files):
            return variant
    return ""


def _load_ocr_engine():
    global _OCR_ENGINE
    with _get_lock():
        if _OCR_ENGINE is not None:
            return _OCR_ENGINE

        from runtime_paths import join_root
        cuda_bin = join_root("bin", "cuda12_fw")
        if os.path.isdir(cuda_bin):
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(cuda_bin)
                except Exception:
                    pass
            os.environ["PATH"] = cuda_bin + os.pathsep + os.environ.get("PATH", "")

        # PyInstaller one-dir builds place collected data below _internal,
        # while source installs keep it beside rapidocr.__file__.  A user may
        # also download the model files into the writable application root.
        # Prefer a complete directory so an empty placeholder never shadows a
        # complete bundled copy.
        try:
            import rapidocr
            package_models_dir = os.path.join(os.path.dirname(rapidocr.__file__), "models")
        except Exception:
            package_models_dir = ""
        import sys
        candidates = []
        try:
            from runtime_paths import bundle_root, join_root
            candidates.append(join_root("rapidocr", "models"))
            candidates.append(join_root("models", "rapidocr", "models"))
        except Exception:
            pass
        candidates.append(package_models_dir)
        meipass = getattr(sys, "_MEIPASS", "") or ""
        if meipass:
            candidates.append(os.path.join(meipass, "rapidocr", "models"))
            candidates.append(os.path.join(meipass, "models", "rapidocr", "models"))
        try:
            candidates.append(os.path.join(bundle_root(), "rapidocr", "models"))
            candidates.append(os.path.join(bundle_root(), "models", "rapidocr", "models"))
        except Exception:
            pass
        candidates = [path for path in candidates if path]
        models_dir = next((path for path in candidates if _ocr_model_variant(path)), "")
        print(f"[OCR] Model directory: {models_dir or '<not found>'}")

        variant = _ocr_model_variant(models_dir) if models_dir else ""
        if not variant:
            raise RuntimeError(
                "RapidOCR model files were not found. Install a complete PP-OCRv4 "
                "or PP-OCRv6 model set, then open Settings → Manage Resources.\n\n"
                f"Looked in: {', '.join(candidates) or 'rapidocr package directory'}"
            )

        from rapidocr import RapidOCR
        # Always pass the resolved directory explicitly.  RapidOCR otherwise
        # derives it from its installed-package path, which is unreliable in
        # a PyInstaller bundle and can surface as a generic "No such file or
        # directory" error in the OCR Translator worker.
        cpu_threads = min(8, max(2, os.cpu_count() or 4))
        base_params = {
            "Global.log_level": "error",
            "Global.model_root_dir": models_dir,
            "Det.limit_type": "max",
            "Det.limit_side_len": int(os.getenv("OCR_DET_LIMIT_SIDE_LEN", "960")),
            "EngineConfig.onnxruntime.intra_op_num_threads": cpu_threads,
        }
        if variant == "PP-OCRv4":
            # RapidOCR 3.x defaults to PP-OCRv6.  Select the legacy model
            # files explicitly when the user downloads the PP-OCRv4 pack.
            base_params.update({
                "Det.model_path": os.path.join(models_dir, "ch_PP-OCRv4_det_mobile.onnx"),
                "Rec.model_path": os.path.join(models_dir, "ch_PP-OCRv4_rec_mobile.onnx"),
                "Rec.rec_keys_path": os.path.join(models_dir, "ppocr_keys_v1.txt"),
                "Cls.model_path": os.path.join(models_dir, "ch_ppocr_mobile_v2.0_cls_mobile.onnx"),
            })
        cuda_ready, cuda_reason = _onnx_cuda_provider_ready()
        if cuda_ready:
            try:
                _OCR_ENGINE = RapidOCR(params={
                    **base_params,
                    "EngineConfig.onnxruntime.use_cuda": True,
                })
                print(f"[OCR] RapidOCR engine loaded ({variant} ONNX, CUDA GPU)")
            except Exception as exc:
                # This covers a genuine RapidOCR initialization failure after
                # the provider itself loaded successfully.
                _OCR_ENGINE = RapidOCR(params=base_params)
                print(f"[OCR] CUDA initialization failed; using CPU ({variant}): {exc}")
        else:
            _OCR_ENGINE = RapidOCR(params=base_params)
            detail = f" ({cuda_reason})" if cuda_reason else ""
            print(f"[OCR] CUDA unavailable; using CPU OCR ({variant}){detail}")
        _enable_reusable_detector_preprocess(_OCR_ENGINE)
        return _OCR_ENGINE


def _open_video(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"[OCR] Cannot open video: {video_path}")
    return cap


def crop_subtitle_region(image, region="bottom"):
    h, w = image.shape[:2]
    rect_str = os.getenv("OCR_SUBTITLE_RECT", "")
    if rect_str:
        try:
            parts = [float(x) for x in rect_str.split(",")]
            if len(parts) == 4:
                rx, ry, rw_val, rh = parts
                x1 = int(rx * w)
                y1 = int(ry * h)
                x2 = int((rx + rw_val) * w)
                y2 = int((ry + rh) * h)
                return image[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        except Exception:
            pass
    effective_region = (os.getenv("OCR_SUBTITLE_REGION") or region or "bottom").strip().lower()
    if effective_region == "bottom":
        if h > w:
            # Vertical short-drama video (9:16): dialogue subtitles are placed in the lower-middle band (56% to 74% height)
            # This precisely avoids bottom receipts, letters, TikTok progress bars, and chest clothing prints.
            top = int(h * float(os.getenv("OCR_VERTICAL_TOP_RATIO", "0.56")))
            bottom = int(h * float(os.getenv("OCR_VERTICAL_BOTTOM_RATIO", "0.74")))
            return image[top:bottom, 0:w]
        else:
            ratio = float(os.getenv("OCR_CROP_RATIO", "0.28"))
            top = int(h * (1.0 - ratio))
            bottom = int(h * 0.96)
            return image[top:bottom, 0:w]
    elif effective_region == "top":
        ratio = float(os.getenv("OCR_CROP_RATIO", "0.28"))
        return image[0:int(h * ratio), 0:w]
    else:
        return image


def preprocess_for_ocr(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
    return cv2.cvtColor(clahe.apply(gray), cv2.COLOR_GRAY2BGR)


def _crop_hash(image):
    small = cv2.resize(image, (64, 64), interpolation=cv2.INTER_NEAREST)
    return small.astype(np.float32).mean(axis=(0, 1))


def _hamming_distance(h1, h2):
    return float(np.sum(np.abs(h1.astype(np.float32) - h2.astype(np.float32))))


def _sanitize_ocr_line(text: str) -> str:
    cleaned = " ".join(str(text or "").replace("\n", " ").split()).strip()
    if not cleaned:
        return ""
    cleaned = _OCR_HANDLE_RE.sub(" ", cleaned)
    for pattern in _OCR_WATERMARK_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"^\d+[\.\s、:：]+", "", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" -_.,;:!?|/\\[]{}()<>'\"`~")
    if not cleaned:
        return ""

    # Check if text has any valid dialogue characters (Chinese/CJK or Latin letters)
    has_cjk = bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", cleaned))
    has_letters = bool(re.search(r"[A-Za-z\u00C0-\u024F\u1EA0-\u1EF9]", cleaned))
    if not has_cjk and not has_letters:
        # Standalone numbers (e.g. "96", "100%"), timestamps, or punctuation without words
        return ""

    if has_cjk:
        # Common Chinese OCR glyph misrecognitions:
        # '7' or 'J' attached to or right after a Chinese character is almost always an OCR misread of '了'
        # e.g., '咋7' -> '咋了', '来7' -> '来了', '对J' -> '对了', '太7' -> '太了'
        cleaned = re.sub(r"(?<=[\u4e00-\u9fff\u3400-\u4dbf])\s*[7J](?=[^\d]|$)", "了", cleaned)

    # Filter out non-dialogue text (food receipts, medication deliveries, address headers, letter salutations, ads)
    if re.search(
        r"(?:份餐具|外卖|送药|医药也快|A栋|a栋|To\s*[\u4e00-\u9fff]|排骨.*必涌泉|"
        r"想卖闲置|卖闲置|闲置.*嫌麻烦|转转.*二手|二手.*转卖|点击评论区|主页有|评论区置顶|关注公众号|私信获取)",
        cleaned,
    ):
        return ""

    # Discard isolated single Chinese character (unless common modal particles/interjections)
    if has_cjk and len(cleaned) == 1:
        if cleaned not in {"啊", "哦", "喂", "嗯", "好", "对", "走", "行", "没", "你", "我"}:
            return ""

    if not has_cjk:
        # Isolated English words/letters are almost always clothing prints or background logos (CALIFORN, SOSTINE, SOS, R, V)
        words = cleaned.split()
        if len(words) < 3:
            return ""

    # Discard single punctuation or single non-cjk noise characters
    if len(cleaned) == 1 and not has_cjk and not cleaned.isalnum():
        return ""

    return cleaned


def _is_blank_region(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    if float(lap.var()) < 15.0:
        return True
    bright_ratio = float(np.sum(gray > 180)) / gray.size
    # Small, single-character white subtitles can occupy only about 0.05% of a
    # expanded crop.
    if bright_ratio > 0.0003:
        return False
    return True


def ocr_frame(engine, image, profiling=None, return_details=False):
    """OCR one frame and optionally accumulate lightweight aggregate timings."""
    preprocess_started = time.perf_counter()
    h, w = image.shape[:2]
    orig_w, orig_h = w, h
    if w > MAX_CROP_WIDTH:
        scale = MAX_CROP_WIDTH / w
        new_w = MAX_CROP_WIDTH
        new_h = int(h * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        w, h = new_w, new_h
    if profiling is not None:
        profiling["crop_preprocess"] += time.perf_counter() - preprocess_started

    inference_started = time.perf_counter()
    result = engine(image, use_cls=False, text_score=0.40, box_thresh=0.30)
    inference_elapsed = time.perf_counter() - inference_started
    if profiling is not None:
        profiling["ocr_inference"] += inference_elapsed
        profiling["ocr_inference_samples"].append(inference_elapsed)

    postprocess_started = time.perf_counter()
    texts = []
    details = []
    
    raw_txts = getattr(result, "txts", None)
    if raw_txts is None:
        raw_txts = []
    elif not isinstance(raw_txts, (list, tuple)):
        raw_txts = list(raw_txts)

    raw_boxes = getattr(result, "boxes", None)
    if raw_boxes is None:
        raw_boxes = []
    elif hasattr(raw_boxes, "tolist"):
        raw_boxes = raw_boxes.tolist()
    elif not isinstance(raw_boxes, (list, tuple)):
        raw_boxes = list(raw_boxes)

    raw_scores = getattr(result, "scores", None)
    if raw_scores is None:
        raw_scores = []
    elif hasattr(raw_scores, "tolist"):
        raw_scores = raw_scores.tolist()
    elif not isinstance(raw_scores, (list, tuple)):
        raw_scores = list(raw_scores)

    for idx, raw_text in enumerate(raw_txts):
        cleaned = _sanitize_ocr_line(raw_text)
        if cleaned:
            texts.append(cleaned)
            box = raw_boxes[idx] if idx < len(raw_boxes) else None
            score = float(raw_scores[idx]) if idx < len(raw_scores) else 0.8
            
            norm_box = None
            if box is not None and len(box) >= 4:
                try:
                    xs = [pt[0] for pt in box]
                    ys = [pt[1] for pt in box]
                    norm_box = [
                        round(float(min(xs)) / max(1.0, float(w)), 4),
                        round(float(min(ys)) / max(1.0, float(h)), 4),
                        round(float(max(xs)) / max(1.0, float(w)), 4),
                        round(float(max(ys)) / max(1.0, float(h)), 4),
                    ]
                except Exception:
                    norm_box = None
            
            details.append({
                "text": cleaned,
                "bbox": norm_box or [0.1, 0.7, 0.9, 0.95],
                "confidence": round(score, 3)
            })

    if profiling is not None:
        profiling["postprocess"] += time.perf_counter() - postprocess_started
        
    if return_details:
        return texts, details
    return texts


def extract_ocr_text_from_video_region(video_path, position_seconds, normalized_rect):
    """Read text from one explicitly requested video-frame region.

    This is intentionally separate from ``transcribe_video_ocr``: it never
    creates subtitle segments, reads no OCR environment settings, and only
    performs work when the caller explicitly requests a capture.
    """
    if not video_path or not os.path.isfile(video_path):
        raise RuntimeError("Please load a video before capturing text.")
    try:
        rx, ry, rw, rh = [float(value) for value in normalized_rect]
    except (TypeError, ValueError):
        raise RuntimeError("The OCR Translator selection is invalid.")
    rx, ry = max(0.0, min(1.0, rx)), max(0.0, min(1.0, ry))
    rw, rh = max(0.001, min(1.0 - rx, rw)), max(0.001, min(1.0 - ry, rh))

    cap = _open_video(video_path)
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(position_seconds)) * 1000.0)
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        raise RuntimeError("Could not capture the current video frame.")

    height, width = frame.shape[:2]
    left, top = int(rx * width), int(ry * height)
    right, bottom = int((rx + rw) * width), int((ry + rh) * height)
    crop = frame[max(0, top):min(height, bottom), max(0, left):min(width, right)]
    if crop.size == 0:
        raise RuntimeError("The OCR Translator selection is outside the video frame.")
    if crop.shape[1] > MAX_CROP_WIDTH:
        scale = MAX_CROP_WIDTH / float(crop.shape[1])
        crop = cv2.resize(crop, (MAX_CROP_WIDTH, max(1, int(crop.shape[0] * scale))), interpolation=cv2.INTER_LINEAR)

    engine = _load_ocr_engine()
    result = engine(crop, use_cls=False, text_score=0.45, box_thresh=0.35)
    # Unlike subtitle OCR, retain short labels and UI text: this utility is
    # meant for any visible text rather than only spoken subtitles.
    lines = [" ".join(str(value or "").split()) for value in (result.txts or [])]
    return "\n".join(line for line in lines if line).strip()


def _texts_equal(current_texts, prev_texts):
    if len(current_texts) != len(prev_texts):
        return False
    return all(a == b for a, b in zip(current_texts, prev_texts))


def transcribe_video_ocr(video_path, *, region="bottom", fps=None, ocr_engine=None, start_seconds=0.0, end_seconds=None):
    workflow_started = time.perf_counter()
    profiling = {
        "engine_init": 0.0,
        "seek_decode": 0.0,
        "crop_preprocess": 0.0,
        "change_detection": 0.0,
        "blank_detection": 0.0,
        "ocr_inference": 0.0,
        "ocr_inference_samples": [],
        "postprocess": 0.0,
        "temporal": 0.0,
    }
    duration = 0
    if fps is None:
        try:
            result = subprocess.run(
                [_ffmpeg_path(), "-i", video_path, "-f", "null", "-"],
                capture_output=True, **subprocess_text_kwargs(),
            )
            for line in (result.stderr or "").splitlines():
                if "Duration:" in line:
                    parts = line.split("Duration:")[1].strip().split(",")[0].strip().split(":")
                    duration = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                    break
            else:
                duration = 60
        except Exception:
            duration = 60
        configured_fps = str(os.getenv("OCR_SAMPLING_FPS", "auto") or "auto").strip().lower()
        if configured_fps not in {"", "auto", "default"}:
            try:
                requested_fps = float(configured_fps)
            except ValueError:
                requested_fps = 0.0
            if 0.25 <= requested_fps <= 10.0:
                fps = requested_fps
                print(f"[OCR] Video duration: {duration:.0f}s, configured fps: {fps}")
            else:
                print(f"[OCR] Ignoring invalid OCR_SAMPLING_FPS={configured_fps!r}; using auto.")

        if fps is None:
            # Very short clips often contain title cards or subtitle flashes that
            # last well below one second.  At 1.5 FPS a two-second clip is sampled
            # only at 0.00, 0.67, and 1.33 seconds, which can miss all of them.
            # Four FPS adds only a few frames for these clips while giving a
            # 250 ms sampling interval.
            sampling_duration = duration
            if end_seconds is not None:
                sampling_duration = max(0.0, float(end_seconds) - max(0.0, float(start_seconds or 0.0)))
            if sampling_duration <= 15:
                fps = 3.0
            elif sampling_duration <= 60:
                fps = 1.5
            elif sampling_duration <= 360:
                fps = 1.0
            elif sampling_duration <= 600:
                fps = 0.75
            else:
                fps = 0.5
            range_label = f", selected range: {sampling_duration:.0f}s" if end_seconds is not None else ""
            print(f"[OCR] Video duration: {duration:.0f}s{range_label}, auto fps: {fps}")

    start_seconds = max(0.0, float(start_seconds or 0.0))
    end_seconds = min(float(duration or 0.0), float(end_seconds)) if end_seconds is not None and duration else end_seconds
    frame_interval = 1.0 / fps
    cap = _open_video(video_path)
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_step = max(1, round(video_fps / fps))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    # Include the initial frame at 0 and the final partial sampling interval.
    total_steps = (total_frames + frame_step - 1) // frame_step if total_frames else 0
    if end_seconds is not None:
        total_steps = max(1, int(max(0.0, end_seconds - start_seconds) * fps) + 1)
    if total_steps <= 0:
        total_steps = int(duration * fps) if duration > 0 else 300
    print(f"[OCR] Seeking {total_steps} frames at {fps} fps from video directly...")
    try:
        if ocr_engine is None:
            engine_started = time.perf_counter()
            ocr_engine = _load_ocr_engine()
            profiling["engine_init"] = time.perf_counter() - engine_started

        segments = []
        prev_texts = None
        prev_hash = None
        seg_start = None
        seg_text_lines = []
        empty_streak = 0
        ocr_count = 0
        skip_count = 0
        unchanged_skip_count = 0
        blank_skip_count = 0
        step = max(0, int(start_seconds * fps))
        sampled_count = 0

        while True:
            frame_idx = step * frame_step
            decode_started = time.perf_counter()
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, img = cap.read()
            profiling["seek_decode"] += time.perf_counter() - decode_started
            if not ret or img is None:
                break
            timestamp = frame_idx / video_fps
            if end_seconds is not None and timestamp > float(end_seconds):
                break
            sampled_count += 1
            crop_started = time.perf_counter()
            cropped = crop_subtitle_region(img, region=region)
            profiling["crop_preprocess"] += time.perf_counter() - crop_started
            change_started = time.perf_counter()
            cur_hash = _crop_hash(cropped)
            unchanged = prev_hash is not None and _hamming_distance(cur_hash, prev_hash) < EXACT_HASH_THRESHOLD
            profiling["change_detection"] += time.perf_counter() - change_started

            if unchanged:
                skip_count += 1
                unchanged_skip_count += 1
                texts = list(prev_texts) if prev_texts else []
            else:
                blank_started = time.perf_counter()
                is_blank = _is_blank_region(cropped)
                profiling["blank_detection"] += time.perf_counter() - blank_started
                if is_blank:
                    skip_count += 1
                    blank_skip_count += 1
                    texts = []
                else:
                    texts, details = ocr_frame(ocr_engine, cropped, profiling=profiling, return_details=True)
                    ocr_count += 1
                    prev_hash = cur_hash
                    prev_details = details

            step += 1

            if sampled_count % 30 == 0:
                pct = sampled_count * 100 // total_steps if total_steps > 0 else 0
                print(f"[OCR] Frame {sampled_count}/{total_steps} ({pct}%, OCR: {ocr_count}, skip: {skip_count})")

            temporal_started = time.perf_counter()
            if not texts:
                empty_streak += 1
                if empty_streak >= EMPTY_TOLERANCE and seg_start is not None:
                    end_ts = max(seg_start + frame_interval, timestamp - frame_interval * 0.5)
                    combined = " ".join(seg_text_lines).strip()
                    if combined:
                        seg_bbox = seg_details[0]["bbox"] if seg_details and "bbox" in seg_details[0] else [0.1, 0.7, 0.9, 0.95]
                        seg_conf = seg_details[0]["confidence"] if seg_details and "confidence" in seg_details[0] else 0.85
                        segments.append({
                            "start": seg_start,
                            "end": end_ts,
                            "text": combined,
                            "words": [],
                            "bbox": seg_bbox,
                            "ocr_confidence": seg_conf,
                        })
                    seg_start = None
                    seg_text_lines = []
                    seg_details = []
                    prev_texts = None
                profiling["temporal"] += time.perf_counter() - temporal_started
                continue

            empty_streak = 0
            if prev_texts is not None and _texts_equal(texts, prev_texts):
                profiling["temporal"] += time.perf_counter() - temporal_started
                continue
            if seg_start is not None and seg_text_lines:
                end_ts = max(seg_start + frame_interval, timestamp - frame_interval * 0.5)
                combined = " ".join(seg_text_lines).strip()
                if combined:
                    seg_bbox = seg_details[0]["bbox"] if seg_details and "bbox" in seg_details[0] else [0.1, 0.7, 0.9, 0.95]
                    seg_conf = seg_details[0]["confidence"] if seg_details and "confidence" in seg_details[0] else 0.85
                    segments.append({
                        "start": seg_start,
                        "end": end_ts,
                        "text": combined,
                        "words": [],
                        "bbox": seg_bbox,
                        "ocr_confidence": seg_conf,
                    })
            seg_start = 0.0 if step == 1 else timestamp - frame_interval * 0.5
            seg_text_lines = texts
            seg_details = details if 'details' in locals() and details else []
            prev_texts = texts
            profiling["temporal"] += time.perf_counter() - temporal_started
    finally:
        cap.release()

    final_temporal_started = time.perf_counter()
    if seg_start is not None and seg_text_lines:
        combined = " ".join(seg_text_lines).strip()
        if combined:
            video_duration = total_frames / video_fps if total_frames and video_fps else (total_steps * frame_interval)
            if end_seconds is not None:
                video_duration = min(video_duration, float(end_seconds))
            end_ts = max(seg_start + frame_interval, video_duration)
            if end_seconds is not None:
                end_ts = min(end_ts, float(end_seconds))
            seg_bbox = seg_details[0]["bbox"] if 'seg_details' in locals() and seg_details and "bbox" in seg_details[0] else [0.1, 0.7, 0.9, 0.95]
            seg_conf = seg_details[0]["confidence"] if 'seg_details' in locals() and seg_details and "confidence" in seg_details[0] else 0.85
            segments.append({
                "start": seg_start,
                "end": end_ts,
                "text": combined,
                "words": [],
                "bbox": seg_bbox,
                "ocr_confidence": seg_conf,
            })

    # The temporal loop already keeps identical sampled frames in one cue.
    # Only exact consecutive OCR output is extended below; do not perform a
    # second fuzzy/short-text deduplication pass that can hide valid lines.
    # Adaptive max_gap based on sampling interval (e.g. 1.0s -> 1.2s, 0.67s -> 0.87s, 0.5s -> 0.7s)
    adaptive_max_gap = max(0.7, frame_interval + 0.2)
    merged = _merge_adjacent(segments, max_gap=adaptive_max_gap)
    profiling["temporal"] += time.perf_counter() - final_temporal_started
    print(f"[OCR] Extracted {len(merged)} subtitle segments from {total_steps} frames (OCR: {ocr_count}, skip: {skip_count})")
    inference_samples = profiling["ocr_inference_samples"]
    inference_avg_ms = (sum(inference_samples) / len(inference_samples) * 1000.0) if inference_samples else 0.0
    inference_p95_ms = float(np.percentile(inference_samples, 95) * 1000.0) if inference_samples else 0.0
    sampled_frames = sampled_count
    decode_preprocess_avg_ms = (
        (profiling["seek_decode"] + profiling["crop_preprocess"]) / sampled_frames * 1000.0
        if sampled_frames else 0.0
    )
    print("[OCR Profiling]")
    print(f"Engine initialization: {profiling['engine_init']:.2f}s")
    print(f"Seek/decode: {profiling['seek_decode']:.2f}s")
    print(f"Crop/preprocess: {profiling['crop_preprocess']:.2f}s")
    print(f"Change detection: {profiling['change_detection']:.2f}s")
    print(f"Blank detection: {profiling['blank_detection']:.2f}s")
    print(f"RapidOCR inference: {profiling['ocr_inference']:.2f}s")
    print(f"Post-processing: {profiling['postprocess']:.2f}s")
    print(f"Temporal segments/merge: {profiling['temporal']:.2f}s")
    print(f"Total: {time.perf_counter() - workflow_started:.2f}s")
    print(
        "Frames: "
        f"sampled={sampled_frames}, OCR={ocr_count}, unchanged_skip={unchanged_skip_count}, blank_skip={blank_skip_count}"
    )
    print(f"OCR inference: avg={inference_avg_ms:.0f}ms, p95={inference_p95_ms:.0f}ms")
    print(f"Frame decode/preprocess: avg={decode_preprocess_avg_ms:.0f}ms")
    return merged


def _normalize_ocr_compare_text(text: str) -> str:
    return re.sub(r"[\s\.,?!:;\"'，。？！：；…—_~`/\\[\]()（）{}]+", "", str(text or "")).strip().lower()


def _are_ocr_texts_near_duplicate(text1: str, text2: str, min_similarity: float = 0.90) -> bool:
    t1 = _normalize_ocr_compare_text(text1)
    t2 = _normalize_ocr_compare_text(text2)
    if not t1 or not t2:
        return False
    if t1 == t2:
        return True
    len_diff = abs(len(t1) - len(t2))
    if len_diff > 1:
        return False
    import difflib
    return difflib.SequenceMatcher(None, t1, t2).ratio() >= min_similarity


def _merge_adjacent(segments, max_gap=0.87):
    if not segments:
        return []
    merged = []
    current = dict(segments[0])
    current["text"] = _sanitize_ocr_line(current.get("text", ""))
    for seg in segments[1:]:
        seg = dict(seg)
        seg["text"] = _sanitize_ocr_line(seg.get("text", ""))
        if not seg["text"]:
            continue
        gap = seg["start"] - current["end"]
        # Extend identical or near-duplicate subtitles occurring within adaptive max_gap
        if gap <= max_gap and _are_ocr_texts_near_duplicate(seg["text"], current["text"]):
            current["end"] = max(current["end"], seg["end"])
            if len(seg["text"]) > len(current["text"]):
                current["text"] = seg["text"]
            if "bbox" in seg and "bbox" not in current:
                current["bbox"] = seg["bbox"]
            if "ocr_confidence" in seg:
                current["ocr_confidence"] = max(float(current.get("ocr_confidence", 0.0) or 0.0), float(seg["ocr_confidence"]))
        else:
            if current.get("text"):
                merged.append(current)
            current = dict(seg)
    if current.get("text"):
        merged.append(current)
    return merged


def unload_ocr_engine():
    global _OCR_ENGINE
    with _get_lock():
        _OCR_ENGINE = None
        print("[OCR] Engine unloaded")

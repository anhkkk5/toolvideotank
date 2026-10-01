"""Module dịch vụ AI Inpainting (Xóa Logo, Watermark, khôi phục nền gốc).

Hỗ trợ 2 mô hình:
1. 'lama': Mô hình AI Large Mask Inpainting (LaMa) phục hồi nền gốc chân thực, xóa sạch bóng logo/chữ (tương tự ezremove.ai).
2. 'telea': Thuật toán OpenCV Inpaint Telea nội suy đa hướng siêu tốc (~100+ fps) phù hợp với nền trơn / gradient.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Callable, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from app.services.video_export_service import _resolve_ffmpeg


class VideoInpaintingService:
    """Dịch vụ xóa Watermark / Logo trên video bằng công nghệ AI Inpainting."""

    def __init__(self):
        self._lama_instance = None

    def _get_lama(self):
        if self._lama_instance is None:
            from simple_lama_inpainting import SimpleLama
            self._lama_instance = SimpleLama()
        return self._lama_instance

    def inpaint_video(
        self,
        input_video_path: str,
        output_video_path: str,
        bbox: Tuple[float, float, float, float],
        mode: str = "lama",
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        is_cancelled_cb: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Xóa logo/watermark trong vùng bbox=(x, y, w, h) [chuẩn hóa 0.0 - 1.0].
        
        Args:
            input_video_path: Đường dẫn video nguồn.
            output_video_path: Đường dẫn video xuất xưởng.
            bbox: Tọa độ vùng xóa tỉ lệ (rx, ry, rw, rh) trong khoảng [0.0, 1.0].
            mode: 'lama' (AI Inpainting phục hồi nền chuẩn) hoặc 'telea' (OpenCV siêu tốc).
            progress_cb: Hàm callback (current_frame, total_frames, message).
            is_cancelled_cb: Hàm kiểm tra xem người dùng có bấm hủy không.
        """
        if not input_video_path or not os.path.isfile(input_video_path):
            raise FileNotFoundError(f"Không tìm thấy file video nguồn: {input_video_path}")

        rx, ry, rw, rh = bbox
        if rw <= 0.005 or rh <= 0.005:
            # Vùng chọn quá nhỏ hoặc không hợp lệ -> chỉ copy file
            shutil.copy2(input_video_path, output_video_path)
            return True

        cap = cv2.VideoCapture(input_video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Không thể mở video bằng OpenCV: {input_video_path}")

        vid_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        vid_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1

        # Chuyển đổi tọa độ tỉ lệ sang pixel
        bx = int(round(rx * vid_w))
        by = int(round(ry * vid_h))
        bw = int(round(rw * vid_w))
        bh = int(round(rh * vid_h))

        # Thêm viền đệm (padding) 16px xung quanh để AI quan sát được ngữ cảnh nền xung quanh
        pad = 16
        x1 = max(0, bx - pad)
        y1 = max(0, by - pad)
        x2 = min(vid_w, bx + bw + pad)
        y2 = min(vid_h, by + bh + pad)
        patch_w = x2 - x1
        patch_h = y2 - y1

        # Tạo mask nhị phân cho vùng cần xóa bên trong patch
        mask_patch = np.zeros((patch_h, patch_w), dtype=np.uint8)
        mask_y1 = by - y1
        mask_y2 = mask_y1 + bh
        mask_x1 = bx - x1
        mask_x2 = mask_x1 + bw
        mask_patch[mask_y1:mask_y2, mask_x1:mask_x2] = 255
        mask_pil = Image.fromarray(mask_patch)

        # File video tạm thời (chỉ có luồng hình ảnh)
        dir_name = os.path.dirname(output_video_path) or "."
        os.makedirs(dir_name, exist_ok=True)
        temp_visual_path = os.path.join(dir_name, f"_temp_inpaint_{int(time.time())}.mp4")

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(temp_visual_path, fourcc, fps, (vid_w, vid_h))

        is_lama = str(mode).lower() in ("lama", "inpaint", "ai")
        lama_model = None
        if is_lama:
            if progress_cb:
                progress_cb(0, total_frames, "Đang khởi tạo mô hình AI Inpainting...")
            lama_model = self._get_lama()

        frame_idx = 0
        t0 = time.time()

        try:
            while True:
                if is_cancelled_cb and is_cancelled_cb():
                    cap.release()
                    writer.release()
                    if os.path.exists(temp_visual_path):
                        os.remove(temp_visual_path)
                    return False

                ret, frame = cap.read()
                if not ret:
                    break

                frame_idx += 1

                # Cắt patch vùng chứa logo
                patch_bgr = frame[y1:y2, x1:x2]

                if is_lama and lama_model is not None:
                    patch_rgb = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2RGB)
                    patch_pil = Image.fromarray(patch_rgb)
                    inpainted_pil = lama_model(patch_pil, mask_pil)
                    inpainted_bgr = cv2.cvtColor(np.array(inpainted_pil), cv2.COLOR_RGB2BGR)
                    inpainted_bgr = inpainted_bgr[:patch_h, :patch_w]
                    frame[y1:y2, x1:x2] = inpainted_bgr
                else:
                    # OpenCV Telea inpainting
                    inpainted_patch = cv2.inpaint(patch_bgr, mask_patch, 3, cv2.INPAINT_TELEA)
                    frame[y1:y2, x1:x2] = inpainted_patch

                writer.write(frame)

                if progress_cb and (frame_idx % 5 == 0 or frame_idx == total_frames):
                    pct = int(frame_idx / total_frames * 100)
                    progress_cb(
                        frame_idx,
                        total_frames,
                        f"🤖 Đang xóa watermark bằng AI: {frame_idx}/{total_frames} khung hình ({pct}%)"
                    )

        finally:
            cap.release()
            writer.release()

        # Ghép lại luồng âm thanh gốc 100% bằng FFmpeg (-c:a copy)
        ffmpeg = _resolve_ffmpeg()
        cmd = [
            ffmpeg, "-y",
            "-i", temp_visual_path,
            "-i", input_video_path,
            "-map", "0:v:0",
            "-map", "1:a:0?",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "19",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            output_video_path,
        ]

        kwargs = {"capture_output": True}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.run(cmd, **kwargs)

        # Dọn dẹp video tạm
        if os.path.exists(temp_visual_path):
            try:
                os.remove(temp_visual_path)
            except Exception:
                pass

        if proc.returncode == 0 and os.path.isfile(output_video_path) and os.path.getsize(output_video_path) > 10240:
            if progress_cb:
                progress_cb(total_frames, total_frames, "✅ Xóa watermark thành công!")
            return True
        else:
            # Fallback nếu FFmpeg ghép thất bại
            if os.path.isfile(temp_visual_path):
                shutil.move(temp_visual_path, output_video_path)
                return True
            return False

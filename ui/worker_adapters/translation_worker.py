"""Worker thread for DeepSeek subtitle translation."""

from __future__ import annotations

import os
import sys
import traceback
from typing import Any

from PySide6.QtCore import QThread, Signal

APP_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "app")
if APP_PATH not in sys.path:
    sys.path.insert(0, APP_PATH)

from services.deepseek_service import DeepSeekService, DeepSeekTranslationError
from services.subtitle_translation_service import SubtitleTranslationService


class DeepSeekTranslationWorker(QThread):
    """QThread worker to run DeepSeek translation asynchronously."""

    progress = Signal(str, int, int)      # message, current, total
    row_updated = Signal(dict)            # single row updated in real-time
    finished = Signal(list, dict)         # all_rows, character_memory
    error = Signal(str)                   # error message

    def __init__(
        self,
        rows: list[dict[str, Any]],
        *,
        overwrite_manual: bool = False,
        api_key: str = "",
        model_name: str = "",
        base_url: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.rows = [dict(r) for r in rows]
        self.overwrite_manual = overwrite_manual
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url

    def run(self):
        try:
            deepseek = DeepSeekService(
                api_key=self.api_key,
                model_name=self.model_name,
                base_url=self.base_url,
            )
            service = SubtitleTranslationService(deepseek)

            def on_progress(message: str, current: int, total: int):
                self.progress.emit(message, current, total)

            def on_row_updated(row_data: dict[str, Any]):
                self.row_updated.emit(row_data)

            final_rows, memory = service.translate_with_deepseek(
                self.rows,
                overwrite_manual=self.overwrite_manual,
                progress=on_progress,
                row_callback=on_row_updated,
            )

            self.finished.emit(final_rows, memory)

        except DeepSeekTranslationError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            traceback.print_exc()
            self.error.emit(f"Lỗi không xác định khi dịch phụ đề bằng DeepSeek: {exc}")

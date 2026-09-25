"""Service for loading, saving, and listing Master Datasets."""

from __future__ import annotations

import glob
import hashlib
import json
import os
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.models.master_dataset import MasterDataset


class MasterDatasetService:
    """Quản lý lưu trữ và nạp MasterDataset chuẩn (Single Source of Truth)."""

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not path:
            return ""
        return os.path.normpath(os.path.abspath(path))

    @classmethod
    def get_history_file(cls, workspace_root: str, video_path: str = "", project_root: str = "") -> str:
        """Xác định đường dẫn tệp json lưu trữ lịch sử kiểm tra / master data."""
        if project_root and os.path.isdir(project_root):
            history_dir = os.path.join(project_root, "analysis")
        else:
            source = cls._normalize_path(video_path)
            key = hashlib.sha256(source.lower().encode("utf-8")).hexdigest()[:20] if source else "default"
            history_dir = os.path.join(workspace_root, "projects", "_voice_gender_history", key)

        os.makedirs(history_dir, exist_ok=True)
        return os.path.join(history_dir, "voice_gender_checks.json")

    @classmethod
    def load_entries(cls, file_path: str) -> list[dict[str, Any]]:
        """Nạp danh sách entry thô từ tệp JSON."""
        if not os.path.isfile(file_path):
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            return list(payload.get("entries") or [])
        except (OSError, ValueError, TypeError):
            return []

    @classmethod
    def list_datasets(
        cls,
        workspace_root: str,
        video_path: str = "",
        project_root: str = "",
    ) -> list[MasterDataset]:
        """Lấy danh sách các bản MasterDataset tương ứng với video hoặc dự án."""
        file_path = cls.get_history_file(workspace_root, video_path=video_path, project_root=project_root)
        raw_entries = cls.load_entries(file_path)
        datasets: list[MasterDataset] = []
        for entry in raw_entries:
            try:
                ds = MasterDataset.from_entry(entry)
                if not ds.video_path and video_path:
                    ds.video_path = video_path
                datasets.append(ds)
            except Exception:
                continue
        return datasets

    @classmethod
    def find_all_available_masters(cls, workspace_root: str) -> list[MasterDataset]:
        """Quét toàn bộ thư mục projects để tìm tất cả các bản Master Data đã lưu

        trong workspace. Hữu ích cho Pipeline B khi người dùng muốn chọn bất kỳ video nào.
        """
        all_datasets: list[MasterDataset] = []
        search_pattern = os.path.join(workspace_root, "projects", "**", "voice_gender_checks.json")
        for file_path in glob.glob(search_pattern, recursive=True):
            entries = cls.load_entries(file_path)
            for entry in entries:
                try:
                    ds = MasterDataset.from_entry(entry)
                    all_datasets.append(ds)
                except Exception:
                    continue

        # Sắp xếp mới nhất lên đầu
        all_datasets.sort(key=lambda d: d.created_at or "", reverse=True)
        return all_datasets

    @classmethod
    def load_dataset_by_id(
        cls,
        workspace_root: str,
        entry_id: str,
        video_path: str = "",
        project_root: str = "",
    ) -> MasterDataset | None:
        """Nạp chính xác một MasterDataset theo ID."""
        # 1. Thử tìm trong file cụ thể trước nếu có video_path / project_root
        if video_path or project_root:
            datasets = cls.list_datasets(workspace_root, video_path=video_path, project_root=project_root)
            for ds in datasets:
                if str(ds.id) == str(entry_id):
                    return ds

        # 2. Tìm quét toàn bộ workspace nếu chưa thấy
        all_masters = cls.find_all_available_masters(workspace_root)
        for ds in all_masters:
            if str(ds.id) == str(entry_id):
                return ds
        return None

    @classmethod
    def save_master_dataset(
        cls,
        workspace_root: str,
        dataset: MasterDataset,
        project_root: str = "",
    ) -> str:
        """Lưu hoặc cập nhật một MasterDataset vào file lịch sử an toàn bằng cơ chế temp atomic write."""
        if not dataset.id:
            dataset.id = uuid4().hex
        if not dataset.created_at:
            dataset.created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        dataset.updated_at = datetime.now().astimezone().isoformat(timespec="seconds")

        file_path = cls.get_history_file(workspace_root, video_path=dataset.video_path, project_root=project_root)
        entries = cls.load_entries(file_path)

        new_entry = dataset.to_dict()

        # Kiểm tra xem ID đã tồn tại chưa để update, nếu chưa thì chèn lên đầu
        found_idx = -1
        for i, ent in enumerate(entries):
            if str(ent.get("id")) == str(dataset.id):
                found_idx = i
                break

        if found_idx >= 0:
            entries[found_idx] = new_entry
        else:
            entries.insert(0, new_entry)

        # Giữ tối đa 50 bản ghi gần nhất
        entries = entries[:50]

        temp_file = file_path + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "entries": entries}, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, file_path)

        return dataset.id

    @classmethod
    def delete_master_dataset(
        cls,
        workspace_root: str,
        entry_id: str,
        video_path: str = "",
        project_root: str = "",
    ) -> bool:
        """Xóa một bản ghi MasterDataset khỏi lịch sử."""
        file_path = cls.get_history_file(workspace_root, video_path=video_path, project_root=project_root)
        entries = cls.load_entries(file_path)
        initial_count = len(entries)
        remaining = [ent for ent in entries if str(ent.get("id")) != str(entry_id)]
        if len(remaining) == initial_count:
            return False

        if remaining:
            temp_file = file_path + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "entries": remaining}, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, file_path)
        elif os.path.isfile(file_path):
            os.remove(file_path)

        return True

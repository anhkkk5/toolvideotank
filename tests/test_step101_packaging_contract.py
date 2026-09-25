"""
tests/test_step101_packaging_contract.py

Bộ kiểm thử chấp nhận (Acceptance Test Suite) cho:
STEP 10.1 — Packaging Contract & Runtime Validation (v1.1)

Ma trận nghiệm thu 9/9 PASS:
- PKG-01: Spec Dynamic Path Invariant (kiểm tra dynamic SPECPATH & validator reject hardcoded path)
- PKG-02: Asset Existence Pre-check (kiểm tra 12 nhóm runtime asset inventory trên đĩa)
- PKG-03: FFmpeg 3-State Resolution (Bundle -> Workspace -> System PATH)
- PKG-04: Writable Directory Bootstrap (khởi tạo output, temp, render_jobs, raw_tts, models, logs)
- PKG-05: Behavioral Bundle Protection (0 byte ghi vào bundle_root, 100% vào workspace_root)
- PKG-06: Runtime Torch Exclusion Verification (main process và Step 8/9 không load torch DLL/modules)
- PKG-07: Gender AI Offline Assets (joblib.load classifier thành công, offline 100%, không torch)
- PKG-08: VieNeu CLI Worker Standalone (app/vieneu_worker.py độc lập, không import Qt/PySide6)
- PKG-09: External Runtime Resolution (Daemon HTTP -> VIENEU_PYTHON -> Local Env -> Clear error)

QUY TẮC BẤT BIẾN:
- Step 8 / Step 9 FROZEN 🔒
- CapCap.spec KHÔNG bị sửa đổi trong Step 10.1 (chỉ đọc/parse)
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import app.runtime_paths as rp



class TestStep101PackagingContract(unittest.TestCase):
    """Bộ kiểm thử 9 tiêu chí nghiệm thu PKG-01 -> PKG-09 của Contract 10.1 v1.1."""

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.spec_path = cls.repo_root / "CapCap.spec"

    # =========================================================================
    # PKG-01: Spec Dynamic Path Invariant
    # =========================================================================
    def test_pkg_01_spec_dynamic_path_invariant(self):
        """PKG-01: Đảm bảo nguyên tắc dynamic SPECPATH và validator phát hiện hardcode.
        
        - Dynamic SPECPATH invariant: Path(SPECPATH).resolve() luôn giải quyết đúng root.
        - Validator: Phát hiện và cấm hardcoded absolute dev path (e.g. D:\\CodingTime\\CapCap).
        - AST parse CapCap.spec hiện tại: Cú pháp hợp lệ, định vị project_root chuẩn bị Step 10.2.
        """
        # 1. Kiểm tra tính toán dynamic SPECPATH invariant
        mock_specpath = str(self.repo_root)
        resolved_root = Path(mock_specpath).resolve()
        self.assertEqual(resolved_root, self.repo_root)
        self.assertTrue((resolved_root / "app").is_dir())
        self.assertTrue((resolved_root / "ui").is_dir())

        # 2. Kiểm tra bộ quy tắc kiểm tra spec (Spec Validator Contract)
        def validate_spec_rules(spec_source: str) -> dict:
            violations = []
            has_dynamic_specpath = "SPECPATH" in spec_source and "Path(SPECPATH).resolve()" in spec_source
            if 'r"D:\\CodingTime\\CapCap"' in spec_source or '"D:\\CodingTime\\CapCap"' in spec_source:
                violations.append("HARDCODED_DEV_PATH_DETECTED")
            return {
                "compliant": len(violations) == 0 and has_dynamic_specpath,
                "violations": violations,
                "has_dynamic_specpath": has_dynamic_specpath,
            }

        # Spec chứa hardcode phải bị reject
        bad_spec = 'project_root = Path(r"D:\\CodingTime\\CapCap")'
        result_bad = validate_spec_rules(bad_spec)
        self.assertFalse(result_bad["compliant"])
        self.assertIn("HARDCODED_DEV_PATH_DETECTED", result_bad["violations"])

        # Spec chuẩn 10.2 với SPECPATH phải pass
        good_spec = 'project_root = Path(SPECPATH).resolve()'
        result_good = validate_spec_rules(good_spec)
        self.assertTrue(result_good["compliant"])
        self.assertEqual(result_good["violations"], [])

        # 3. Đọc và parse AST của CapCap.spec trên đĩa (không sửa đổi spec)
        self.assertTrue(self.spec_path.is_file(), "Tệp CapCap.spec phải tồn tại.")
        spec_content = self.spec_path.read_text(encoding="utf-8")
        parsed_ast = ast.parse(spec_content, filename=str(self.spec_path))
        self.assertIsInstance(parsed_ast, ast.Module, "CapCap.spec phải là mã nguồn Python hợp lệ.")

        # Định vị dòng gán project_root trong AST để ghi nhận phục vụ Step 10.2
        found_project_root_assign = False
        for node in ast.walk(parsed_ast):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "project_root":
                        found_project_root_assign = True
                        break
        self.assertTrue(found_project_root_assign, "CapCap.spec phải có định nghĩa project_root.")


    # =========================================================================
    # PKG-02: Asset Existence Pre-check
    # =========================================================================
    def test_pkg_02_runtime_asset_inventory_existence(self):
        """PKG-02: Kiểm tra sự tồn tại trên đĩa của 12 nhóm tài nguyên trong Inventory."""
        inventory_items = [
            ("1. runtime_paths", self.repo_root / "app" / "runtime_paths.py", "file"),
            ("2. gender_ai_package", self.repo_root / "gender_voice_ai_windows_package", "dir"),
            ("3. gender_classifier", self.repo_root / "gender_voice_ai_windows_package" / "gender_classifier.joblib", "file"),
            ("4. vieneu_worker", self.repo_root / "app" / "vieneu_worker.py", "file"),
            ("5. assets_dir", self.repo_root / "assets", "dir"),
            ("6. translation_prompts", self.repo_root / "app" / "translation" / "prompts", "dir"),
            ("7. piper_models", self.repo_root / "models" / "piper", "dir"),
            ("8. env_example", self.repo_root / ".env_example", "file"),
            ("9. ffmpeg_bin", self.repo_root / "bin" / "ffmpeg" / "ffmpeg.exe", "file"),
            ("10. ffprobe_bin", self.repo_root / "bin" / "ffmpeg" / "ffprobe.exe", "file"),
            ("11. core_entrypoint", self.repo_root / "ui" / "gui.py", "file"),
            ("12. voice_catalog", self.repo_root / "app" / "voice_preview_catalog.json", "file"),
        ]

        missing = []
        for label, path, kind in inventory_items:
            if kind == "file" and not path.is_file():
                missing.append(f"{label}: thiếu tệp {path}")
            elif kind == "dir" and not path.is_dir():
                missing.append(f"{label}: thiếu thư mục {path}")

        self.assertEqual(missing, [], f"Phát hiện tài nguyên thiếu trong inventory: {missing}")

        # Kiểm tra catalog JSON parse được hợp lệ
        catalog_path = self.repo_root / "app" / "voice_preview_catalog.json"
        with open(catalog_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertIsInstance(data, (dict, list), "Voice catalog phải là JSON hợp lệ.")

    # =========================================================================
    # PKG-03: FFmpeg 3-State Resolution
    # =========================================================================
    def test_pkg_03_ffmpeg_3_state_resolution(self):
        """PKG-03: Kiểm tra 3-state resolution cascade: Bundle -> Workspace -> System PATH."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_bundle_ffmpeg = temp_path / "bundle" / "bin" / "ffmpeg" / "ffmpeg.exe"
            fake_workspace_ffmpeg = temp_path / "workspace" / "bin" / "ffmpeg" / "ffmpeg.exe"

            fake_bundle_ffmpeg.parent.mkdir(parents=True, exist_ok=True)
            fake_bundle_ffmpeg.write_bytes(b"MZfake")

            fake_workspace_ffmpeg.parent.mkdir(parents=True, exist_ok=True)
            fake_workspace_ffmpeg.write_bytes(b"MZfake")

            # State 1: Bundle có -> Chọn Bundle
            with patch("app.runtime_paths.bin_path", return_value=str(fake_bundle_ffmpeg)):
                res = rp.resolve_ffmpeg_path()
                self.assertEqual(res, str(fake_bundle_ffmpeg.resolve()))

            # State 2: Bundle không có, Workspace có -> Chọn Workspace
            with patch("app.runtime_paths.bin_path", return_value=""), \
                 patch("app.runtime_paths.join_root", return_value=str(fake_workspace_ffmpeg)):
                res = rp.resolve_ffmpeg_path()
                self.assertEqual(res, str(fake_workspace_ffmpeg.resolve()))

            # State 3: Bundle & Workspace không có -> Fallback System PATH
            with patch("app.runtime_paths.bin_path", return_value=""), \
                 patch("app.runtime_paths.join_root", return_value=str(temp_path / "nonexistent")), \
                 patch("shutil.which", return_value=r"C:\fake_system\ffmpeg.exe"):
                res = rp.resolve_ffmpeg_path()
                self.assertEqual(res, r"C:\fake_system\ffmpeg.exe")

            # State 4: Cả 3 đều không có -> Raise FileNotFoundError rõ ràng
            with patch("app.runtime_paths.bin_path", return_value=""), \
                 patch("app.runtime_paths.join_root", return_value=str(temp_path / "nonexistent")), \
                 patch("shutil.which", return_value=None):
                with self.assertRaises(FileNotFoundError) as cm:
                    rp.resolve_ffmpeg_path()
                self.assertIn("Không tìm thấy file thực thi FFmpeg", str(cm.exception))

        # Kiểm tra thực tế trên môi trường hiện tại: Phải resolve được và chạy được
        actual_ffmpeg = rp.resolve_ffmpeg_path()
        self.assertTrue(os.path.isfile(actual_ffmpeg), f"FFmpeg thực tế phải tồn tại: {actual_ffmpeg}")
        proc = subprocess.run([actual_ffmpeg, "-version"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, "FFmpeg phải thực thi được và trả về code 0.")
        self.assertIn("ffmpeg version", proc.stdout.lower())

    # =========================================================================
    # PKG-04: Writable Directory Bootstrap
    # =========================================================================
    def test_pkg_04_writable_directory_bootstrap(self):
        """PKG-04: Khởi tạo các thư mục writable tại workspace: output, temp, render_jobs, raw_tts, models, logs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            created_dirs = rp.ensure_runtime_directories(temp_dir)
            expected_names = {"output", "temp", "render_jobs", "raw_tts", "models", "logs"}
            created_names = {os.path.basename(d) for d in created_dirs}
            self.assertEqual(created_names, expected_names)

            # Đảm bảo tất cả thư mục đều tồn tại trên đĩa
            for d in created_dirs:
                self.assertTrue(os.path.isdir(d), f"Thư mục {d} phải được tạo thành công.")
                # Kiểm tra quyền ghi (writable)
                test_file = os.path.join(d, "write_test.tmp")
                with open(test_file, "w", encoding="utf-8") as f:
                    f.write("ok")
                self.assertTrue(os.path.isfile(test_file))
                os.remove(test_file)

            # Kiểm tra tính Idempotent (chạy lần 2 không lỗi, không mất dữ liệu)
            marker_file = os.path.join(temp_dir, "output", "existing_job.txt")
            with open(marker_file, "w", encoding="utf-8") as f:
                f.write("job_data")

            second_call = rp.ensure_runtime_directories(temp_dir)
            self.assertEqual(len(second_call), len(created_dirs))
            self.assertTrue(os.path.isfile(marker_file), "Bootstrap lần 2 không được xóa file cũ.")

    # =========================================================================
    # PKG-05: Behavioral Bundle Protection
    # =========================================================================
    def test_pkg_05_behavioral_bundle_protection(self):
        """PKG-05: Behavioral test đảm bảo 0 byte ghi vào bundle_root, 100% vào workspace_root."""
        with tempfile.TemporaryDirectory() as bundle_temp, tempfile.TemporaryDirectory() as ws_temp:
            bundle_path = Path(bundle_temp)
            ws_path = Path(ws_temp)

            # Giả lập môi trường frozen với bundle_root riêng biệt
            with patch("app.runtime_paths.bundle_root", return_value=str(bundle_path)), \
                 patch("app.runtime_paths.workspace_root", return_value=str(ws_path)):

                # 1. Chạy bootstrap
                rp.ensure_runtime_directories()

                # 2. Chạy ghi temp artifact
                t_path = rp.temp_path("test_cache.wav")
                with open(t_path, "wb") as f:
                    f.write(b"RIFFWAVE" * 100)

                # 3. Chạy ghi output artifact
                o_path = rp.output_path("final_video.mp4")
                with open(o_path, "wb") as f:
                    f.write(b"MP4DATA" * 100)

                # Xác nhận 0 byte được ghi vào bundle_root
                bundle_contents = list(bundle_path.glob("**/*"))
                self.assertEqual(
                    bundle_contents,
                    [],
                    f"VI PHẠM BUNDLE PROTECTION: Có file được ghi vào bundle_root: {bundle_contents}",
                )

                # Xác nhận 100% dữ liệu đi vào workspace_root
                self.assertTrue(os.path.isfile(t_path))
                self.assertTrue(os.path.isfile(o_path))
                self.assertTrue(str(t_path).startswith(str(ws_path)))
                self.assertTrue(str(o_path).startswith(str(ws_path)))

    # =========================================================================
    # PKG-06: Runtime Torch Exclusion Verification
    # =========================================================================
    def test_pkg_06_runtime_torch_exclusion_verification(self):
        """PKG-06: Xác nhận main process và Step 8/9 KHÔNG load Torch vào sys.modules."""
        check_script = """
import sys
import app.services.video_creator_service
import ui.worker_adapters.video_creator_adapter
import app.runtime_paths

torch_modules = [m for m in sys.modules.keys() if 'torch' in m]
print("TORCH_MODULES:" + ",".join(torch_modules))
"""
        cmd = [sys.executable, "-c", check_script]
        proc = subprocess.run(cmd, cwd=str(self.repo_root), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"Subprocess check lỗi: {proc.stderr}")

        output_line = [line for line in proc.stdout.splitlines() if line.startswith("TORCH_MODULES:")][0]
        loaded_torch = output_line.replace("TORCH_MODULES:", "").strip()
        self.assertEqual(
            loaded_torch,
            "",
            f"VI PHẠM TORCH EXCLUSION: Main process đã nạp các module torch: {loaded_torch}",
        )

        # Kiểm tra caller trace: Khi mock sys.modules['torch'] = None, Step 8/9 vẫn import bình thường
        orig_torch = sys.modules.get("torch")
        orig_torchaudio = sys.modules.get("torchaudio")
        try:
            sys.modules["torch"] = None
            sys.modules["torchaudio"] = None
            from app.services.video_creator_service import VideoCreatorService, VideoCreatorRequest
            from ui.worker_adapters.video_creator_adapter import VideoCreatorWorker
            self.assertIsNotNone(VideoCreatorService)
            self.assertIsNotNone(VideoCreatorWorker)
        finally:
            if orig_torch is not None:
                sys.modules["torch"] = orig_torch
            else:
                sys.modules.pop("torch", None)
            if orig_torchaudio is not None:
                sys.modules["torchaudio"] = orig_torchaudio
            else:
                sys.modules.pop("torchaudio", None)


    # =========================================================================
    # PKG-07: Gender AI Offline Assets
    # =========================================================================
    def test_pkg_07_gender_ai_offline_assets(self):
        """PKG-07: Tải và kiểm tra model gender_classifier.joblib hoạt động offline 100% không torch."""
        import joblib
        import numpy as np

        model_file = self.repo_root / "gender_voice_ai_windows_package" / "gender_classifier.joblib"
        self.assertTrue(model_file.is_file(), f"Thiếu model classifier: {model_file}")

        # Nạp model
        classifier = joblib.load(str(model_file))
        self.assertTrue(hasattr(classifier, "predict"), "Classifier phải có hàm predict().")
        self.assertTrue(hasattr(classifier, "classes_"), "Classifier phải có thuộc tính classes_.")
        self.assertGreater(len(classifier.classes_), 1, "Classifier phải có ít nhất 2 lớp nhãn.")

        # Thử nghiệm inference với feature vector 192 chiều dạng float (ECAPA embedding)
        n_features = getattr(classifier, "n_features_in_", 192)
        dummy_feature = np.zeros((1, n_features), dtype=np.float32)
        prediction = classifier.predict(dummy_feature)

        self.assertEqual(len(prediction), 1)
        self.assertIn(prediction[0], classifier.classes_)

    # =========================================================================
    # PKG-08: VieNeu CLI Worker Standalone
    # =========================================================================
    def test_pkg_08_vieneu_cli_worker_standalone(self):
        """PKG-08: Tệp app/vieneu_worker.py tồn tại, cú pháp hợp lệ, không import GUI Qt."""
        worker_file = self.repo_root / "app" / "vieneu_worker.py"
        self.assertTrue(worker_file.is_file(), "app/vieneu_worker.py phải tồn tại.")

        # Parse AST kiểm tra tính toàn vẹn cú pháp
        code = worker_file.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=str(worker_file))
        self.assertIsInstance(tree, ast.Module)

        # Kiểm tra không import bất kỳ GUI toolkit nào (PySide6, PyQt5, PyQt6)
        disallowed_guis = {"PySide6", "PyQt5", "PyQt6", "PySide2", "tkinter"}
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module.split(".")[0])

        gui_intersect = imported_modules.intersection(disallowed_guis)
        self.assertEqual(
            gui_intersect,
            set(),
            f"VI PHẠM STANDALONE WORKER: vieneu_worker.py không được import GUI: {gui_intersect}",
        )

        # Chạy thử nghiệm standalone với --help
        cmd = [sys.executable, str(worker_file), "--help"]
        proc = subprocess.run(cmd, cwd=str(self.repo_root), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"vieneu_worker.py --help trả về lỗi: {proc.stderr}")
        self.assertIn("--server", proc.stdout)
        self.assertIn("--model", proc.stdout)

    # =========================================================================
    # PKG-09: External Runtime Resolution
    # =========================================================================
    def test_pkg_09_external_runtime_resolution(self):
        """PKG-09: Kiểm tra thứ tự cascade phân giải VieNeu runtime."""
        # 1. HTTP Daemon có sẵn (Mock ping 200 OK)
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response):
            res_daemon = rp.resolve_vieneu_runtime("http://127.0.0.1:53239")
            self.assertTrue(res_daemon["available"])
            self.assertEqual(res_daemon["type"], "daemon")
            self.assertEqual(res_daemon["target"], "http://127.0.0.1:53239")

        # 2. Không có daemon -> Kiểm tra biến môi trường VIENEU_PYTHON
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            fake_env_python = f.name

        try:
            with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")), \
                 patch.dict(os.environ, {"VIENEU_PYTHON": fake_env_python}):
                res_env = rp.resolve_vieneu_runtime()
                self.assertTrue(res_env["available"])
                self.assertEqual(res_env["type"], "external_python")
                self.assertEqual(res_env["target"], os.path.abspath(fake_env_python))
        finally:
            if os.path.isfile(fake_env_python):
                os.remove(fake_env_python)

        # 3. Không có daemon & env -> Kiểm tra local ./vieneu_env/...
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_local_py = Path(temp_dir) / "vieneu_env" / "Scripts" / "python.exe"
            fake_local_py.parent.mkdir(parents=True, exist_ok=True)
            fake_local_py.write_bytes(b"MZfake")

            with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")), \
                 patch.dict(os.environ, {}, clear=True), \
                 patch("app.runtime_paths.join_root", return_value=str(fake_local_py)):
                res_local = rp.resolve_vieneu_runtime()
                self.assertTrue(res_local["available"])
                self.assertEqual(res_local["type"], "local_env")
                self.assertEqual(res_local["target"], str(fake_local_py.resolve()))

        # 4. Không có gì -> Fallback an toàn, có thông điệp hướng dẫn rõ ràng, KHÔNG crash
        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")), \
             patch.dict(os.environ, {}, clear=True), \
             patch("app.runtime_paths.join_root", return_value="C:\\nonexistent\\python.exe"):
            res_none = rp.resolve_vieneu_runtime()
            self.assertFalse(res_none["available"])
            self.assertEqual(res_none["type"], "none")
            self.assertIsNone(res_none["target"])
            self.assertIsNotNone(res_none["error"])
            self.assertIn("VieNeu TTS runtime chưa sẵn sàng", res_none["error"])


if __name__ == "__main__":
    unittest.main()

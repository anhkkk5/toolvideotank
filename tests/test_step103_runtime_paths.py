"""
tests/test_step103_runtime_paths.py

Bộ kiểm thử chấp nhận (Acceptance Test Suite) cho:
STEP 10.3 — Runtime Directory & Path Initialization (v1.1 LOCKED)

Tiêu chuẩn nghiệm thu 8 tiêu chí:
- DIR-01: Bundle / Workspace separation (Frozen: _internal vs exe_dir)
- DIR-02: 6 Writable directories bootstrap (output, temp, render_jobs, raw_tts, models, logs)
- DIR-03: Idempotence & safety (bảo toàn file khi gọi bootstrap nhiều lần)
- DIR-04: Behavioral bundle protection + writable models path (0 byte vào bundle, 100% vào workspace)
- DIR-05: Model resolution 3 cases (Case A: bundle-only, Case B: workspace override, Case C: writable target)
- DIR-06: DEV/FROZEN + CWD independence (thay đổi os.chdir không ảnh hưởng tới bất kỳ path nào)
- DIR-07: Zero hardcoded developer paths trong runtime_paths.py và ui/gui.py
- DIR-08: Startup bootstrap & failure handling (fail-fast SystemExit(1) khi workspace lỗi)
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

ui_dir = repo_root / "ui"
if str(ui_dir) not in sys.path:
    sys.path.insert(0, str(ui_dir))

import app.runtime_paths as rp


class TestStep103RuntimePaths(unittest.TestCase):
    """Bộ kiểm thử chấp nhận DIR-01 -> DIR-08 của Contract 10.3 v1.1."""

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]

    # =========================================================================
    # DIR-01: Bundle / Workspace Separation
    # =========================================================================
    def test_dir_01_bundle_workspace_separation(self):
        """DIR-01: Ở chế độ Frozen, bundle_root trỏ _internal, workspace_root trỏ exe_dir."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_exe = temp_path / "CapCap.exe"
            fake_exe.write_bytes(b"MZfake")
            fake_internal = temp_path / "_internal"
            fake_internal.mkdir(parents=True, exist_ok=True)

            # 1. Giả lập Frozen one-dir: exe_dir và _internal tách biệt
            with patch("sys.frozen", True, create=True), \
                 patch("sys.executable", str(fake_exe)):

                b_root = Path(rp.bundle_root()).resolve()
                w_root = Path(rp.workspace_root()).resolve()

                # Xác nhận bundle_root trỏ vào _internal
                self.assertEqual(b_root, fake_internal.resolve())
                # Xác nhận workspace_root trỏ vào thư mục chứa exe
                self.assertEqual(w_root, temp_path.resolve())
                # Xác nhận ranh giới tách biệt tuyệt đối
                self.assertNotEqual(b_root, w_root)
                self.assertTrue(str(b_root).startswith(str(w_root)))
                self.assertEqual(b_root.name, "_internal")

            # 2. Giả lập Frozen với sys._MEIPASS (one-file temp unpack)
            fake_meipass = temp_path / "_MEIPASS_12345"
            fake_meipass.mkdir(parents=True, exist_ok=True)
            with patch("sys.frozen", True, create=True), \
                 patch.object(sys, "_MEIPASS", str(fake_meipass), create=True), \
                 patch("sys.executable", str(fake_exe)):

                b_root_meipass = Path(rp.bundle_root()).resolve()
                w_root_meipass = Path(rp.workspace_root()).resolve()

                self.assertEqual(b_root_meipass, fake_meipass.resolve())
                self.assertEqual(w_root_meipass, temp_path.resolve())
                self.assertNotEqual(b_root_meipass, w_root_meipass)

    # =========================================================================
    # DIR-02: 6 Writable Dirs Bootstrap
    # =========================================================================
    def test_dir_02_six_writable_directories_bootstrap(self):
        """DIR-02: ensure_runtime_directories tạo đủ 6 thư mục: output, temp, render_jobs, raw_tts, models, logs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            ensured_dirs = rp.ensure_runtime_directories(temp_dir)
            expected_names = {"output", "temp", "render_jobs", "raw_tts", "models", "logs"}
            actual_names = {Path(d).name for d in ensured_dirs}

            self.assertEqual(actual_names, expected_names, "Phải tạo đầy đủ 6 thư mục định danh.")
            self.assertEqual(len(ensured_dirs), 6)

            # Kiểm tra từng thư mục tồn tại và có quyền ghi thực tế
            for d in ensured_dirs:
                self.assertTrue(os.path.isdir(d), f"Thư mục {d} phải là thư mục hợp lệ.")
                test_file = os.path.join(d, "write_test.tmp")
                with open(test_file, "wb") as f:
                    f.write(b"write_ok")
                self.assertTrue(os.path.isfile(test_file))
                os.remove(test_file)

    # =========================================================================
    # DIR-03: Idempotence & Safety / Artifact Preservation
    # =========================================================================
    def test_dir_03_idempotence_and_preservation(self):
        """DIR-03: Bootstrap nhiều lần không lỗi và bảo toàn 100% dữ liệu đã có trong workspace."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Lần 1: Khởi tạo
            rp.ensure_runtime_directories(temp_dir)

            # Tạo các artifact người dùng mô phỏng công việc đang xử lý
            marker_output = Path(temp_dir) / "output" / "rendered_final.mp4"
            marker_temp = Path(temp_dir) / "temp" / "cached_segment_01.wav"
            marker_job = Path(temp_dir) / "render_jobs" / "job_2026.json"
            marker_tts = Path(temp_dir) / "raw_tts" / "audio_voice_0.wav"
            marker_log = Path(temp_dir) / "logs" / "session_2026.log"
            marker_model = Path(temp_dir) / "models" / "custom_piper.onnx"

            marker_output.write_bytes(b"VIDEO_DATA")
            marker_temp.write_bytes(b"TEMP_WAV")
            marker_job.write_text('{"job_id": 1}', encoding="utf-8")
            marker_tts.write_bytes(b"TTS_RAW")
            marker_log.write_text("INIT LOG", encoding="utf-8")
            marker_model.write_bytes(b"MODEL_ONNX")

            # Lần 2 & 3: Gọi lại bootstrap
            rp.ensure_runtime_directories(temp_dir)
            rp.ensure_runtime_directories(temp_dir)

            # Khẳng định 100% dữ liệu nguyên vẹn
            self.assertEqual(marker_output.read_bytes(), b"VIDEO_DATA")
            self.assertEqual(marker_temp.read_bytes(), b"TEMP_WAV")
            self.assertEqual(marker_job.read_text(encoding="utf-8"), '{"job_id": 1}')
            self.assertEqual(marker_tts.read_bytes(), b"TTS_RAW")
            self.assertEqual(marker_log.read_text(encoding="utf-8"), "INIT LOG")
            self.assertEqual(marker_model.read_bytes(), b"MODEL_ONNX")

    # =========================================================================
    # DIR-04: Behavioral Bundle Protection + Writable Models Path
    # =========================================================================
    def test_dir_04_bundle_protection_and_writable_models(self):
        """DIR-04: 0 byte ghi vào bundle_root, 100% ghi vào workspace_root trên cả 6 hàm ghi."""
        with tempfile.TemporaryDirectory() as bundle_dir, tempfile.TemporaryDirectory() as ws_dir:
            bundle_path = Path(bundle_dir)
            ws_path = Path(ws_dir)

            # Đặt fake bundle_root và fake workspace_root
            with patch("app.runtime_paths.bundle_root", return_value=str(bundle_path)), \
                 patch("app.runtime_paths.workspace_root", return_value=str(ws_path)):

                # Khởi tạo workspace
                rp.ensure_runtime_directories()

                # Ghi dữ liệu vào cả 6 hàm ghi
                f_out = rp.output_path("video.mp4")
                f_temp = rp.temp_path("chunk.wav")
                f_logs = rp.logs_path("run.log")
                f_jobs = rp.render_jobs_path("job.json")
                f_tts = rp.raw_tts_path("tts.wav")
                f_model = rp.writable_models_path("whisper_download.bin")

                Path(f_out).write_bytes(b"OUTPUT_BYTES")
                Path(f_temp).write_bytes(b"TEMP_BYTES")
                Path(f_logs).write_text("LOG_BYTES", encoding="utf-8")
                Path(f_jobs).write_text('{"id": 1}', encoding="utf-8")
                Path(f_tts).write_bytes(b"TTS_BYTES")
                Path(f_model).write_bytes(b"MODEL_DOWNLOAD_BYTES")

                # Kiểm tra nghiêm ngặt: bundle_root phải rỗng 0 file, 0 byte!
                bundle_files = list(bundle_path.glob("**/*"))
                self.assertEqual(
                    bundle_files,
                    [],
                    f"VI PHẠM BUNDLE PROTECTION: Có file xuất hiện trong bundle_root: {bundle_files}"
                )

                # Kiểm tra 100% artifact nằm đúng trong workspace_root
                for fp in [f_out, f_temp, f_logs, f_jobs, f_tts, f_model]:
                    self.assertTrue(os.path.isfile(fp))
                    self.assertTrue(str(Path(fp).resolve()).startswith(str(ws_path.resolve())))

    # =========================================================================
    # DIR-05: Model Resolution 3 Cases
    # =========================================================================
    def test_dir_05_model_resolution_three_cases(self):
        """DIR-05: Kiểm tra 3 trường hợp resolution của models_path và writable_models_path."""
        with tempfile.TemporaryDirectory() as bundle_dir, tempfile.TemporaryDirectory() as ws_dir:
            bundle_models = Path(bundle_dir) / "models"
            ws_models = Path(ws_dir) / "models"
            bundle_models.mkdir(parents=True, exist_ok=True)
            ws_models.mkdir(parents=True, exist_ok=True)

            with patch("app.runtime_paths.bundle_root", return_value=str(bundle_dir)), \
                 patch("app.runtime_paths.workspace_root", return_value=str(ws_dir)):

                # Case A: Model chỉ có trong bundle -> models_path trả về bundle
                bundle_voice = bundle_models / "ngochuyen.onnx"
                bundle_voice.write_bytes(b"BUNDLE_VOICE")
                resolved_a = rp.models_path("ngochuyen.onnx")
                self.assertEqual(resolved_a, str(bundle_voice.resolve()))
                # Khẳng định models_path() không tự ý tạo thư mục hay file bên workspace
                self.assertFalse((ws_models / "ngochuyen.onnx").exists())

                # Case B: Model có ở cả bundle và workspace -> models_path ưu tiên workspace override
                ws_voice = ws_models / "ngochuyen.onnx"
                ws_voice.write_bytes(b"USER_CUSTOM_VOICE")
                resolved_b = rp.models_path("ngochuyen.onnx")
                self.assertEqual(resolved_b, str(ws_voice.resolve()))

                # Case C: writable_models_path("ngochuyen.onnx") luôn luôn trả về workspace path
                resolved_c = rp.writable_models_path("ngochuyen.onnx")
                self.assertEqual(resolved_c, str(ws_voice.resolve()))
                self.assertFalse(resolved_c.startswith(str(bundle_dir)))

                # Khẳng định model chưa tồn tại: models_path không tự tạo file hay thư mục
                nonexistent = rp.models_path("nonexistent_model.bin")
                self.assertFalse(os.path.exists(nonexistent))

    # =========================================================================
    # DIR-06: DEV/FROZEN + CWD Independence
    # =========================================================================
    def test_dir_06_cwd_independence(self):
        """DIR-06: Thay đổi os.chdir sang thư mục khác không làm thay đổi bundle_root, workspace_root hay *_path."""
        orig_cwd = os.getcwd()
        random_cwd = tempfile.mkdtemp()
        try:
            # 1. Thu thập đường dẫn ban đầu ở CWD hiện tại
            b_root_orig = rp.bundle_root()
            w_root_orig = rp.workspace_root()
            out_orig = rp.output_path("test.mp4")
            temp_orig = rp.temp_path("test.wav")
            log_orig = rp.logs_path("test.log")
            job_orig = rp.render_jobs_path("test.json")
            tts_orig = rp.raw_tts_path("test.wav")
            model_orig = rp.writable_models_path("test.onnx")

            # 2. Đổi CWD sang thư mục tạm
            os.chdir(random_cwd)
            self.assertEqual(os.path.realpath(os.getcwd()), os.path.realpath(random_cwd))

            # Kiểm tra lại các hàm path
            self.assertEqual(rp.bundle_root(), b_root_orig)
            self.assertEqual(rp.workspace_root(), w_root_orig)
            self.assertEqual(rp.output_path("test.mp4"), out_orig)
            self.assertEqual(rp.temp_path("test.wav"), temp_orig)
            self.assertEqual(rp.logs_path("test.log"), log_orig)
            self.assertEqual(rp.render_jobs_path("test.json"), job_orig)
            self.assertEqual(rp.raw_tts_path("test.wav"), tts_orig)
            self.assertEqual(rp.writable_models_path("test.onnx"), model_orig)

            # Khẳng định tất cả đường dẫn đều là đường dẫn tuyệt đối
            for p in [b_root_orig, w_root_orig, out_orig, temp_orig, log_orig, job_orig, tts_orig, model_orig]:
                self.assertTrue(os.path.isabs(p), f"Đường dẫn phải là tuyệt đối: {p}")
        finally:
            os.chdir(orig_cwd)
            shutil.rmtree(random_cwd, ignore_errors=True)

    # =========================================================================
    # DIR-07: Zero Hardcoded Developer Paths
    # =========================================================================
    def test_dir_07_zero_hardcoded_developer_paths(self):
        """DIR-07: Khẳng định 0 hardcoded developer paths trong app/runtime_paths.py và ui/gui.py."""
        target_files = [
            self.repo_root / "app" / "runtime_paths.py",
            self.repo_root / "ui" / "gui.py",
        ]
        disallowed_patterns = [
            "D:\\CodingTime",
            "D:/CodingTime",
            "CodingTime",
            "D:\\VieNeu-TTS",
            "D:/VieNeu-TTS",
        ]

        violations = []
        for tf in target_files:
            content = tf.read_text(encoding="utf-8")
            for pattern in disallowed_patterns:
                if pattern in content:
                    violations.append(f"{tf.name} chứa mẫu cấm '{pattern}'")

        self.assertEqual(violations, [], f"Phát hiện hardcoded path máy cá nhân: {violations}")

    # =========================================================================
    # DIR-08: Startup Bootstrap & Failure Handling
    # =========================================================================
    def test_dir_08_startup_bootstrap_and_failure_handling(self):
        """DIR-08: ui/gui.py gọi bootstrap an toàn; fail-fast SystemExit(1) khi workspace không có quyền ghi."""
        import ui.gui as gui

        # 1. Success Path: Gọi _bootstrap_workspace thành công, 6 thư mục sẵn sàng
        gui._bootstrap_workspace()
        expected_dirs = ["output", "temp", "render_jobs", "raw_tts", "models", "logs"]
        for d in expected_dirs:
            self.assertTrue(os.path.isdir(rp.join_root(d)))

        # 2. Failure Path: Mô phỏng lỗi quyền ghi (PermissionError / read-only workspace)
        with patch("app.runtime_paths.ensure_runtime_directories", side_effect=PermissionError("Simulated Read-only Workspace")):
            stderr_capture = io.StringIO()
            with patch("sys.stderr", stderr_capture):
                with self.assertRaises(SystemExit) as cm:
                    gui._bootstrap_workspace()

                self.assertEqual(cm.exception.code, 1, "Khi bootstrap thất bại phải thoát với code 1.")
                error_output = stderr_capture.getvalue()
                self.assertIn("[Startup Error]", error_output)
                self.assertIn("Simulated Read-only Workspace", error_output)


if __name__ == "__main__":
    unittest.main()

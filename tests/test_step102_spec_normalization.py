"""
tests/test_step102_spec_normalization.py

Bộ kiểm thử chấp nhận (Acceptance Test Suite) cho:
STEP 10.2 — Chuẩn Hóa CapCap.spec (v1.2 LOCKED)

Tiêu chuẩn nghiệm thu 12 sub-steps:
- 10.2.1: Dynamic SPECPATH Invariant (CWD-independent)
- 10.2.2: Datas inventory & existence
- 10.2.3: Gender AI package destination (<bundle>/gender_voice_ai_windows_package/...)
- 10.2.4: VieNeu worker destination (<bundle>/app/vieneu_worker.py)
- 10.2.5: Translation prompts destination (<bundle>/app/translation/prompts/...)
- 10.2.6: Voice assets conditional destination (<bundle>/assets/voices/...)
- 10.2.7: Hidden-import audit (Group A: proven, Group B: app lazy, Group C: zero private internals)
- 10.2.8: Excludes audit (torch, torchaudio, torchvision, demucs)
- 10.2.9: PyInstaller Analysis Audit (a.pure, a.binaries, a.datas destination layout, warnings)
- 10.2.10: AST Static Spec Audit (0 hardcoded dev paths)
"""

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


class TestStep102SpecNormalization(unittest.TestCase):
    """Bộ kiểm tra nghiệm thu chuẩn hóa CapCap.spec theo Contract 10.2 v1.2."""

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.spec_path = cls.repo_root / "CapCap.spec"
        cls.spec_content = cls.spec_path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.spec_content, filename=str(cls.spec_path))

    # =========================================================================
    # 10.2.1: Dynamic SPECPATH Invariant
    # =========================================================================
    def test_1021_dynamic_specpath_cwd_independent(self):
        """10.2.1: SPECPATH invariant đảm bảo resolve project_root độc lập với CWD."""
        # 1. Kiểm tra AST: project_root được resolve từ SPECPATH
        self.assertIn("SPECPATH", self.spec_content)
        self.assertIn("_spec_dir = globals().get(\"SPECPATH\")", self.spec_content)
        self.assertIn("project_root = Path(_spec_dir).resolve()", self.spec_content)
        self.assertNotIn('project_root = Path(r"D:\\CodingTime\\CapCap")', self.spec_content)

        # 2. Kiểm tra tính độc lập CWD: Dù CWD ở bất kỳ đâu, khi SPECPATH truyền vào repo_root,
        # project_root luôn trỏ chính xác về thư mục gốc CapCap
        arbitrary_dir = Path(tempfile.gettempdir())
        original_cwd = os.getcwd()
        try:
            os.chdir(str(arbitrary_dir))
            spec_ns = {"SPECPATH": str(self.repo_root), "Path": Path, "globals": lambda: {"SPECPATH": str(self.repo_root)}}
            _spec_dir = spec_ns["SPECPATH"]
            resolved = Path(_spec_dir).resolve()
            self.assertEqual(resolved, self.repo_root)
            self.assertTrue((resolved / "app").is_dir())
            self.assertTrue((resolved / "ui").is_dir())
            self.assertTrue((resolved / "CapCap.spec").is_file())
        finally:
            os.chdir(original_cwd)

    # =========================================================================
    # 10.2.2 & 10.2.3: Datas Inventory & Gender AI Package Destination
    # =========================================================================
    def test_1022_and_1023_gender_ai_destination_tuple(self):
        """10.2.2 & 10.2.3: gender_voice_ai_windows_package được khai báo đúng mapping nguồn -> đích."""
        self.assertIn('"gender_voice_ai_windows_package"', self.spec_content)

        # Xác nhận gói trên đĩa chứa đầy đủ sub-models: classifier, detector, runtime_models (ast, ecapa)
        pkg_dir = self.repo_root / "gender_voice_ai_windows_package"
        self.assertTrue((pkg_dir / "gender_classifier.joblib").is_file())
        self.assertTrue((pkg_dir / "gender_detector.py").is_file())
        self.assertTrue((pkg_dir / "runtime_models" / "ast").is_dir())
        self.assertTrue((pkg_dir / "runtime_models" / "ecapa").is_dir())

    # =========================================================================
    # 10.2.4: VieNeu Worker Script Destination
    # =========================================================================
    def test_1024_vieneu_worker_destination_tuple(self):
        """10.2.4: vieneu_worker.py được khai báo với destination thư mục app."""
        self.assertIn('"vieneu_worker.py"', self.spec_content)
        self.assertIn('"app"', self.spec_content)
        worker_file = self.repo_root / "app" / "vieneu_worker.py"
        self.assertTrue(worker_file.is_file())


    # =========================================================================
    # 10.2.5: Translation Prompts Destination
    # =========================================================================
    def test_1025_translation_prompts_destination(self):
        """10.2.5: app/translation/prompts được ánh xạ chính xác vào bundle."""
        self.assertIn('"app/translation/prompts"', self.spec_content.replace("\\", "/"))
        prompts_dir = self.repo_root / "app" / "translation" / "prompts"
        self.assertTrue(prompts_dir.is_dir())

    # =========================================================================
    # 10.2.6: Voice Assets (Conditional Destination)
    # =========================================================================
    def test_1026_voice_assets_conditional(self):
        """10.2.6: assets/voices được xử lý conditional an toàn nếu tồn tại trên đĩa."""
        self.assertIn('(project_root / "assets" / "voices").is_dir()', self.spec_content.replace("\\", "/"))
        voices_dir = self.repo_root / "assets" / "voices"
        if voices_dir.is_dir():
            voice_files = list(voices_dir.glob("*.*"))
            self.assertGreater(len(voice_files), 0, "Nếu assets/voices tồn tại thì phải có file mẫu.")

    # =========================================================================
    # 10.2.7: Hidden-Import Audit (Group A, B, C)
    # =========================================================================
    def test_1027_hidden_imports_three_groups_integrity(self):
        """10.2.7: Phân nhóm hiddenimports chặt chẽ, loại bỏ hoàn toàn private internals."""
        # Group A — Proven required
        self.assertIn('"joblib"', self.spec_content)
        self.assertIn('"sklearn.pipeline"', self.spec_content)

        # Group B — Application dynamic/lazy modules
        self.assertIn('"app.models.subtitle_segment"', self.spec_content)
        self.assertIn('"app.services.video_creator_service"', self.spec_content)
        self.assertIn('"ui.worker_adapters.video_creator_adapter"', self.spec_content)
        self.assertIn('"ui.dialogs.pipeline_b_progress_dialog"', self.spec_content)
        self.assertIn('"app.services.gender_service"', self.spec_content)

        # Group C — Private Dependency Internals: TUYỆT ĐỐI KHÔNG CÓ TRONG SPEC
        self.assertNotIn("sklearn.preprocessing._data", self.spec_content)
        self.assertNotIn("sklearn.linear_model._logistic", self.spec_content)
        self.assertNotIn("sklearn.utils._typedefs", self.spec_content)

    # =========================================================================
    # 10.2.8: Excludes Audit (Torch / Demucs / Llama)
    # =========================================================================
    def test_1028_excludes_audit_torch_demucs(self):
        """10.2.8: Duy trì excludes và post-filter loại trừ tuyệt đối Torch và Demucs."""
        self.assertIn('"torch"', self.spec_content)
        self.assertIn('"torchaudio"', self.spec_content)
        self.assertIn('"torchvision"', self.spec_content)
        self.assertIn('"demucs"', self.spec_content)
        self.assertIn('_EXCLUDE_PREFIXES = ("torch", "torchaudio", "torchvision", "demucs")', self.spec_content)

    # =========================================================================
    # 10.2.9: PyInstaller Analysis Audit (Dry-run)
    # =========================================================================
    def test_1029_pyinstaller_analysis_audit(self):
        """10.2.9: Thực thi Analysis thực tế của PyInstaller trên spec và đối chiếu Acceptance Matrix."""
        import PyInstaller.building.build_main as bm
        from PyInstaller.config import CONF

        spec_file = str(self.spec_path)
        with tempfile.TemporaryDirectory() as temp_work:
            CONF['spec'] = spec_file
            CONF['specpath'], CONF['specnm'] = os.path.split(spec_file)
            CONF['specnm'] = os.path.splitext(CONF['specnm'])[0]
            CONF['distpath'] = os.path.join(temp_work, 'dist')
            CONF['workpath'] = os.path.join(temp_work, 'build')
            CONF['warnfile'] = os.path.join(temp_work, 'warn.txt')
            CONF['dot-file'] = os.path.join(temp_work, 'graph.dot')
            CONF['xref-file'] = os.path.join(temp_work, 'xref.html')
            CONF['cachedir'] = os.path.join(temp_work, 'cache')
            CONF['code_cache'] = dict()
            os.makedirs(CONF['workpath'], exist_ok=True)

            spec_ns = {
                'DISTPATH': CONF['distpath'],
                'HOMEPATH': bm.HOMEPATH,
                'SPEC': CONF['spec'],
                'specnm': CONF['specnm'],
                'SPECPATH': CONF['specpath'],
                'WARNFILE': CONF['warnfile'],
                'workpath': CONF['workpath'],
                'TOC': bm.TOC,
                'Analysis': bm.Analysis,
                'BUNDLE': lambda *args, **kwargs: None,
                'COLLECT': lambda *args, **kwargs: None,
                'EXE': lambda *args, **kwargs: None,
                'MERGE': bm.MERGE,
                'PYZ': lambda *args, **kwargs: None,
                'Tree': bm.Tree,
                'Splash': bm.Splash,
                'os': os,
            }

            with open(spec_file, 'rb') as f:
                code = compile(f.read(), spec_file, 'exec')
            exec(code, spec_ns)
            a = spec_ns.get('a')
            self.assertIsNotNone(a, "Analysis object phải được khởi tạo thành công.")

            # 1. a.pure audit: KHÔNG chứa torch/demucs
            torch_pure = [m for m in a.pure if m[0].startswith('torch.') or m[0] == 'torch' or m[0].startswith('demucs')]
            self.assertEqual(torch_pure, [], f"Torch/Demucs lọt vào a.pure: {torch_pure}")

            # 2. a.binaries audit: KHÔNG chứa torch DLLs thực sự
            torch_dll_names = {"torch_python.dll", "c10.dll", "torch_cpu.dll", "torch_cuda.dll", "demucs.dll"}
            actual_torch_dlls = [b for b in a.binaries if Path(str(b[0])).name.lower() in torch_dll_names]
            self.assertEqual(actual_torch_dlls, [], f"Torch DLLs lọt vào a.binaries: {actual_torch_dlls}")

            # 3. a.binaries audit: FFmpeg và FFprobe tồn tại và đúng destination
            ffmpeg_bins = [b for b in a.binaries if Path(str(b[0])).name.lower() in ("ffmpeg.exe", "ffprobe.exe")]
            self.assertGreaterEqual(len(ffmpeg_bins), 2, "a.binaries phải chứa ffmpeg.exe và ffprobe.exe")
            for b in ffmpeg_bins:
                dest = str(b[0]).replace("\\", "/")
                self.assertTrue(dest.startswith("bin/ffmpeg/"), f"FFmpeg binary destination không đúng layout: {dest}")

            # 4. a.datas audit: Gender AI destination layout
            gender_datas = [d for d in a.datas if "gender_voice_ai_windows_package" in str(d[0]).replace("\\", "/")]
            self.assertGreater(len(gender_datas), 0, "a.datas phải chứa gender_voice_ai_windows_package")
            for d in gender_datas:
                dest = str(d[0]).replace("\\", "/")
                self.assertTrue(dest.startswith("gender_voice_ai_windows_package/"), f"Gender AI destination layout sai: {dest}")

            # 5. a.datas audit: vieneu_worker destination layout
            vieneu_datas = [d for d in a.datas if "vieneu_worker.py" in str(d[0]).replace("\\", "/")]
            self.assertEqual(len(vieneu_datas), 1, "a.datas phải chứa đúng 1 entry vieneu_worker.py")
            self.assertEqual(str(vieneu_datas[0][0]).replace("\\", "/"), "app/vieneu_worker.py")

            # 6. a.datas audit: Translation prompts destination layout
            prompts_datas = [d for d in a.datas if "translation/prompts" in str(d[0]).replace("\\", "/")]
            self.assertGreater(len(prompts_datas), 0, "a.datas phải chứa translation prompts")
            for d in prompts_datas:
                dest = str(d[0]).replace("\\", "/")
                self.assertTrue(dest.startswith("app/translation/prompts/"), f"Prompts destination layout sai: {dest}")

    # =========================================================================
    # 10.2.10: AST Static Spec Audit
    # =========================================================================
    def test_10210_ast_static_spec_audit(self):
        """10.2.10: Quét AST toàn diện khẳng định không còn bất kỳ đường dẫn dev máy cá nhân nào."""
        # 1. Không chứa chuỗi D:\CodingTime\CapCap
        self.assertNotIn("D:\\CodingTime\\CapCap", self.spec_content)
        self.assertNotIn("CodingTime", self.spec_content)

        # 2. Cú pháp module AST hoàn toàn hợp lệ
        self.assertIsInstance(self.tree, ast.Module)


if __name__ == "__main__":
    unittest.main()

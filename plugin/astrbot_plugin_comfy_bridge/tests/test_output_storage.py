import io
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from output_storage_runtime import configure_output, strip_png_metadata, watermark_image
from PIL import Image, PngImagePlugin


class OutputStorageTests(unittest.TestCase):
    def test_palette_has_dedicated_prefix(self):
        workflow = {"1": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}}}
        configure_output(workflow, {"grouping": "style"}, style="one", palette=True)
        self.assertTrue(workflow["1"]["inputs"]["filename_prefix"].startswith("AAA-RandomStyle/"))

    def test_stripping_keeps_pixels(self):
        image = Image.new("RGB", (20, 20), (31, 112, 78))
        meta = PngImagePlugin.PngInfo()
        meta.add_text("workflow", "secret")
        stream = io.BytesIO()
        image.save(stream, format="PNG", pnginfo=meta)
        stripped = Image.open(io.BytesIO(strip_png_metadata(stream.getvalue())))
        self.assertNotIn("workflow", stripped.info)
        self.assertEqual(stripped.tobytes(), image.tobytes())

    def test_watermark_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.png"
            Image.new("RGB", (100, 100), "white").save(source)
            original = source.read_bytes()
            Image.new("RGBA", (10, 10), (255, 0, 0, 128)).save(root / "signature.png")
            result = watermark_image(source, root, root / "output", {})
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(result.parent.name, "Author Pictures")
            self.assertNotEqual(result.read_bytes(), original)

    def test_rejects_broken_png(self):
        with self.assertRaises(ValueError):
            strip_png_metadata(b"broken")

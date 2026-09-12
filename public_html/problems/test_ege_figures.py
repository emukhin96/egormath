from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from .ege_figures import _image_info, package_ege_images


class EgeFiguresTests(SimpleTestCase):
    def test_reads_ocr_coordinates_from_stem(self):
        info = _image_info('uuid-013_382_597_2013_1222')
        self.assertEqual(info['page'], 13)
        self.assertEqual((info['height'], info['width']), (382, 597))

    def test_removes_confirmed_answer_grid(self):
        import fitz
        from PIL import Image, ImageDraw

        stem = 'uuid-001_300_300_100_100'
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, dest, pdf = root / 'source', root / 'dest', root / 'book.pdf'
            source.mkdir()
            image = Image.new('RGB', (300, 300), 'white')
            draw = ImageDraw.Draw(image)
            draw.line((0, 245, 299, 245), fill='black', width=2)
            draw.line((0, 295, 299, 295), fill='black', width=2)
            image.save(source / (stem + '.jpg'))
            document = fitz.open()
            page = document.new_page(width=595.28, height=841.89)
            document.save(pdf)
            document.close()
            bundle = SimpleNamespace(tasks=[SimpleNamespace(
                external_id='1.1', images=[stem], subitems=[])])
            with patch('problems.ege_figures._answer_y', return_value=100):
                result = package_ege_images(
                    bundle, source, pdf, dest,
                    {'tasks': {'1.1': {'page': 1, 'clip': [0, 0, 595, 842]}}})
            self.assertIn(stem, result['removed_grid'])
            with Image.open(dest / (stem + '.jpg')) as packed:
                self.assertLess(packed.height, 300)
            with patch('problems.ege_figures._answer_y', return_value=100):
                repeated = package_ege_images(
                    bundle, source, pdf, dest,
                    {'tasks': {'1.1': {'page': 1, 'clip': [0, 0, 595, 842]}}})
            self.assertIn(stem, repeated['removed_grid'])

    def test_copies_when_pdf_does_not_confirm_answer(self):
        import fitz
        from PIL import Image

        stem = 'uuid-001_100_100_100_100'
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, dest, pdf = root / 'source', root / 'dest', root / 'book.pdf'
            source.mkdir()
            Image.new('RGB', (100, 100), 'white').save(source / (stem + '.jpg'))
            document = fitz.open()
            document.new_page(width=595.28, height=841.89)
            document.save(pdf)
            document.close()
            bundle = SimpleNamespace(tasks=[SimpleNamespace(
                external_id='1.1', images=[stem], subitems=[])])
            result = package_ege_images(
                bundle, source, pdf, dest,
                {'tasks': {'1.1': {'page': 1, 'clip': [0, 0, 595, 842]}}})
            self.assertIn(stem, result['copied'])
            self.assertTrue((dest / (stem + '.jpg')).is_file())

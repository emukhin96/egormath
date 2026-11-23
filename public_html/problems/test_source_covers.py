"""Обложки задачников: отрисовка страницы PDF / картинки
(problems/source_covers.py) и команда ``manage.py source_covers``."""
import io
import json
import shutil
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from problems.models import Source
from problems.source_covers import COVER_SIZE, CoverError, render_cover
from problems.tests import make_teacher
from worksheets.collection_shelves import cover_url


def make_pdf(path, pages=2, text=True):
    import pymupdf

    doc = pymupdf.open()
    for number in range(1, pages + 1):
        page = doc.new_page(width=420, height=595)
        if text:
            page.insert_text((60, 100), f'Page {number}', fontsize=40)
    doc.save(path)
    doc.close()


class RenderCoverTests(TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_pdf_page_to_jpeg_of_cover_size(self):
        pdf = self.dir / 'book.pdf'
        make_pdf(pdf)
        image = Image.open(io.BytesIO(render_cover(pdf, page=2)))
        self.assertEqual(image.format, 'JPEG')
        self.assertEqual(image.size, COVER_SIZE)

    def test_missing_page_and_broken_file(self):
        pdf = self.dir / 'book.pdf'
        make_pdf(pdf, pages=1)
        with self.assertRaisesMessage(CoverError, 'страницы 3 нет'):
            render_cover(pdf, page=3)
        blank = self.dir / 'blank.pdf'
        make_pdf(blank, pages=1, text=False)
        with self.assertRaisesMessage(CoverError, 'пустая'):
            render_cover(blank)
        broken = self.dir / 'broken.pdf'
        broken.write_bytes(b'not a pdf')
        with self.assertRaises(CoverError):
            render_cover(broken)

    def test_image_is_cropped_to_cover_proportion(self):
        png = self.dir / 'wide.png'
        image = Image.new('RGB', (900, 300), 'red')
        image.paste('blue', (0, 0, 450, 300))
        image.save(png)
        image = Image.open(io.BytesIO(render_cover(png)))
        self.assertEqual(image.size, COVER_SIZE)


class SourceCoversCommandTests(TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        media = self.dir / 'media'
        override = override_settings(MEDIA_ROOT=str(media))
        override.enable()
        self.addCleanup(override.disable)
        make_pdf(self.dir / 'book.pdf')
        self.ziv = Source.objects.create(title='Зив-8')
        self.geo7 = Source.objects.create(title='Геометрия. 7 класс', author='А. В. Волчкевич')
        Source.objects.create(title='Алгебра. 7 класс', author='Мерзляк А. Г.')

    def run_command(self, rows, *args):
        mapping = self.dir / 'covers.json'
        mapping.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        out, err = io.StringIO(), io.StringIO()
        call_command('source_covers', str(mapping), *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_writes_cover_by_title_and_author(self):
        out, err = self.run_command([
            {'match': 'зив-8', 'file': 'book.pdf'},
            {'match': '7 класс', 'author': 'Волчкевич', 'file': 'book.pdf', 'page': 2},
        ])
        self.assertEqual(err, '')
        self.assertIn('записано: 2', out)
        self.ziv.refresh_from_db()
        self.geo7.refresh_from_db()
        self.assertRegex(self.ziv.cover.name,
                         rf'^source_covers/source-{self.ziv.pk}-[0-9a-f]{{8}}\.jpg$')
        self.assertTrue(Path(self.geo7.cover.path).is_file())

    def test_existing_cover_kept_without_force(self):
        self.run_command([{'match': 'Зив-8', 'file': 'book.pdf'}])
        out, _ = self.run_command([{'match': 'Зив-8', 'file': 'book.pdf'}])
        self.assertIn('обложка уже есть', out)
        out, _ = self.run_command([{'match': 'Зив-8', 'file': 'book.pdf'}], '--force')
        self.assertIn('записано: 1', out)
        self.ziv.refresh_from_db()
        # Старый файл удалён, новый — без хвостов «_abc123» от хранилища
        self.assertRegex(self.ziv.cover.name,
                         rf'^source_covers/source-{self.ziv.pk}-[0-9a-f]{{8}}\.jpg$')
        self.assertEqual(len(list((Path(self.ziv.cover.path).parent).iterdir())), 1)

    def test_ambiguous_unknown_and_missing_file_are_reported(self):
        out, err = self.run_command([
            {'match': '7 класс', 'file': 'book.pdf'},
            {'match': 'Нет такой книги', 'file': 'book.pdf'},
            {'match': 'Зив-8', 'file': 'nope.pdf'},
        ])
        self.assertIn('подходит несколько источников', err)
        self.assertIn('нет источника', err)
        self.assertIn('нет файла', err)
        self.assertIn('пропущено с ошибкой: 3', out)
        self.assertFalse(Source.objects.exclude(cover='').exists())

    def test_dry_run_writes_nothing(self):
        out, _ = self.run_command([{'match': 'Зив-8', 'file': 'book.pdf'}], '--dry-run')
        self.assertIn('Зив-8 ← book.pdf, стр. 1', out)
        self.ziv.refresh_from_db()
        self.assertFalse(self.ziv.cover)

    def test_export_then_import_on_another_machine(self):
        export = self.dir / 'export'
        self.run_command([{'match': '7 класс', 'author': 'Волчкевич', 'file': 'book.pdf'}],
                         '--export', str(export))
        self.geo7.refresh_from_db()
        self.assertFalse(self.geo7.cover)
        rows = json.loads((export / 'covers.json').read_text(encoding='utf-8'))
        self.assertEqual(rows, [{'match': '7 класс', 'author': 'Волчкевич',
                                 'file': 'cover-01.jpg'}])
        # Выгрузке не нужен источник в локальной базе — только файл
        out, err = self.run_command([{'match': 'Книга только на проде', 'file': 'book.pdf'}],
                                    '--export', str(self.dir / 'export2'))
        self.assertEqual(err, '')
        self.assertIn('выгружено: 1', out)
        # Сервер: тот же список с путями к JPEG рядом с ним
        out = io.StringIO()
        call_command('source_covers', str(export / 'covers.json'), stdout=out)
        self.assertIn('записано: 1', out.getvalue())
        self.geo7.refresh_from_db()
        self.assertTrue(self.geo7.cover)

    def test_cover_view_and_versioned_link(self):
        self.run_command([{'match': 'Зив-8', 'file': 'book.pdf'}])
        self.ziv.refresh_from_db()
        url = cover_url(self.ziv)
        version = self.ziv.cover.name.rsplit('-', 1)[-1].removesuffix('.jpg')
        self.assertEqual(url, f"{reverse('source_cover', args=[self.ziv.pk])}?v={version}")
        self.assertEqual(cover_url(self.geo7), '')
        # Анониму — на вход, учителю — JPEG с суточным кэшем; без обложки — 404
        self.assertEqual(self.client.get(url).status_code, 302)
        make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertIn('max-age=86400', response['Cache-Control'])
        self.assertEqual(b''.join(response.streaming_content)[:2], b'\xff\xd8')
        missing = self.client.get(reverse('source_cover', args=[self.geo7.pk]))
        self.assertEqual(missing.status_code, 404)

    def test_cover_uploaded_in_admin_keeps_its_type(self):
        png = io.BytesIO()
        Image.new('RGB', (52, 72), 'green').save(png, 'PNG')
        self.geo7.cover.save('geo7.png', ContentFile(png.getvalue()), save=True)
        make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse('source_cover', args=[self.geo7.pk]))
        self.assertEqual(response['Content-Type'], 'image/png')

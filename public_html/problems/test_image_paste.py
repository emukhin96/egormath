"""Картинки, вставленные из буфера обмена (static/js/image_paste.js).

Браузер присылает такой файл с именем вида paste-20261014-153000.png,
а сторонний клиент — и вовсе без расширения. Загрузка должна проходить
обычную валидацию и сжатие TaskImage, а плохой файл — давать ошибку
формы, а не 500.
"""
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Task, TaskImage
from .tests import formset_management, make_teacher


def image_bytes(fmt='PNG', size=(40, 30)):
    buf = io.BytesIO()
    Image.new('RGB', size, color=(10, 120, 200)).save(buf, format=fmt)
    return buf.getvalue()


class ImagePasteTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def create_task(self, upload):
        return self.client.post(reverse('task_create'), {
            'text_latex': 'Задача с рисунком \\taskpic{1}', 'columns': 0,
            'answer_latex': '', 'solution_latex': '',
            'stars': 0, 'answer_type': 'number',
            **formset_management('source_refs'),
            **formset_management('subitems'),
            **formset_management('images', total=1),
            'images-0-order': 10, 'images-0-image': upload,
        })

    def test_base_includes_script_and_marks_formset_input(self):
        response = self.client.get(reverse('task_create'))
        self.assertContains(response, 'js/image_paste.js')
        # У строки формсета своё превью — зона вставки без миниатюры
        self.assertContains(response, 'data-image-paste-thumb="off"')

    def test_pasted_png_is_saved(self):
        response = self.create_task(SimpleUploadedFile(
            'paste-20261014-153000.png', image_bytes(), 'image/png'))
        self.assertEqual(response.status_code, 302)
        image = TaskImage.objects.get()
        self.assertTrue(image.filename.startswith('paste-20261014-153000'))
        self.assertTrue(image.filename.endswith('.png'))

    def test_png_without_extension_gets_one(self):
        response = self.create_task(SimpleUploadedFile(
            'paste', image_bytes(), 'image/png'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(TaskImage.objects.get().filename.endswith('.png'))

    def test_jpeg_without_extension_gets_one(self):
        response = self.create_task(SimpleUploadedFile(
            'paste', image_bytes('JPEG'), 'image/jpeg'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(TaskImage.objects.get().filename.endswith('.jpg'))

    def test_webp_is_stored_as_jpeg(self):
        response = self.create_task(SimpleUploadedFile(
            'paste-20261014-153000.webp', image_bytes('WEBP'), 'image/webp'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(TaskImage.objects.get().filename.endswith('.jpg'))

    def test_not_an_image_is_form_error(self):
        response = self.create_task(SimpleUploadedFile(
            'paste-20261014-153000.png', b'not an image', 'image/png'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'не похож на картинку')
        self.assertFalse(Task.objects.exists())

    @override_settings(TASK_IMAGE_MAX_SIZE_MB=0)
    def test_too_large_is_form_error(self):
        response = self.create_task(SimpleUploadedFile(
            'paste-20261014-153000.png', image_bytes(), 'image/png'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'уменьшите картинку')
        self.assertFalse(TaskImage.objects.exists())

    def test_inline_editor_accepts_pasted_png(self):
        task = Task.objects.create(text_latex='Условие', created_by=self.teacher)
        url = reverse('task_manage', args=[task.pk])
        response = self.client.post(url, {
            'block': 'images', 'scope': 'global',
            **formset_management('images', total=1),
            'images-0-order': 10,
            'images-0-image': SimpleUploadedFile(
                'paste', image_bytes(), 'image/png'),
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(task.images.get().filename.endswith('.png'))

    def test_inline_editor_bad_file_is_json_error(self):
        task = Task.objects.create(text_latex='Условие', created_by=self.teacher)
        response = self.client.post(reverse('task_manage', args=[task.pk]), {
            'block': 'images', 'scope': 'global',
            **formset_management('images', total=1),
            'images-0-order': 10,
            'images-0-image': SimpleUploadedFile(
                'paste.png', b'garbage', 'image/png'),
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertIn('не похож на картинку', response.json()['errors']['__all__'][0])
        self.assertFalse(task.images.exists())

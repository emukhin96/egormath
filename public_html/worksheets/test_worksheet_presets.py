"""«Свойства листка»: шапка макетом, сохранённые настройки листка
(worksheets/presets.py) и свой префикс имени PDF (filenames.clean_prefix)."""
from django.test import TestCase
from django.urls import reverse

from problems.tests import make_teacher
from worksheets.filenames import clean_prefix
from worksheets.models import Worksheet, WorksheetPreset


class PdfPrefixTests(TestCase):
    def setUp(self):
        self.owner = make_teacher()

    def test_clean_prefix(self):
        self.assertEqual(clean_prefix('Лицей 8'), 'licey-8')
        self.assertEqual(clean_prefix('  geom8 '), 'geom8')
        self.assertEqual(clean_prefix('Алг--8__'), 'alg-8')
        self.assertEqual(clean_prefix('!!!'), '')

    def test_custom_prefix_replaces_subject_and_grade(self):
        sheet = Worksheet.objects.create(
            title='Разложение на множители', owner=self.owner, grade=7)
        self.assertEqual(sheet.pdf_filename(), 'math7-razl_mnozh.pdf')
        sheet.pdf_prefix = 'lyceum7'
        self.assertEqual(sheet.pdf_filename(), 'lyceum7-razl_mnozh.pdf')
        self.assertEqual(sheet.pdf_filename('answers'), 'lyceum7-razl_mnozh-otvety.pdf')
        self.assertEqual(sheet.beamer_filename(), 'lyceum7-razl_mnozh-prezentaciya.pdf')
        # Имя целиком по-прежнему главнее префикса
        sheet.pdf_basename = 'svoe'
        self.assertEqual(sheet.pdf_filename(), 'svoe.pdf')

    def test_form_normalizes_and_rejects_prefix(self):
        self.client.force_login(self.owner)
        sheet = Worksheet.objects.create(title='Дроби', owner=self.owner)
        url = reverse('worksheet_edit', args=[sheet.pk])
        data = {'title': 'Дроби', 'pdf_prefix': 'Лицей 8'}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        sheet.refresh_from_db()
        self.assertEqual(sheet.pdf_prefix, 'licey-8')
        response = self.client.post(url, {'title': 'Дроби', 'pdf_prefix': '!!!'})
        self.assertContains(response, 'В префиксе нужны буквы или цифры')
        # 40 символов кириллицы в транслите втрое длиннее поля — ошибка, не 500
        response = self.client.post(url, {'title': 'Дроби', 'pdf_prefix': 'щ' * 40})
        self.assertContains(response, 'Префикс латиницей — не длиннее 40 символов')


class WorksheetPresetTests(TestCase):
    def setUp(self):
        self.owner = make_teacher()
        self.other = make_teacher('teacher2')
        self.client.force_login(self.owner)

    def save(self, **data):
        return self.client.post(reverse('worksheet_preset_save'), {
            'grade_label': '8 класс', 'author_name': 'Лицей 1535', 'subtitle': '',
            'pdf_prefix': 'Лицей 8', **data})

    def test_save_and_overwrite_by_name(self):
        response = self.save(name='Лицей')
        self.assertTrue(response.json()['ok'])
        preset = WorksheetPreset.objects.get(owner=self.owner)
        self.assertEqual(preset.pdf_prefix, 'licey-8')
        self.assertEqual(preset.author_name, 'Лицей 1535')
        self.save(name='Лицей', grade_label='9 класс')
        self.assertEqual(WorksheetPreset.objects.get(owner=self.owner).grade_label, '9 класс')
        self.assertEqual(self.save(name='  ').status_code, 400)
        too_long = self.save(name='Длинный', pdf_prefix='щ' * 30)
        self.assertEqual(too_long.status_code, 400)
        self.assertIn('не длиннее 40 символов', too_long.json()['message'])
        self.assertFalse(WorksheetPreset.objects.filter(name='Длинный').exists())

    def test_one_default_and_new_worksheet_prefilled(self):
        self.save(name='Восьмые', is_default='1')
        self.save(name='Девятые', grade_label='9 класс', is_default='1')
        self.assertEqual(
            list(WorksheetPreset.objects.filter(is_default=True).values_list('name', flat=True)),
            ['Девятые'])
        response = self.client.get(reverse('worksheet_create'))
        form = response.context['form']
        self.assertEqual(form.initial['grade_label'], '9 класс')
        self.assertContains(response, 'по настройкам «Девятые»')
        eighth = WorksheetPreset.objects.get(name='Восьмые')
        chosen = self.client.get(reverse('worksheet_create'), {'preset': eighth.pk})
        self.assertEqual(chosen.context['form'].initial['grade_label'], '8 класс')
        # Шапка — полями макета (класс sheet-head-input), имя PDF — подсказкой
        self.assertContains(response, 'class="sheet-head-input"', count=4)
        self.assertContains(response, 'data-auto-prefix="math"')

    def test_presets_are_private(self):
        self.save(name='Секретные настройки')
        preset = WorksheetPreset.objects.get()
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse('worksheet_create')), 'Секретные настройки')
        self.assertEqual(self.client.get(reverse('worksheet_create'), {'preset': preset.pk})
                         .context['form'].initial, {})
        response = self.client.post(reverse('worksheet_preset_delete', args=[preset.pk]))
        self.assertEqual(response.status_code, 404)
        self.client.force_login(self.owner)
        self.assertTrue(self.client.post(
            reverse('worksheet_preset_delete', args=[preset.pk])).json()['ok'])
        self.assertFalse(WorksheetPreset.objects.exists())


class WorksheetFormScriptsTests(TestCase):
    def test_bundle_scripts_not_included_twice(self):
        """dialogs.js и autosave.js — в app.js; второй экземпляр удвоил бы
        обработчики и запросы автосохранения."""
        self.client.force_login(make_teacher())
        response = self.client.get(reverse('worksheet_create'))
        self.assertContains(response, 'js/worksheet_form.js')
        self.assertNotContains(response, 'js/dialogs.js')
        self.assertNotContains(response, 'js/autosave.js')

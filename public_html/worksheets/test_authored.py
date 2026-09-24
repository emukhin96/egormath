"""Авторские листки в подборках: перенос туда и обратно, видимость."""
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from problems.models import ExamItem, ExamModel, Task
from problems.tests import make_teacher
from worksheets.models import Collection, Worksheet, WorksheetItem
from worksheets.tests import make_worksheet

from .authored import (AuthoredError, move_to_collections,
                       move_to_worksheets, section_for)
from .corpus import SOURCE_TITLE


class AuthoredSectionTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = make_worksheet(self.teacher)

    def test_section_by_grade_exam_and_misc(self):
        self.assertEqual(section_for(self.worksheet)[1], 'Разное')
        self.worksheet.grade = 8
        self.assertEqual(section_for(self.worksheet)[:2], ('grade:8', '8 класс'))
        self.worksheet.grade = 11
        self.assertEqual(section_for(self.worksheet)[:2], ('grade:10', '10–11 класс'))
        model, _ = ExamModel.objects.get_or_create(
            exam_type=ExamModel.TYPE_OGE, exam_year=2026,
            defaults={'code': 'OGE_2026', 'name': 'ОГЭ 2026'})
        item, _ = ExamItem.objects.get_or_create(
            exam_model=model, item_number=1,
            defaults={'code': 'OGE_2026_01', 'name': '№1'})
        tasks = [row.task for row in self.worksheet.ordered_items()]
        tasks[0].exam_items.add(item)
        # Одна задача из двух — не большинство.
        self.assertEqual(section_for(self.worksheet)[1], '10–11 класс')
        tasks[1].exam_items.add(item)
        self.assertEqual(section_for(self.worksheet)[:2], ('exam:OGE', 'ОГЭ'))


class AuthoredMoveTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.other = make_teacher('teacher2')
        self.worksheet = make_worksheet(self.teacher, title='Проценты')
        self.worksheet.grade = 6
        self.worksheet.comment = 'corpus:6 класс/percent'
        self.worksheet.save()
        self.client.login(username='teacher1', password='pass12345')

    def test_move_creates_private_collection_in_grade_section(self):
        collection = move_to_collections(self.worksheet, self.teacher)
        self.assertEqual(collection.source.title, SOURCE_TITLE)
        self.assertEqual(collection.parent.worksheet.title, '6 класс')
        self.assertEqual(collection.locator, 'corpus:6 класс/percent')
        self.assertFalse(collection.is_published)
        self.assertTrue(collection.parent.is_published)
        # Раздел переиспользуется, повторный перенос — ошибка.
        second = make_worksheet(self.teacher, title='Дроби')
        second.grade = 6
        second.save()
        self.assertEqual(
            move_to_collections(second, self.other).parent, collection.parent)
        with self.assertRaises(AuthoredError):
            move_to_collections(self.worksheet, self.teacher)
        with self.assertRaises(AuthoredError):
            move_to_collections(
                Worksheet.objects.create(title='Пустой', owner=self.teacher),
                self.teacher)

    def test_section_container_is_protected_from_teachers(self):
        collection = move_to_collections(self.worksheet, self.teacher)
        second = make_worksheet(self.other, title='Чужая')
        second.grade = 6
        second.save()
        foreign = move_to_collections(second, self.other)
        section = collection.parent
        self.assertEqual(foreign.parent, section)
        self.assertEqual(section.worksheet.owner.username, 'authored-sections')
        self.assertFalse(section.worksheet.owner.is_active)
        # Ни первый, ни второй учитель не могут удалить или править контейнер.
        for username in ('teacher1', 'teacher2'):
            self.client.login(username=username, password='pass12345')
            response = self.client.post(
                reverse('worksheet_delete', args=[section.worksheet_id]))
            self.assertEqual(response.status_code, 404)
            response = self.client.get(
                reverse('worksheet_detail', args=[section.worksheet_id]))
            self.assertEqual(response.status_code, 404)
            response = self.client.get(
                reverse('collection_edit', args=[section.pk]))
            self.assertEqual(response.status_code, 403)
        self.assertTrue(Collection.objects.filter(pk=section.pk).exists())
        self.assertEqual(Collection.objects.filter(parent=section).count(), 2)

    def test_visibility_and_publish_toggle(self):
        collection = move_to_collections(self.worksheet, self.teacher)
        # Владелец видит, чужой учитель — нет; в «Моих листках» листка нет.
        response = self.client.get(reverse('worksheet_list'))
        self.assertNotContains(response, 'Проценты')
        response = self.client.get(
            reverse('collection_list'), {'source': collection.source_id})
        self.assertContains(response, '6 класс')
        response = self.client.get(
            reverse('collection_detail', args=[collection.parent.pk]), follow=True)
        self.assertContains(response, 'Проценты')
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.get(reverse('collection_list'))
        self.assertNotContains(response, SOURCE_TITLE)
        self.assertEqual(self.client.get(
            reverse('collection_detail', args=[collection.pk])).status_code, 403)
        # Чужой не может опубликовать; владелец — может.
        response = self.client.post(
            reverse('collection_publish', args=[collection.pk]), {'published': '1'})
        self.assertEqual(response.status_code, 403)
        self.client.login(username='teacher1', password='pass12345')
        self.client.post(
            reverse('collection_publish', args=[collection.pk]), {'published': '1'})
        collection.refresh_from_db()
        self.assertTrue(collection.is_published)
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.get(
            reverse('collection_detail', args=[collection.parent.pk]), follow=True)
        self.assertContains(response, 'Проценты')

    def test_section_page_hides_foreign_private_children(self):
        collection = move_to_collections(self.worksheet, self.teacher)
        self.client.login(username='teacher2', password='pass12345')
        published = make_worksheet(self.other, title='Открытая')
        published.grade = 6
        published.save()
        mine = move_to_collections(published, self.other)
        mine.is_published = True
        mine.save()
        response = self.client.get(
            reverse('collection_detail', args=[collection.parent.pk]), follow=True)
        self.assertContains(response, 'Открытая')
        self.assertNotContains(response, 'Проценты')

    def test_move_back_and_views(self):
        response = self.client.post(
            reverse('worksheet_to_collections', args=[self.worksheet.pk]))
        collection = Collection.objects.get(worksheet=self.worksheet)
        self.assertRedirects(
            response, reverse('collection_detail', args=[collection.pk]))
        response = self.client.get(
            reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertContains(response, 'Вернуть в мои листки')
        response = self.client.post(
            reverse('collection_to_worksheets', args=[collection.pk]))
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertFalse(Collection.objects.filter(pk=collection.pk).exists())
        self.assertTrue(Worksheet.objects.filter(pk=self.worksheet.pk).exists())
        self.assertContains(self.client.get(reverse('worksheet_list')), 'Проценты')
        # Раздел вернуть нельзя, чужую подборку тоже.
        section = Collection.objects.get(locator='section:grade:6')
        with self.assertRaises(AuthoredError):
            move_to_worksheets(section)

    def test_bulk_move_from_worksheet_list(self):
        other_sheet = make_worksheet(self.teacher, title='Дроби')
        response = self.client.post(reverse('worksheet_bulk_update'), {
            'ids': [self.worksheet.pk, other_sheet.pk], 'to_collections': '1'})
        self.assertRedirects(response, reverse('worksheet_list'))
        self.assertEqual(Collection.objects.filter(
            worksheet__in=[self.worksheet, other_sheet]).count(), 2)
        self.assertEqual(
            Collection.objects.get(worksheet=other_sheet).parent.worksheet.title,
            'Разное')

    def test_management_command(self):
        out = StringIO()
        call_command('authored_to_collections', '--dry-run', stdout=out)
        self.assertIn('Проценты', out.getvalue())
        self.assertFalse(Collection.objects.filter(worksheet=self.worksheet).exists())
        call_command('authored_to_collections', stdout=out)
        self.assertTrue(Collection.objects.filter(worksheet=self.worksheet).exists())
        call_command('authored_to_collections', stdout=out)
        self.assertIn('Итого перенесено: 0', out.getvalue())


class CorpusPushTests(TestCase):
    def setUp(self):
        from problems.rubricator import seed_rubricator
        seed_rubricator()
        self.teacher = make_teacher()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch('worksheet_corpus.paths.OUTPUT_DIR', Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_push_goes_to_collections(self):
        from worksheet_corpus.store import save_draft
        from .corpus import push_draft
        from .test_corpus import _sample_draft
        draft = _sample_draft()
        save_draft(draft)
        worksheet, info = push_draft(draft, self.teacher)
        self.assertIsNotNone(info['collection'])
        self.assertEqual(info['collection'].parent.worksheet.title, '6 класс')
        self.assertFalse(info['collection'].is_published)
        again, info2 = push_draft(draft, self.teacher)
        self.assertEqual(again.pk, worksheet.pk)
        self.assertEqual(Collection.objects.filter(worksheet=worksheet).count(), 1)

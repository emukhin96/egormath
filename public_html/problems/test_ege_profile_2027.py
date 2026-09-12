"""Проверки актуальной таксономии профильного ЕГЭ."""

import importlib

from django.apps import apps
from django.test import TestCase

from problems.models import (ExamItem, ExamModel, Source, Task,
                             TextbookImportBatch, TextbookTaskDraft)
from problems.rubricator import seed_rubricator


class EgeProfile2027TaxonomyTests(TestCase):
    def test_active_profile_model_has_all_2027_positions(self):
        seed_rubricator()

        model = ExamModel.objects.get(code='EXAM_EGE_PROFILE_2027')
        items = list(model.items.order_by('item_number').values_list(
            'item_number', 'code', 'name'))

        self.assertEqual(model.exam_year, 2027)
        self.assertEqual(
            [number for number, _code, _name in items], list(range(21)))
        self.assertEqual(
            [code for _number, code, _name in items],
            ['EGE_PROFILE_2027'] + [
                f'EGE_PROFILE_2027_{number:02d}'
                for number in range(1, 21)],
        )

    def test_new_positions_follow_project_structure(self):
        seed_rubricator()

        names = dict(ExamItem.objects.filter(
            code__startswith='EGE_PROFILE_2027_').values_list('code', 'name'))
        self.assertIn('случайные величины', names['EGE_PROFILE_2027_06'])
        self.assertIn('текстовая задача', names['EGE_PROFILE_2027_11'])
        self.assertIn('финансовая математика', names['EGE_PROFILE_2027_13'])
        self.assertIn('экстремальная текстовая задача',
                      names['EGE_PROFILE_2027_17'])

    def test_migration_keeps_only_referenced_legacy_items(self):
        legacy_model = ExamModel.objects.create(
            code='EXAM_EGE_PROFILE_2026', exam_type='EGE_PROFILE',
            exam_year=2026, name='ЕГЭ по математике, профильный уровень — 2026')
        unused = ExamItem.objects.create(
            exam_model=legacy_model, item_number=1,
            code='EGE_PROFILE_2026_01', name='Старая метка', order=1)
        linked = ExamItem.objects.create(
            exam_model=legacy_model, item_number=2,
            code='EGE_PROFILE_2026_02', name='Связанная старая метка', order=2)
        task = Task.objects.create(text_latex='Задача со старой меткой')
        task.exam_items.add(linked)

        migration = importlib.import_module(
            'problems.migrations.0025_ege_profile_2027')
        migration.install_ege_profile_2027(apps, None)

        self.assertFalse(ExamItem.objects.filter(pk=unused.pk).exists())
        self.assertTrue(ExamItem.objects.filter(pk=linked.pk).exists())
        self.assertTrue(ExamModel.objects.filter(pk=legacy_model.pk).exists())

    def test_migration_keeps_legacy_item_referenced_by_draft(self):
        legacy_model = ExamModel.objects.create(
            code='EXAM_EGE_PROFILE_2026', exam_type='EGE_PROFILE',
            exam_year=2026, name='ЕГЭ по математике, профильный уровень — 2026')
        draft_item = ExamItem.objects.create(
            exam_model=legacy_model, item_number=1,
            code='EGE_PROFILE_2026_01', name='Метка черновика', order=1)
        from django.contrib.auth.models import User
        editor = User.objects.create_user('draft-editor')
        batch = TextbookImportBatch.objects.create(
            title='Черновики', profile='test',
            source=Source.objects.create(title='Источник'), created_by=editor)
        TextbookTaskDraft.objects.create(
            batch=batch, external_id='1', source_number='1',
            text_latex='Черновик', exam_item_codes=[draft_item.code])

        migration = importlib.import_module(
            'problems.migrations.0025_ege_profile_2027')
        migration.install_ege_profile_2027(apps, None)

        self.assertTrue(ExamItem.objects.filter(pk=draft_item.pk).exists())

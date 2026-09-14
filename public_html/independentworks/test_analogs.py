"""Проверки сохранённых связей при неполном импорте и рубриках."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from problems.models import Source, Task, TaskSource
from worksheets.models import Collection, Worksheet, WorksheetItem
from .analogs import sync_families
from .models import Family, FamilyMember


class AnalogDiscoveryTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(title='Банк')
        self.owner = get_user_model().objects.create_user('analog_owner')

    def ref(self, locator, path=()):
        task = Task.objects.create(text_latex=locator)
        TaskSource.objects.create(source=self.source, task=task, locator=locator, source_path=list(path))
        return task

    def test_partial_ziv_dry_run_and_later_import(self):
        first = self.ref('sr/1/v1/2')
        report = sync_families(report=True, dry_run=True)
        self.assertEqual(len(report['incomplete']), 1)
        self.assertFalse(Family.objects.exists())
        second = self.ref('sr/1/v2/2')
        report = sync_families(report=True, dry_run=True)
        self.assertEqual(report['members_added'], 2)
        self.assertFalse(Family.objects.exists())
        sync_families()
        self.assertEqual(set(Family.objects.get().tasks.all()), {first, second})
        self.assertTrue(FamilyMember.objects.first().evidence)
        self.assertEqual(sync_families(report=True)['members_added'], 0)

    def test_same_prototype_in_different_sections(self):
        for chapter in ('Алгебра', 'Геометрия'):
            for i in range(2):
                self.ref(f'{chapter}-{i}', [chapter, 'Прототип 1.1'])
        sync_families()
        self.assertEqual(Family.objects.count(), 2)
        self.assertTrue(all(f.tasks.count() == 2 for f in Family.objects.all()))

    def test_inline_rubrics_and_ambiguous_heading(self):
        sheet = Worksheet.objects.create(owner=self.owner, title='№6')
        Collection.objects.create(source=self.source, worksheet=sheet, locator='six')
        WorksheetItem.objects.create(worksheet=sheet, order=1, rubric='Прототип 6.1')
        for order in (2, 3):
            WorksheetItem.objects.create(worksheet=sheet, order=order, task=Task.objects.create(text_latex=str(order)))
        WorksheetItem.objects.create(worksheet=sheet, order=4, rubric='Аналоги')
        WorksheetItem.objects.create(worksheet=sheet, order=5, task=Task.objects.create(text_latex='Неопределённый'))
        report = sync_families(report=True)
        self.assertEqual(Family.objects.get().tasks.count(), 2)
        self.assertEqual(len(report['ambiguous']), 1)
        self.assertTrue(FamilyMember.objects.first().evidence[0]['item_id'])

    def test_manual_membership_is_preserved(self):
        self.ref('sr/1/v1/2')
        # Разные записи источника могут указывать на одинаковый номер
        # в рубриках; неоднозначная группа не должна объединяться молча.
        self.ref('sr/1/v2/2')
        family = Family.objects.create(key='manual:keep', title='Учитель')
        family.tasks.add(Task.objects.first())
        sync_families()
        self.assertEqual(family.tasks.count(), 1)
        self.assertEqual(family.familymember_set.get().origin, 'manual')

    def test_production_ege_sibling_prototype_and_nested_analogs(self):
        root_sheet = Worksheet.objects.create(owner=self.owner, title='№7. Уравнения 1')
        root = Collection.objects.create(source=self.source, worksheet=root_sheet, locator='root')
        proto_sheet = Worksheet.objects.create(owner=self.owner, title='№07. Уравнения 1 — прототип 7.1')
        Collection.objects.create(source=self.source, worksheet=proto_sheet, parent=root, locator='proto')
        branch_sheet = Worksheet.objects.create(owner=self.owner, title='Прототип 7.1')
        branch = Collection.objects.create(source=self.source, worksheet=branch_sheet, parent=root, locator='branch')
        analog_sheet = Worksheet.objects.create(owner=self.owner, title='Аналоги')
        Collection.objects.create(source=self.source, worksheet=analog_sheet, parent=branch, locator='analogs')
        for sheet in (proto_sheet, analog_sheet):
            WorksheetItem.objects.create(worksheet=sheet, task=Task.objects.create(text_latex='Уравнение'))
        sync_families()
        self.assertEqual(Family.objects.count(), 1)
        self.assertEqual(Family.objects.get().tasks.count(), 2)

    def test_production_oge_generic_sections_use_task_number(self):
        for section, locator in [('Прототипы', '6.1'), ('Аналоги', '6.1.1'), ('Аналоги', '6.2.1')]:
            task = self.ref(locator, ['№06. Дроби', section])
            sheet = Worksheet.objects.create(owner=self.owner, title='№6. Дроби — ' + section)
            collection = Collection.objects.create(source=self.source, worksheet=sheet,
                locator=locator, source_path=['№06. Дроби', section])
            WorksheetItem.objects.create(worksheet=sheet, task=task)
        report = sync_families(report=True)
        self.assertEqual(Family.objects.count(), 1)
        self.assertEqual(Family.objects.get().tasks.count(), 2)
        self.assertEqual(report['ambiguous'], [])

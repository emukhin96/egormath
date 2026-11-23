"""Переход к соседям на странице подборки (worksheets/collection_neighbors.py):
варианты одной работы — сегментами, стрелки — в соседнюю работу на тот же
вариант."""
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from problems.models import Source, Task
from problems.tests import make_teacher
from worksheets.collection_catalog import variant_label
from worksheets.models import Collection, Worksheet, WorksheetItem


class VariantLabelTests(SimpleTestCase):
    def test_variant_from_locator(self):
        self.assertEqual(variant_label('key:Глава III/СР III.1/Вариант 3*'), 'Вариант 3*')
        self.assertEqual(variant_label('key:Упражнения/Одночлены/вариант 2'), 'Вариант 2')
        self.assertEqual(variant_label('key:Варианты вступительных экзаменов в МГУ/1970 год'), '')
        self.assertEqual(variant_label('key:Сборник/Варианты МГУ'), '')
        self.assertEqual(variant_label(''), '')


class CollectionNeighborsTests(TestCase):
    def setUp(self):
        self.owner = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.source = Source.objects.create(title='Шабунин')
        self.parent = self.make('Дидактические материалы', 'key:ДМ')
        self.sr1 = [self.make('Самостоятельная работа III.1', f'key:ДМ/СР1/Вариант {n}',
                              parent=self.parent, order=10) for n in (1, 2, 3)]
        self.sr2 = [self.make('Самостоятельная работа III.2', f'key:ДМ/СР2/Вариант {n}',
                              parent=self.parent, order=20) for n in (1, 2)]
        self.kr = self.make('Контрольная работа III.1', 'key:ДМ/КР1', parent=self.parent, order=30)

    def make(self, title, locator, parent=None, order=0, published=True):
        sheet = Worksheet.objects.create(title=title, owner=self.owner)
        WorksheetItem.objects.create(
            worksheet=sheet, order=10,
            task=Task.objects.create(text_latex=f'Задача: {locator}', created_by=self.owner))
        return Collection.objects.create(
            worksheet=sheet, source=self.source, parent=parent, locator=locator,
            order=order, is_published=published)

    def page(self, collection, **params):
        return self.client.get(reverse('collection_detail', args=[collection.pk]), params)

    def test_variants_and_arrows_keep_variant(self):
        response = self.page(self.sr1[1])
        neighbors = response.context['neighbors']
        self.assertEqual([v['label'] for v in neighbors['variants']], ['1', '2', '3'])
        self.assertEqual([v['current'] for v in neighbors['variants']], [False, True, False])
        self.assertIsNone(neighbors['prev'])
        # Дальше — следующая работа на тот же вариант 2
        self.assertEqual(neighbors['next'].pk, self.sr2[1].pk)
        self.assertContains(response, 'aria-label="Соседние подборки"')
        self.assertContains(response, f'href="{reverse("collection_detail", args=[self.sr1[2].pk])}?"')
        # Варианта 3 в соседней работе нет — последний из её вариантов
        self.assertEqual(self.page(self.sr1[2]).context['neighbors']['next'].pk, self.sr2[1].pk)
        back = self.page(self.sr2[1]).context['neighbors']
        self.assertEqual(back['prev'].pk, self.sr1[1].pk)
        self.assertEqual(back['next'].pk, self.kr.pk)
        self.assertEqual((back['position'], back['total']), (2, 3))

    def test_single_work_has_arrows_only(self):
        neighbors = self.page(self.kr).context['neighbors']
        self.assertEqual(neighbors['variants'], [])
        self.assertEqual(neighbors['prev'].pk, self.sr2[0].pk)
        self.assertIsNone(neighbors['next'])

    def test_variant_link_keeps_page_and_filter(self):
        response = self.page(self.sr1[0], topic='5')
        self.assertContains(
            response, f'href="{reverse("collection_detail", args=[self.sr1[1].pk])}?topic=5"')

    def test_hidden_sibling_and_lonely_collection(self):
        hidden = self.make('Самостоятельная работа III.1', 'key:ДМ/СР1/Вариант 4',
                           parent=self.parent, order=10, published=False)
        hidden.worksheet.owner = make_teacher('teacher2')
        hidden.worksheet.save()
        labels = [v['label'] for v in self.page(self.sr1[0]).context['neighbors']['variants']]
        self.assertEqual(labels, ['1', '2', '3'])
        lonely = self.make('Одна подборка', 'key:Одна')
        other_source = Source.objects.create(title='Другой')
        Collection.objects.filter(pk=lonely.pk).update(source=other_source)
        response = self.page(lonely)
        self.assertIsNone(response.context['neighbors'])
        self.assertNotContains(response, 'Соседние подборки')

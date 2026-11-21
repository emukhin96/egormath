"""Фильтр правой панели внутри подборки (worksheets/collection_filters.py):
темы и содержание задач ЭТОЙ подборки, выбор подборки не сбрасывается."""
from django.test import TestCase
from django.urls import reverse

from problems.models import FacetType, FacetValue, Source, Task, Topic
from problems.tests import make_teacher
from worksheets.models import Collection, Worksheet, WorksheetItem


class CollectionFilterTests(TestCase):
    def setUp(self):
        self.owner = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.source = Source.objects.create(title='Задачник')
        self.sheet = Worksheet.objects.create(title='Глава 1', owner=self.owner)
        self.collection = Collection.objects.create(
            worksheet=self.sheet, source=self.source, locator='g1', is_published=True)
        self.linear = Topic.objects.create(code='T.LIN', name='Линейные уравнения')
        self.square = Topic.objects.create(code='T.SQ', name='Квадратные уравнения')
        content_type = FacetType.objects.create(code='CONTENT', name='Содержание')
        group = FacetValue.objects.create(facet_type=content_type, code='MOD', name='Модуль')
        self.modulus = FacetValue.objects.create(
            facet_type=content_type, code='MOD_EQ', name='Уравнение с модулем', parent=group)
        order = iter(range(10, 1000, 10))

        def rubric(title):
            WorksheetItem.objects.create(worksheet=self.sheet, rubric=title, order=next(order))

        def task(text, topic, content=None):
            created = Task.objects.create(text_latex=text, created_by=self.owner)
            created.topics.add(topic)
            if content:
                created.facet_values.add(content)
            WorksheetItem.objects.create(worksheet=self.sheet, task=created, order=next(order))
            return created

        rubric('§ 1. Линейные')
        self.a = task('Решите $x+1=2$.', self.linear)
        self.b = task('Решите $|x|=2$.', self.linear, self.modulus)
        rubric('§ 2. Квадратные')
        self.c = task('Решите $x^2=4$.', self.square)

    def url(self, **params):
        return self.client.get(reverse('collection_detail', args=[self.collection.pk]), params)

    def test_sidebar_lists_task_topics_with_counts_and_stays_in_collection(self):
        response = self.url()
        self.assertContains(response, 'Темы задач подборки')
        self.assertContains(response, f'href="?topic={self.linear.pk}"')
        self.assertContains(response, 'href="?content=MOD_EQ"')
        self.assertNotContains(response, f'{reverse("task_list")}?topic=')
        choices = {c['obj'].pk: c['total'] for c in response.context['collection_filter']['topics']}
        self.assertEqual(choices, {self.linear.pk: 2, self.square.pk: 1})

    def test_topic_filter_keeps_collection_and_drops_empty_paragraphs(self):
        response = self.url(topic=self.square.pk)
        self.assertContains(response, 'x^2=4')
        self.assertNotContains(response, 'x+1=2')
        self.assertContains(response, '§ 2. Квадратные')
        self.assertNotContains(response, '§ 1. Линейные</h3>')
        self.assertContains(response, 'Все задачи подборки')
        # Список тем не прыгает: счётчики по всей подборке, выбранная отмечена
        topics = response.context['collection_filter']['topics']
        self.assertEqual(len(topics), 2)
        active = [c for c in topics if c['active']]
        self.assertEqual([c['obj'].pk for c in active], [self.square.pk])
        self.assertEqual(active[0]['url'], '?')

    def test_content_filter_and_empty_result(self):
        response = self.url(content='MOD_EQ')
        self.assertContains(response, '|x|=2')
        self.assertNotContains(response, 'x+1=2')
        empty = self.url(content='MOD_EQ', topic=self.square.pk)
        self.assertContains(empty, 'Нет задач по выбранному фильтру')

    def test_paragraph_links_keep_filter(self):
        response = self.url(topic=self.linear.pk)
        self.assertContains(response, f'href="?topic={self.linear.pk}&amp;page=1#section-0"')

    def test_crumbs_link_source_and_parent(self):
        child_sheet = Worksheet.objects.create(title='§ 1. Линейные', owner=self.owner)
        child = Collection.objects.create(
            worksheet=child_sheet, source=self.source, parent=self.collection,
            locator='g1-1', is_published=True)
        WorksheetItem.objects.create(worksheet=child_sheet, task=self.a, order=10)
        response = self.client.get(reverse('collection_detail', args=[child.pk]))
        self.assertContains(response, f'href="{reverse("collection_list")}?source={self.source.pk}"')
        self.assertContains(response, f'href="{reverse("collection_detail", args=[self.collection.pk])}"')

    def test_section_list_filters_child_collections(self):
        """Раздел «списком» (две ступени подборок): фильтр — по задачам
        дочерних подборок, группы без подходящих задач скрываются."""
        root_sheet = Worksheet.objects.create(title='Часть 1', owner=self.owner)
        root = Collection.objects.create(
            worksheet=root_sheet, source=self.source, locator='p1', is_published=True)
        self.collection.parent = root
        self.collection.save(update_fields=['parent'])
        other_sheet = Worksheet.objects.create(title='Глава 2', owner=self.owner)
        Collection.objects.create(
            worksheet=other_sheet, source=self.source, parent=root, locator='g2',
            is_published=True)
        other = Task.objects.create(text_latex='Докажите неравенство.', created_by=self.owner)
        WorksheetItem.objects.create(worksheet=other_sheet, task=other, order=10)
        url = reverse('collection_detail', args=[root.pk])
        full = self.client.get(url)
        self.assertContains(full, 'Докажите неравенство')
        self.assertContains(full, f'href="?topic={self.square.pk}"')
        response = self.client.get(url, {'topic': self.square.pk})
        self.assertContains(response, 'x^2=4')
        self.assertNotContains(response, 'Докажите неравенство')
        self.assertNotContains(response, 'x+1=2')

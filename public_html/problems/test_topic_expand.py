"""Раскрытие подтем фильтра ``?topic=`` одним запросом — результат тот же,
что у рекурсивного обхода (аудит быстродействия 06.11.2026)."""
from django.test import TestCase

from problems.models import Topic
from problems.rubricator import expand_topic_ids


def naive_descendants(topic):
    """Прежний рекурсивный обход: запрос на каждый узел."""
    ids = [topic.pk]
    for child in topic.children.all():
        ids.extend(naive_descendants(child))
    return ids


class TopicExpandTests(TestCase):
    def setUp(self):
        # Два корня, три уровня, порядок подтем — не по id
        self.alg = Topic.objects.create(name='Алгебра (тест)', order=1)
        self.geo = Topic.objects.create(name='Геометрия (тест)', order=0)
        self.eq = Topic.objects.create(name='Уравнения', parent=self.alg, order=2)
        self.func = Topic.objects.create(name='Функции', parent=self.alg, order=1)
        self.linear = Topic.objects.create(name='Линейные', parent=self.eq, order=0)
        self.quad = Topic.objects.create(name='Квадратные', parent=self.eq, order=1)
        self.tri = Topic.objects.create(name='Треугольники', parent=self.geo, order=0)
        self.leaf = Topic.objects.create(name='Биквадратные', parent=self.quad, order=0)

    def test_descendants_match_recursive_walk(self):
        for topic in Topic.objects.all():
            with self.subTest(topic=topic.name):
                self.assertEqual(topic.descendants_ids(), naive_descendants(topic))

    def test_descendants_single_query(self):
        with self.assertNumQueries(1):
            ids = self.alg.descendants_ids()
        self.assertEqual(ids, [self.alg.pk, self.func.pk, self.eq.pk,
                               self.linear.pk, self.quad.pk, self.leaf.pk])

    def test_expand_matches_recursive_for_every_combination(self):
        topics = list(Topic.objects.all())
        cases = [[t] for t in topics] + [[self.alg, self.geo], [self.eq, self.linear],
                                         [self.leaf, self.alg]]
        for case in cases:
            expected = set()
            for topic in case:
                expected.update(naive_descendants(topic))
            with self.subTest(case=[t.name for t in case]):
                got = expand_topic_ids([str(t.pk) for t in case])
                self.assertEqual(sorted(got), sorted(expected))
                self.assertEqual(len(got), len(set(got)))

    def test_expand_single_query_for_root(self):
        with self.assertNumQueries(1):
            got = expand_topic_ids([str(self.alg.pk), str(self.geo.pk)])
        # Справочник рубрикатора уже засеян миграцией — сравниваем только
        # с деревом теста
        mine = naive_descendants(self.alg) + naive_descendants(self.geo)
        self.assertEqual(sorted(got), sorted(mine))

    def test_unknown_and_empty_ids(self):
        self.assertEqual(expand_topic_ids([]), [])
        self.assertEqual(expand_topic_ids(['', None, 'abc']), [])
        missing = str(Topic.objects.order_by('-pk').first().pk + 1000)
        self.assertEqual(expand_topic_ids([missing]), [])
        self.assertEqual(sorted(expand_topic_ids([missing, str(self.tri.pk)])),
                         [self.tri.pk])

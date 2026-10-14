"""Тег page_tools: ссылки-сегменты строки фильтров сохраняют остальные
GET-параметры и сбрасывают page (docs/PIPELINE.md, «Шапка страницы и фильтры»)."""
from urllib.parse import parse_qs

from django.http import QueryDict
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase

from problems.templatetags.page_tools import query_url, seg_links


def parse(url):
    """«?a=1&b=2» → {'a': ['1'], 'b': ['2']}."""
    assert url.startswith('?'), url
    return parse_qs(url[1:], keep_blank_values=True)


class QueryUrlTests(SimpleTestCase):
    def test_resets_page_and_replaces_value(self):
        params = QueryDict('grade=7&order=title&page=3')
        self.assertEqual(parse(query_url(params, {'grade': 8})),
                         {'grade': ['8'], 'order': ['title']})

    def test_none_and_empty_remove_key(self):
        params = QueryDict('grade=7&status=submitted&q=x')
        self.assertEqual(parse(query_url(params, {'grade': None})),
                         {'status': ['submitted'], 'q': ['x']})
        self.assertEqual(parse(query_url(params, {'status': ''})),
                         {'grade': ['7'], 'q': ['x']})

    def test_empty_result_is_bare_question_mark(self):
        params = QueryDict('grade=7&page=2')
        self.assertEqual(query_url(params, {'grade': None}), '?')

    def test_keeps_repeated_params(self):
        params = QueryDict('topic=3&topic=5&grade=7')
        self.assertEqual(parse(query_url(params, {'grade': 9})),
                         {'topic': ['3', '5'], 'grade': ['9']})

    def test_replaces_all_values_of_repeated_key(self):
        params = QueryDict('topic=3&topic=5')
        self.assertEqual(parse(query_url(params, {'topic': 8})),
                         {'topic': ['8']})

    def test_source_params_not_mutated(self):
        params = QueryDict('grade=7&page=2')
        query_url(params, {'grade': 8})
        self.assertEqual(params.urlencode(), 'grade=7&page=2')


class QuerySetTagTests(SimpleTestCase):
    def test_tag_uses_request_get(self):
        request = RequestFactory().get('/', {'topic': ['3', '5'], 'page': '2'})
        html = Template('{% load page_tools %}{% query_set grade=8 %}').render(
            Context({'request': request}))
        self.assertEqual(parse(html.replace('&amp;', '&')),
                         {'topic': ['3', '5'], 'grade': ['8']})


class SegLinksTests(SimpleTestCase):
    CHOICES = [(5, '5'), (8, '8'), (10, '10–11')]

    def items(self, query, *args, **kwargs):
        request = RequestFactory().get('/', query)
        return seg_links({'request': request}, *args, **kwargs)['items']

    def active(self, items):
        return [item['label'] for item in items if item['active']]

    def test_all_segment_first_and_active_without_param(self):
        items = self.items({'order': 'title'}, 'grade', self.CHOICES)
        self.assertEqual([item['label'] for item in items],
                         ['Все', '5', '8', '10–11'])
        self.assertEqual(self.active(items), ['Все'])
        self.assertEqual(parse(items[0]['url']), {'order': ['title']})
        self.assertEqual(parse(items[2]['url']),
                         {'order': ['title'], 'grade': ['8']})

    def test_active_from_get_param(self):
        items = self.items({'grade': '8', 'page': '4'}, 'grade', self.CHOICES)
        self.assertEqual(self.active(items), ['8'])
        self.assertNotIn('page', parse(items[1]['url']))

    def test_grade_11_alias_activates_10_11(self):
        items = self.items({'grade': '11'}, 'grade', self.CHOICES)
        self.assertEqual(self.active(items), ['10–11'])

    def test_default_when_param_missing(self):
        items = self.items({}, 'kind', [('ordinary', 'Обычные'),
                                        ('independent', 'Самостоятельные')],
                           default='ordinary')
        self.assertEqual(self.active(items), ['Обычные'])

    def test_explicit_current_overrides_get(self):
        items = self.items({'status': 'bogus'}, 'status',
                           [('submitted', 'На проверке')],
                           current='submitted')
        self.assertEqual(self.active(items), ['На проверке'])

    def test_all_label_none_omits_all_segment(self):
        items = self.items({}, 'grade', self.CHOICES, all_label=None)
        self.assertEqual([item['label'] for item in items], ['5', '8', '10–11'])
        self.assertEqual(self.active(items), [])

    def test_empty_choice_value_clears_param(self):
        items = self.items({'kind': 'ordinary'}, 'kind',
                           [('', 'Все работы'), ('ordinary', 'Обычные')],
                           all_label=None)
        self.assertEqual(items[0]['url'], '?')
        self.assertEqual(self.active(items), ['Обычные'])

    def test_rendered_markup(self):
        request = RequestFactory().get('/', {'grade': '8'})
        html = Template(
            "{% load page_tools %}{% seg_links 'grade' choices label='Класс' %}"
        ).render(Context({'request': request, 'choices': self.CHOICES}))
        self.assertInHTML('<a class="seg-item is-active" href="?grade=8" '
                          'aria-current="true">8</a>', html)
        self.assertIn('<nav class="seg" aria-label="Класс">', html)
        self.assertEqual(html.count('class="seg-item'), 4)

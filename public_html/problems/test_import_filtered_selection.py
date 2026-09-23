"""Массовый выбор не ограничивается страницей и сохраняет границы фильтра."""
from django.test import TestCase
from django.urls import reverse

from .models import Source, TextbookImportBatch, TextbookTaskDraft
from .tests import make_teacher
from .views import _textbook_collection_groups


class FilteredImportSelectionTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)
        self.batch = TextbookImportBatch.objects.create(
            title='Массовая сверка', source=Source.objects.create(title='Книга'),
            created_by=self.teacher)
        self.url = reverse('textbook_import_bulk', args=[self.batch.pk])

    def draft(self, key, **fields):
        defaults = dict(batch=self.batch, source_path=['Первый раздел'],
                        collection_key='first', text_latex='Условие')
        defaults.update(fields)
        return TextbookTaskDraft.objects.create(external_id=key, **defaults)

    def test_approval_spans_pages_and_respects_combined_filters(self):
        targets = [self.draft(str(i)) for i in range(55)]
        excluded = [
            self.draft('answer', author_answer_latex='$1$'),
            self.draft('editorial', answer_latex='$2$'),
            self.draft('subitem', subitems=[{'label': '1', 'text_latex': 'Пункт',
                                           'answer_latex': '$3$'}]),
            self.draft('section', source_path=['Другой раздел'], collection_key='other'),
            self.draft('conflict', status='conflict'),
            self.draft('imported', status='imported'),
        ]
        other_batch = TextbookImportBatch.objects.create(
            title='Другая партия', source=self.batch.source, created_by=self.teacher)
        excluded.append(self.draft('foreign', batch=other_batch))
        before = {d.pk: d.status for d in excluded}
        group = next(g for g in _textbook_collection_groups(self.batch)
                     if g['path'] == ['Первый раздел'])
        filters = {'section': group['token'], 'status': 'needs_review', 'answers': 'none'}
        response = self.client.get(reverse('textbook_import_detail', args=[self.batch.pk]), filters)
        self.assertEqual(len(response.context['page']), 50)
        self.assertEqual(response.context['filtered_selectable_count'], 55)
        self.assertContains(response, 'Выбрать все найденные (55)')
        response = self.client.post(self.url, {
            'selection_scope': 'filtered', 'filter_section': group['token'],
            'filter_status': 'needs_review', 'filter_answers': 'none',
            'status': 'approved', 'ids': [excluded[-1].pk],
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TextbookTaskDraft.objects.filter(
            pk__in=[d.pk for d in targets], status='approved',
            reviewed_by=self.teacher, reviewed_at__isnull=False).count(), 55)
        self.assertEqual(dict(TextbookTaskDraft.objects.filter(
            pk__in=before).values_list('pk', 'status')), before)

    def test_all_batch_selection_excludes_published_drafts(self):
        target = self.draft('review')
        published = self.draft('published', status='imported')
        self.client.post(self.url, {'selection_scope': 'filtered', 'status': 'approved'})
        target.refresh_from_db()
        published.refresh_from_db()
        self.assertEqual(target.status, 'approved')
        self.assertEqual(published.status, 'imported')
        self.assertIsNone(published.reviewed_at)

    def test_invalid_filter_never_expands_selection(self):
        target = self.draft('review')
        for field, value in [('filter_section', 'missing'), ('filter_status', 'missing'),
                             ('filter_answers', 'missing'), ('selection_scope', 'missing')]:
            with self.subTest(field=field):
                self.client.post(self.url, {'selection_scope': 'filtered',
                                            'status': 'approved', field: value})
                target.refresh_from_db()
                self.assertEqual(target.status, 'needs_review')
                self.assertIsNone(target.reviewed_at)

    def test_page_selection_only_changes_explicit_ids(self):
        first = self.draft('first')
        second = self.draft('second')
        self.client.post(self.url, {'ids': [first.pk], 'status': 'approved'})
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, 'approved')
        self.assertEqual(second.status, 'needs_review')

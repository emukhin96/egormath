"""Права, неизменяемая история, повторная доставка и ограничения журнала."""
import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import Profile
from assignments.models import Assignment, Submission, SubmissionPart
from assignments.views import _persist_answers
from independentworks.models import Work, Position, Candidate
from independentworks import services as iw
from problems.models import Task, TaskSubitem
from problems.tests import make_teacher, make_student
from worksheets.tests import make_worksheet
from worksheets.models import WorksheetItem
from .models import ActivityEvent, AnswerRevision
from .services import activity_timeline, answer_snapshot, format_span, record_revision, swap_marks, visibility_summary


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class AuditTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.other_teacher = make_teacher('other-teacher')
        self.other = make_student(self.other_teacher, 'other-student')
        self.sheet = make_worksheet(self.teacher)
        self.assignment = Assignment.objects.create(worksheet=self.sheet, student=self.student)
        self.task = Task.objects.create(text_latex='Вычислите', answer_mask='{{number: 4}}')
        WorksheetItem.objects.create(worksheet=self.sheet, task=self.task, order=1)
        self.work = Work.objects.create(owner=self.teacher, title='Работа')
        Candidate.objects.create(position=Position.objects.create(work=self.work), task=self.task)
        run = iw.prepare(self.work, self.teacher, [self.student.pk])
        iw.issue(run.pk)
        self.attempt = iw.start(run.attempts.get().pk)
        self.point = self.attempt.variant.points.get()
        self.client.force_login(self.student)

    def event(self, **kwargs):
        return {**dict(id=str(uuid.uuid4()), page=str(uuid.uuid4()), seq=0, kind='hidden',
                       blocked=False, at=timezone.now().isoformat(), elapsed=100), **kwargs}

    def post_events(self, rows, kind='assignment'):
        pk = self.assignment.pk if kind == 'assignment' else self.attempt.pk
        return self.client.post(reverse('workaudit:events', args=[kind, pk]),
                                data=json.dumps({'events': rows}), content_type='application/json')

    def test_delivery_duplicate_and_access(self):
        row = self.event()
        self.assertEqual(self.post_events([row, row]).status_code, 200)
        self.assertEqual(self.post_events([row]).status_code, 200)
        self.assertEqual(ActivityEvent.objects.count(), 1)
        self.assertEqual(self.post_events([self.event()], 'attempt').status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.post_events([row]).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertEqual(self.post_events([row]).status_code, 404)
        for kind, obj in [('assignment', self.assignment), ('attempt', self.attempt)]:
            url = reverse('workaudit:activity', args=[kind, obj.pk])
            self.assertEqual(self.client.get(url).status_code, 200)
            self.client.force_login(self.other_teacher)
            self.assertEqual(self.client.get(url).status_code, 404)
            self.client.force_login(self.student)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.client.force_login(self.teacher)

    def test_validation_rate_csrf_and_completion(self):
        row = self.event()
        for field, value in [('kind', 'key'), ('elapsed', -1), ('seq', True), ('blocked', 'yes'), ('page', 'bad'), ('at', 'not-a-date')]:
            self.assertEqual(self.post_events([dict(row, **{field: value})]).status_code, 400)
        self.assertEqual(self.post_events([row]*51).status_code, 400)
        self.assertEqual(self.post_events([]).status_code, 400)
        url = reverse('workaudit:events', args=['assignment', self.assignment.pk])
        self.assertEqual(self.client.post(url, 'x'*140000, content_type='application/json').status_code, 413)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.student)
        self.assertEqual(csrf_client.post(url, json.dumps({'events': [row]}), content_type='application/json').status_code, 403)
        for _ in range(4):
            self.assertEqual(self.post_events([self.event() for _ in range(50)]).status_code, 200)
        self.assertEqual(self.post_events([self.event() for _ in range(50)]).status_code, 429)
        self.assignment.status = Assignment.STATUS_SUBMITTED
        self.assignment.submitted_at = timezone.now()-timedelta(minutes=3)
        self.assignment.save()
        self.assertEqual(self.post_events([row]).status_code, 409)

    def test_late_batch_after_submit(self):
        row = self.event()
        self.assignment.status = Assignment.STATUS_SUBMITTED
        self.assignment.submitted_at = timezone.now()
        self.assignment.save()
        self.assertEqual(self.post_events([row]).status_code, 200)
        self.assertEqual(self.post_events([self.event()]).status_code, 200)
        self.assertEqual(ActivityEvent.objects.count(), 1)

    def test_assignment_history_changed_clear_and_rollback(self):
        payload = {f'task{self.task.pk}_s1': '4'}
        _persist_answers(self.assignment, payload)
        self.assertEqual(AnswerRevision.objects.count(), 1)
        _persist_answers(self.assignment, payload)
        self.assertEqual(AnswerRevision.objects.count(), 1)
        _persist_answers(self.assignment, {f'task{self.task.pk}_s1': ''})
        self.assertEqual(AnswerRevision.objects.count(), 2)
        self.assertEqual(AnswerRevision.objects.latest('pk').snapshot['answer_json'], {'s1': ''})
        with patch('workaudit.services.record_revision', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                _persist_answers(self.assignment, payload)
        self.assertEqual(Submission.objects.get(assignment=self.assignment).answer_json, {'s1': ''})
        self.assertEqual(AnswerRevision.objects.count(), 2)

    def test_subpart_and_existing_baseline(self):
        subitem = TaskSubitem.objects.create(task=self.task, order=1, text_latex='а', answer_mask='{{number: 3}}')
        submission = Submission.objects.create(assignment=self.assignment, task=self.task)
        part = SubmissionPart.objects.create(submission=submission, subitem=subitem, answer_json={'s1': '2'})
        _persist_answers(self.assignment, {f'task{self.task.pk}_sub{subitem.pk}_s1': '3'})
        revisions = AnswerRevision.objects.filter(part=part).order_by('pk')
        self.assertEqual(revisions.count(), 2)
        self.assertTrue(revisions[0].initial)
        self.assertEqual(revisions[0].snapshot['answer_json'], {'s1': '2'})
        self.assertFalse(revisions[1].initial)
        self.client.force_login(self.teacher)
        url = reverse('workaudit:history', args=['part', part.pk])
        self.assertContains(self.client.get(url), 'время ввода неизвестно')
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_independent_versions_conflict_and_rollback(self):
        answer = iw.save_answer(self.attempt.pk, self.point.pk, 0, {'s1': '4'})
        iw.save_answer(self.attempt.pk, self.point.pk, 1, {'s1': '4'})
        self.assertEqual(AnswerRevision.objects.filter(answer=answer).count(), 1)
        with self.assertRaises(iw.WorkError):
            iw.save_answer(self.attempt.pk, self.point.pk, 0, {'s1': '5'})
        with patch('workaudit.services.record_revision', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                iw.save_answer(self.attempt.pk, self.point.pk, 2, {'s1': '5'})
        answer.refresh_from_db()
        self.assertEqual(answer.version, 2)
        self.assertEqual(answer.values, {'s1': '4'})
        iw.save_answer(self.attempt.pk, self.point.pk, 2, {'s1': ''})
        self.assertEqual(AnswerRevision.objects.filter(answer=answer).count(), 2)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('workaudit:history', args=['answer', answer.pk])).status_code, 200)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(reverse('workaudit:history', args=['answer', answer.pk])).status_code, 404)

    def test_summary_tabs_missing_and_out_of_order(self):
        one, two = uuid.uuid4(), uuid.uuid4()
        def e(page, seq, kind, ms):
            return ActivityEvent(page_id=page, sequence=seq, kind=kind, elapsed_ms=ms)
        summary = visibility_summary([e(one, 1, 'visible', 10100), e(one, 0, 'hidden', 100),
                                      e(two, 0, 'hidden', 500), e(one, 2, 'hidden', 11000)])
        first = next(row for row in summary if row['page'] == str(one)[:8])
        self.assertEqual(first, {'page': str(one)[:8], 'seconds': 10, 'count': 2, 'unknown': 1})

    def test_timeline_intervals_tabs_and_short(self):
        one, two = uuid.uuid4(), uuid.uuid4()
        t0 = timezone.now()
        def e(page, seq, kind, ms, at, blocked=False):
            # Всё получено одной пачкой через минуту — лента должна идти по client_at
            return ActivityEvent(page_id=page, sequence=seq, kind=kind, elapsed_ms=ms, blocked=blocked,
                                 client_at=t0 + timedelta(seconds=at), received_at=t0 + timedelta(seconds=300))
        rows, summary = activity_timeline([
            e(one, 0, 'hidden', 100, 10), e(one, 1, 'visible', 100100, 110),      # уход на 100 с
            e(one, 2, 'copy', 120000, 130, blocked=True),
            e(one, 3, 'hidden', 130000, 140), e(one, 4, 'visible', 132000, 142),   # короткий, 2 с
            e(two, 0, 'hidden', 500, 200),                                         # вторая вкладка, не вернулся
            e(one, 5, 'hidden', 140000, 150), e(one, 6, 'hidden', 141000, 151),    # разорванная пара
        ], started_at=t0)
        self.assertEqual(summary['away'], 5)   # 100 с, 2 с, разорванная пара (2 строки), вторая вкладка
        self.assertEqual(summary['away_seconds'], 102)
        self.assertEqual(summary['away_max'], 100)
        self.assertEqual(summary['unknown'], 3)
        self.assertEqual((summary['copy'], summary['blocked'], summary['tabs'], summary['short']), (1, 1, 2, 1))
        self.assertEqual([r['at'] for r in rows], sorted((r['at'] for r in rows), reverse=True))
        first = next(r for r in rows if r['seconds'] == 100)
        self.assertEqual((first['tab'], first['offset'], first['short']), (1, 10, False))
        self.assertEqual(first['received'], t0 + timedelta(seconds=300))
        self.assertEqual([r['offset'] for r in rows], [200, 151, 150, 140, 130, 10])   # по client_at, не по пачке
        self.assertTrue(next(r for r in rows if r['tab'] == 2)['open_ended'])
        self.assertEqual(next(r for r in rows if r['kind'] == 'copy')['blocked'], True)
        self.assertEqual((format_span(40), format_span(252), format_span(3900)), ('40 с', '4 мин 12 с', '1 ч 05 мин'))

    def test_activity_panel_filters_and_raw(self):
        page = str(uuid.uuid4())
        def ev(**fields):
            row = self.event(); row.update(page=page, **fields); return row
        self.post_events([ev(seq=0, kind='hidden', elapsed=100), ev(seq=1, kind='visible', elapsed=30100),
                          ev(seq=2, kind='paste', elapsed=40000)])
        self.client.force_login(self.teacher)
        url = reverse('workaudit:activity', args=['assignment', self.assignment.pk])
        response = self.client.get(url)
        self.assertContains(response, 'Уходил со страницы 1 раз, всего 30 с')
        self.assertContains(response, 'ушёл со страницы на 30 с')
        self.assertContains(response, 'вставка ответа')
        self.assertNotContains(response, 'вкладка 1')
        away = self.client.get(url, {'show': 'away'})
        self.assertContains(away, 'ушёл со страницы на 30 с')
        self.assertNotContains(away, 'вставка ответа')
        raw = self.client.get(url, {'raw': '1'})
        self.assertContains(raw, 'Возврат на страницу')
        self.assertContains(raw, 'К ленте')

    def test_cleanup_and_page_size(self):
        obj = Submission.objects.create(assignment=self.assignment, task=self.task)
        AnswerRevision.objects.bulk_create([AnswerRevision(submission=obj, snapshot={'answer_json': {'s1': str(i)}}) for i in range(52)])
        old = AnswerRevision.objects.first()
        AnswerRevision.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=91))
        self.post_events([self.event()])
        ActivityEvent.objects.update(received_at=timezone.now()-timedelta(days=91))
        call_command('cleanup_work_activity', verbosity=0)
        self.assertEqual(AnswerRevision.objects.count(), 51)
        self.assertEqual(ActivityEvent.objects.count(), 0)
        self.assertTrue(Submission.objects.filter(pk=obj.pk).exists())
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('workaudit:history', args=['submission', obj.pk]))
        self.assertEqual(len(response.context['page']), 50)
        self.assertContains(response, 'Страница 1 из 2')
        self.assertEqual(response['Cache-Control'].find('no-store') >= 0, True)

    def test_settings_and_templates(self):
        self.client.force_login(self.teacher)
        url = reverse('workaudit:run_settings', args=[self.attempt.run_id])
        both = {'restrict_clipboard': 'on', 'swap_numbers': 'on'}
        self.assertEqual(self.client.post(url, {**both, 'exempt': [self.attempt.pk]}).status_code, 302)
        self.attempt.refresh_from_db()
        self.assertEqual((self.attempt.restrict_clipboard, self.attempt.swap_numbers), (False, False))
        # Настройки независимы: подмена без запрета и запрет без подмены
        self.client.post(url, {'swap_numbers': 'on'})
        self.attempt.refresh_from_db()
        self.assertEqual((self.attempt.restrict_clipboard, self.attempt.swap_numbers), (False, True))
        self.assertContains(self.client.get(reverse('independentworks:progress', args=[self.attempt.run_id])), 'name="swap_numbers" checked')
        self.assertEqual(self.client.post(url, {'restrict_clipboard': 'on'}).status_code, 302)
        self.attempt.refresh_from_db()
        self.assertEqual((self.attempt.restrict_clipboard, self.attempt.swap_numbers), (True, False))
        self.assertEqual(self.client.post(url, {'exempt': ['999999']}).status_code, 400)
        self.assertContains(self.client.get(reverse('independentworks:progress', args=[self.attempt.run_id])), 'Копирование и вставка')
        self.assertContains(self.client.get(reverse('review_assignment', args=[self.assignment.pk])), 'Активность ученика')
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(url, {}).status_code, 403)
        page = self.client.get(reverse('independentworks:attempt', args=[self.attempt.pk]))
        self.assertContains(page, 'data-restricted="1" data-swap="0"')
        self.assertContains(page, f'data-audit-statement="{self.point.label}"')
        self.assertContains(page, 'data-audit-answer')
        self.assignment.swap_numbers = True
        self.assignment.save(update_fields=['swap_numbers'])
        sheet = self.client.get(reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(sheet, 'data-restricted="0" data-swap="1"')
        # Формулы без дублей при копировании — на всех страницах
        self.assertContains(sheet, 'js/katex_copy.js')

    def test_copied_text_whole_statement_and_swap(self):
        """Копирование пишет текст и доли условий; целиком — пометка учителю."""
        page = str(uuid.uuid4())
        whole = self.event(page=page, seq=0, kind='copy', text='Вычислите $2^{3}+15$', swapped='Вычислите $2^{3}+17$',
                           statements=[{'label': '1', 'share': 96}])
        part = self.event(page=page, seq=1, kind='copy', text='Вычислите', statements=[{'label': '2а', 'share': 40}])
        legacy = self.event(page=page, seq=2, kind='copy')
        self.assertEqual(self.post_events([whole, part, legacy]).status_code, 200)
        events = {e.sequence: e for e in ActivityEvent.objects.all()}
        self.assertEqual((events[0].whole, events[1].whole, events[2].whole), (True, False, False))
        self.assertEqual(events[0].statements, [{'label': '1', 'share': 96}])
        self.assertEqual(events[2].text, '')
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('workaudit:activity', args=['assignment', self.assignment.pk]))
        self.assertContains(response, 'скопировал условие задачи 1 целиком')
        self.assertContains(response, 'скопировал часть условия задачи 2а (40%)')
        self.assertContains(response, 'условие целиком — 1')
        self.assertContains(response, 'Вычислите $2^{3}+<mark>17</mark>$')
        self.assertContains(response, 'копирование условия')
        review = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(review, 'копировал условие целиком')
        progress = self.client.get(reverse('worksheet_progress', args=[self.sheet.pk]))
        self.assertContains(progress, 'копировал условие целиком')

    def test_copied_text_validation_and_limit(self):
        for extra in [{'text': 5}, {'swapped': ['x']}, {'statements': 'all'}, {'statements': [{'label': '1'}]},
                      {'statements': [{'label': '1', 'share': 101}]}, {'statements': [{'label': 1, 'share': 50}]},
                      {'statements': [{'label': '1', 'share': 50}, {'label': 1}]}]:
            self.assertEqual(self.post_events([self.event(kind='copy', **extra)]).status_code, 400, extra)
        self.assertEqual(self.post_events([self.event(kind='copy', text='я' * 3000)]).status_code, 200)
        self.assertEqual(len(ActivityEvent.objects.get().text), 2000)
        # Выделение всей страницы большого листка: пакет не теряется, условия обрезаются
        many = [{'label': str(i), 'share': 100} for i in range(150)]
        self.assertEqual(self.post_events([self.event(kind='copy', text='всё', statements=many)]).status_code, 200)
        copied = ActivityEvent.objects.get(text='всё')
        self.assertEqual((len(copied.statements), copied.whole), (100, True))
        # Текст пишется только у копирования
        self.post_events([self.event(kind='paste', text='чужой буфер')])
        self.assertEqual(ActivityEvent.objects.get(kind='paste').text, '')

    def test_swap_marks_and_attempt_progress_flag(self):
        self.assertEqual(swap_marks('a=2, b=0,5', 'a=3, b=0,7'), 'a=<mark>3</mark>, b=<mark>0,7</mark>')
        self.assertEqual(swap_marks('<b>2</b>', '<b>2</b>'), '&lt;b&gt;2&lt;/b&gt;')
        self.assertEqual(swap_marks('12', '1 3'), '1 3')
        self.post_events([self.event(kind='copy', text='x', statements=[{'label': '1', 'share': 100}])], 'attempt')
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse('independentworks:progress', args=[self.attempt.run_id])), 'копировал условие целиком')
        self.assertContains(self.client.get(reverse('independentworks:attempt', args=[self.attempt.pk])), 'копировал условие целиком')

    def test_database_exclusive_targets(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnswerRevision.objects.create(snapshot={})

    def test_assignment_clipboard_forms_and_retention_filter(self):
        from assignments.forms import AssignmentSettingsForm, AssignmentCreateForm
        form = AssignmentSettingsForm({'swap_numbers': 'yes', 'restrict_clipboard': 'no', 'due_action': 'keep'}, recipients=[self.assignment])
        self.assertTrue(form.is_valid())
        self.assertEqual((form.changes()['swap_numbers'], form.changes()['restrict_clipboard']), (True, False))
        keep = AssignmentSettingsForm({'swap_numbers': '', 'due_action': 'keep'}, recipients=[self.assignment])
        self.assertTrue(keep.is_valid())
        self.assertNotIn('swap_numbers', keep.changes())
        self.assertEqual(keep.initial['swap_numbers'], 'no')
        creation = AssignmentCreateForm(teacher=self.teacher)
        self.assertFalse(creation.fields['restrict_clipboard'].initial)
        self.assertFalse(creation.fields['swap_numbers'].initial)
        row = self.event()
        self.post_events([row])
        ActivityEvent.objects.update(received_at=timezone.now()-timedelta(days=91))
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('workaudit:activity', args=['assignment', self.assignment.pk]))
        self.assertContains(response, 'За последние 90 дней событий нет')

    def test_events_before_start_and_after_expiry(self):
        self.attempt.started_at = None
        self.attempt.ends_at = None
        self.attempt.save()
        self.assertEqual(self.post_events([self.event()], 'attempt').status_code, 409)
        self.attempt.started_at = timezone.now()-timedelta(hours=1)
        self.attempt.ends_at = timezone.now()-timedelta(minutes=3)
        self.attempt.save()
        self.assertEqual(self.post_events([self.event()], 'attempt').status_code, 409)

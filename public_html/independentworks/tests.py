"""Сквозные проверки самостоятельных: время, изоляция, снимки и история."""
import io
import tempfile
from datetime import timedelta
from unittest.mock import patch
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import Profile
from problems.models import Task, TaskSubitem, TaskSource, Source, TaskImage
from .models import Work, Position, Candidate, Attempt, Answer, Asset, Family
from . import services as svc


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class IndependentWorkTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        settings = override_settings(MEDIA_ROOT=self.media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        User = get_user_model()
        self.teacher = User.objects.create_user('teacher')
        Profile.objects.create(user=self.teacher, role='teacher')
        self.student = User.objects.create_user('student')
        Profile.objects.create(user=self.student, teacher=self.teacher, role='student')
        self.other = User.objects.create_user('other')
        Profile.objects.create(user=self.other, role='student')
        self.work = Work.objects.create(owner=self.teacher, title='Уравнения')
        self.position = Position.objects.create(work=self.work)
        self.task = Task.objects.create(text_latex='Два плюс два?', answer_latex='SECRET_ANSWER', solution_latex='SECRET_SOLUTION', answer_mask='{{number: 4}}')
        self.candidate = Candidate.objects.create(position=self.position, task=self.task)

    def issued(self, **kwargs):
        run = svc.prepare(self.work, self.teacher, [self.student.pk], **kwargs)
        svc.issue(run.pk)
        return run.attempts.get()

    def begin(self, **kwargs):
        return svc.start(self.issued(**kwargs).pk)

    def url(self, name, *args):
        return reverse('independentworks:' + name, args=args)

    def test_idempotent_issue_start(self):
        a = self.issued()
        svc.issue(a.run_id)
        self.assertEqual(Attempt.objects.count(), 1)
        first, second = svc.start(a.pk), svc.start(a.pk)
        self.assertEqual(first.ends_at, second.ends_at)
        self.assertEqual(first.started_at, second.started_at)

    def test_snapshot_and_stale_preview(self):
        run = svc.prepare(self.work, self.teacher, [self.student.pk])
        self.task.text_latex = 'Изменено'
        self.task.save()
        with self.assertRaises(svc.WorkError):
            svc.issue(run.pk)
        a = self.issued()
        self.task.text_latex = 'Снова изменено'
        self.task.save()
        self.assertEqual(a.variant.points.get().snapshot['text'], 'Изменено')

    def test_deadline_closed_browser_and_not_started(self):
        now = timezone.now()
        a = self.issued(deadline=now + timedelta(minutes=3), duration=40)
        begun = svc.start(a.pk)
        self.assertEqual(begun.ends_at, a.run.deadline)
        with patch('independentworks.services.timezone.now', return_value=now + timedelta(minutes=4)):
            svc.finish_expired(begun)
            self.assertEqual(begun.submitted_at, a.run.deadline)
            with self.assertRaises(svc.WorkError):
                svc.save_answer(a.pk, a.variant.points.get().pk, 0, {'s1': '4'})
        another = self.issued(deadline=now + timedelta(minutes=2))
        with patch('independentworks.services.timezone.now', return_value=now + timedelta(minutes=4)):
            with self.assertRaises(svc.WorkError):
                svc.start(another.pk)
            self.assertIsNone(svc.result(another)['percent'])

    def test_versions_clear_and_no_check_in_save_response(self):
        a = self.begin()
        point = a.variant.points.get()
        self.client.force_login(self.student)
        response = self.client.post(self.url('save', a.pk, point.pk), {'version': 0, f'p{point.pk}_s1': '4'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {'version', 'saved_at', 'state', 'attempt_state'})
        self.assertEqual(Answer.objects.get().auto_check, 'ok')
        response = self.client.post(self.url('save', a.pk, point.pk), {'version': 0, f'p{point.pk}_s1': '5'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Answer.objects.get().values['s1'], '4')
        svc.save_answer(a.pk, point.pk, 1, {'s1': ''})
        self.assertEqual(Answer.objects.get().values, {'s1': ''})
        self.assertEqual(Answer.objects.get().auto_check, 'wrong')
        self.assertFalse(Answer.objects.get().pending)

    def test_disclosure_before_start_submit_and_manual_flags(self):
        a = self.issued(release_mode='auto', release_flags=['checks', 'answer', 'solution'])
        self.client.force_login(self.student)
        self.assertNotContains(self.client.get(self.url('attempt', a.pk)), self.task.text_latex)
        svc.start(a.pk)
        response = self.client.get(self.url('attempt', a.pk))
        self.assertContains(response, self.task.text_latex)
        self.assertNotContains(response, 'SECRET_ANSWER')
        self.assertNotContains(response, 'SECRET_SOLUTION')
        svc.submit(a.pk)
        self.assertContains(self.client.get(self.url('attempt', a.pk)), 'SECRET_ANSWER')
        a.published_at = timezone.now()
        a.release_flags = ['answer']
        a.save(update_fields=['published_at', 'release_flags'])
        response = self.client.get(self.url('attempt', a.pk))
        self.assertContains(response, 'SECRET_ANSWER')
        self.assertNotContains(response, 'SECRET_SOLUTION')
        self.assertNotContains(response, 'Зачтено')

    def test_foreign_attempt_point_and_teacher_routes(self):
        a = self.begin()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url('attempt', a.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url('start', a.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url('save', a.pk, a.variant.points.get().pk)).status_code, 404)
        self.client.force_login(self.student)
        b = self.issued()
        self.assertEqual(self.client.post(self.url('save', a.pk, b.variant.points.get().pk)).status_code, 404)
        for name in ['progress', 'export', 'preview']:
            self.assertEqual(self.client.get(self.url(name, a.run_id)).status_code, 403)

    def two_parts(self):
        return [TaskSubitem.objects.create(task=self.task, order=i, text_latex=str(i), answer_mask='{{number: ' + str(i) + '}}') for i in (2, 3)]

    def test_same_task_separate_positions_and_partial_credit(self):
        first, second = self.two_parts()
        self.candidate.subitem_ids = [first.pk]
        self.candidate.save()
        p = Position.objects.create(work=self.work, order=2)
        Candidate.objects.create(position=p, task=self.task, subitem_ids=[second.pk])
        a = self.begin()
        points = list(a.variant.points.all())
        self.assertEqual(len(points), 2)
        svc.save_answer(a.pk, points[0].pk, 0, {'s1': '2'})
        svc.save_answer(a.pk, points[1].pk, 0, {'s1': '3'})
        self.assertEqual(svc.result(a)['done'], 2)
        Answer.objects.filter(point=points[1]).update(grade='+-')
        self.assertEqual(svc.result(a)['done'], 1.75)
        self.assertEqual(svc.result(a)['percent'], 88)

    def test_duplicate_point_rejected(self):
        Candidate.objects.create(position=Position.objects.create(work=self.work, order=2), task=self.task)
        with self.assertRaises(svc.WorkError):
            self.issued()

    def test_mismatch_confirmation(self):
        self.two_parts()
        Candidate.objects.create(position=self.position, task=Task.objects.create(text_latex='Другой кандидат'))
        with self.assertRaises(svc.WorkError):
            self.issued()
        self.position.mismatch_confirmed = True
        self.position.confirmed_composition = svc.composition(self.position)
        self.position.save()
        self.issued()

    def test_correction_snapshot_only_error_history(self):
        self.two_parts()
        a = self.begin()
        p, q = list(a.variant.points.all())
        svc.save_answer(a.pk, p.pk, 0, {'s1': '2'})
        svc.save_answer(a.pk, q.pk, 0, {'s1': '4'})
        svc.submit(a.pk)
        a.refresh_from_db()
        self.task.text_latex = 'Условие изменено'
        self.task.save()
        run = svc.prepare(self.work, self.teacher, [self.student.pk], parent=a, kind='correction')
        svc.issue(run.pk)
        b = svc.start(run.attempts.get().pk)
        point = b.variant.points.get()
        self.assertEqual(point.source_key, q.source_key)
        self.assertEqual(point.snapshot, q.snapshot)
        svc.save_answer(b.pk, point.pk, 0, {'s1': '3'})
        self.assertEqual(svc.result(a)['done'], 1)
        self.assertEqual(svc.cumulative(a)['done'], 2)

    def test_retake_avoids_seen(self):
        Candidate.objects.create(position=self.position, task=Task.objects.create(text_latex='Аналог', answer_mask='{{number: 5}}'))
        a = self.begin()
        svc.submit(a.pk); a.refresh_from_db()
        run = svc.prepare(self.work, self.teacher, [self.student.pk], parent=a, kind='retake')
        self.assertNotEqual(run.plan['variants'][0][0]['source_key'], a.variant.points.get().source_key)

    def test_shortage_and_cap(self):
        run = svc.prepare(self.work, self.teacher, [self.student.pk, self.other.pk])
        with self.assertRaises(svc.WorkError):
            svc.issue(run.pk)
        svc.issue(run.pk, confirm=True)
        self.assertEqual(run.attempts.count(), 2)
        capped = svc.prepare(self.work, self.teacher, [self.student.pk, self.other.pk], max_variants=1)
        self.assertFalse(capped.plan['shortage'])
        svc.issue(capped.pk)
        self.assertEqual(capped.variants.count(), 1)

    def test_started_reassignment_forbidden(self):
        a = self.begin()
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(self.url('reassign', a.pk), {'variant': a.variant_id}).status_code, 409)

    def test_assets_private_and_independent(self):
        stream = io.BytesIO()
        Image.new('RGB', (10, 10)).save(stream, 'PNG')
        image = TaskImage.objects.create(task=self.task, image=ContentFile(stream.getvalue(), name='figure.png'))
        self.task.solution_latex = r'SECRET_SOLUTION \taskpic{1}'
        self.task.save()
        a = self.begin(release_mode='auto', release_flags=['solution'])
        asset = Asset.objects.get()
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url('asset', a.pk, asset.pk)).status_code, 404)
        image.image.delete(); image.delete()
        svc.submit(a.pk)
        response = self.client.get(self.url('asset', a.pk, asset.pk))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b''.join(response.streaming_content))

    def test_export_plain_text(self):
        self.student.first_name = '=1+1'; self.student.save()
        a = self.begin()
        self.client.force_login(self.teacher)
        response = self.client.get(self.url('export', a.run_id))
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(b''.join(response.streaming_content)))
        self.assertEqual(book.sheetnames, ['Сводка', 'Пункты'])
        self.assertEqual(book['Сводка']['A2'].data_type, 's')
        self.assertEqual(book['Сводка']['A2'].value, '=1+1')

    def test_pages_and_etag(self):
        self.client.force_login(self.teacher)
        run = svc.prepare(self.work, self.teacher, [self.student.pk])
        for name, args in [('catalog', []), ('create', []), ('edit', [self.work.pk]), ('pick', [self.position.pk]), ('prepare', [self.work.pk]), ('preview', [run.pk])]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(self.url(name, *args)).status_code, 200)
        svc.issue(run.pk)
        self.assertEqual(self.client.get(self.url('progress', run.pk)).status_code, 200)
        self.assertEqual(self.client.get(self.url('attempt', run.attempts.get().pk)).status_code, 200)
        response = self.client.get(self.url('progress', run.pk) + '?fragment=1')
        self.assertEqual(self.client.get(self.url('progress', run.pk) + '?fragment=1', HTTP_IF_NONE_MATCH=response['ETag']).status_code, 304)

    def test_pending_publication(self):
        self.task.answer_mask = ''; self.task.save()
        a = self.begin(); svc.submit(a.pk)
        self.client.force_login(self.teacher)
        self.client.post(self.url('publish', a.run_id), {'flags': ['checks']})
        self.client.force_login(self.student)
        self.assertContains(self.client.get(self.url('attempt', a.pk)), 'Задача на проверке')

    def test_feature_flag(self):
        self.client.force_login(self.teacher)
        with override_settings(INDEPENDENT_WORKS_ENABLED=False):
            self.assertEqual(self.client.get(self.url('catalog')).status_code, 404)

    def test_families_idempotent_and_pairs_separate(self):
        source = Source.objects.create(title='Зив')
        ids = []
        for v in range(1, 5):
            task = Task.objects.create(text_latex=f'Вариант {v}')
            ids.append(task.pk)
            TaskSource.objects.create(task=task, source=source, locator=f'sr/01/v{v}/3')
        bank = Source.objects.create(title='ФИПИ')
        for n in range(2):
            task = Task.objects.create(text_latex=f'Банк {n}')
            TaskSource.objects.create(task=task, source=bank, locator=f'2.1.{n}', source_path=['№2', 'Прототип 2.1', 'Аналоги'])
        from .analogs import sync_families
        sync_families(); sync_families()
        self.assertEqual(Family.objects.count(), 3)
        self.assertEqual(set(Task.objects.get(pk=ids[0]).analog_families.get().tasks.values_list('pk', flat=True)), set(ids[:2]))
        self.assertFalse(Task.objects.get(pk=ids[0]).analog_families.filter(tasks=ids[2]).exists())


    def test_block_candidates_remain_coherent(self):
        from problems.models import TaskBlock
        self.candidate.delete()
        source = Source.objects.create(title='Общие условия')
        blocks = []
        for variant in range(2):
            block = TaskBlock.objects.create(source=source, key=str(variant), title='Блок', size=5)
            members = [Task.objects.create(block=block, block_position=i, text_latex=f'Общее условие {variant}. Вопрос {i}.', answer_mask='{{number: 4}}') for i in range(1, 6)]
            svc.add_candidate(self.position, members[0])
            blocks.append({t.pk for t in members})
        self.assertEqual(self.work.positions.count(), 5)
        variants, shortage, _ = svc.generate(svc.material(self.work), 2, 'block')
        self.assertFalse(shortage)
        for points in variants:
            ids = {int(p['source_key'][1:]) for p in points}
            self.assertIn(ids, blocks)
        self.assertNotEqual(variants[0], variants[1])

    def test_oge_prototype_sections_do_not_merge(self):
        from .analogs import sync_families
        source = Source.objects.create(title='ФИПИ ОГЭ')
        tasks = []
        for prototype in (1, 2):
            for index, section in enumerate(('Прототипы', 'Аналоги')):
                task = Task.objects.create(text_latex=f'{prototype}/{index}')
                TaskSource.objects.create(task=task, source=source, locator=f'6.{prototype}.{index}', source_path=['№6', section])
                tasks.append(task)
        manual = Family.objects.create(key='manual:test', title='Ручная связь')
        manual.tasks.add(tasks[0], tasks[2])
        sync_families()
        sync_families()
        self.assertEqual(Family.objects.filter(origin='source').count(), 2)
        self.assertEqual(Family.objects.get(key=f'bank:{source.pk}:6.1').tasks.count(), 2)
        self.assertEqual(manual.tasks.count(), 2)

    def test_unpublished_correction_does_not_reveal_cumulative(self):
        a = self.begin(release_mode='auto', release_flags=['checks'])
        svc.submit(a.pk)
        a.refresh_from_db()
        run = svc.prepare(self.work, self.teacher, [self.student.pk], parent=a, kind='correction')
        svc.issue(run.pk)
        child = svc.start(run.attempts.get().pk)
        svc.save_answer(child.pk, child.variant.points.get().pk, 0, {'s1': '4'})
        svc.submit(child.pk)
        self.assertEqual(svc.cumulative(a)['percent'], 100)
        self.assertEqual(svc.cumulative(a, student_view=True)['percent'], 0)
        Attempt.objects.filter(pk=child.pk).update(published_at=timezone.now(), release_flags=['checks'])
        self.assertEqual(svc.cumulative(a, student_view=True)['percent'], 100)

    def test_manual_analog_finishes_in_normal_editor(self):
        self.client.force_login(self.teacher)
        response = self.client.post(self.url('create_analog', self.position.pk, self.task.pk))
        self.assertEqual(response.status_code, 302)
        task = Task.objects.exclude(pk=self.task.pk).get()
        self.assertIsNone(task.variant_of_id)
        self.assertEqual(self.position.candidates.count(), 1)
        editor = self.client.get(response.url)
        self.assertContains(editor, 'Добавить сохранённый аналог в самостоятельную')
        response = self.client.post(self.url('finish_analog', self.position.pk, task.pk))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.position.candidates.count(), 2)
        self.assertEqual(set(task.analog_families.get().tasks.values_list('pk', flat=True)), {task.pk, self.task.pk})

    def test_analog_from_worksheet_local_variant(self):
        local = self.task.make_variant(self.teacher)
        Candidate.objects.create(position=self.position, task=local)
        self.client.force_login(self.teacher)
        response = self.client.post(self.url('create_analog', self.position.pk, local.pk))
        self.assertEqual(response.status_code, 302)
        another = self.task.make_variant(self.teacher)
        self.assertEqual(self.client.post(self.url('create_analog', self.position.pk, another.pk)).status_code, 404)

    def test_photo_ownership_and_deadline(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import Photo
        a = self.begin()
        p = a.variant.points.get()
        data = io.BytesIO()
        Image.new('RGB', (8, 8)).save(data, format='PNG')
        self.client.force_login(self.student)
        response = self.client.post(self.url('upload_photo', a.pk, p.pk), {'photo': SimpleUploadedFile('test.png', data.getvalue(), content_type='image/png')})
        self.assertEqual(response.status_code, 302)
        photo = Photo.objects.get()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url('photo', photo.pk)).status_code, 404)
        self.client.force_login(self.student)
        with patch('independentworks.models.timezone.now', return_value=a.ends_at):
            self.assertEqual(self.client.post(self.url('delete_photo', photo.pk)).status_code, 409)
            response = self.client.post(self.url('upload_photo', a.pk, p.pk), {'photo': SimpleUploadedFile('test.png', data.getvalue(), content_type='image/png')})
            self.assertEqual(response.status_code, 409)
        self.assertEqual(Photo.objects.count(), 1)


    def test_save_rechecks_time_after_validation(self):
        from assignments.checks import check_mask
        a = self.begin()
        point = a.variant.points.get()
        clock = [a.started_at]
        def validate(spec, values):
            checked = check_mask(spec, values)
            clock[0] = a.ends_at
            return checked
        with patch('independentworks.services.timezone.now', side_effect=lambda: clock[0]):
            with patch('independentworks.services.check_mask', side_effect=validate):
                with self.assertRaises(svc.WorkError):
                    svc.save_answer(a.pk, point.pk, 0, {'s1': '4'})
        self.assertFalse(a.answers.exists())

    def test_shared_masks_through_save_endpoint(self):
        from assignments.checks import parse_mask
        cases = [
            ('number', '4', '4'), ('digits', '234', '234'),
            ('decimal', '-0,5', '-0,5'), ('ratio', '1:2', '1:2'),
            ('proportion', '1:2', '1:2'), ('simplify', 'x+1', 'x+1'),
            ('factor', '(x-1)(x+1)', '(x-1)(x+1)'),
            ('equation', 'x=2', 'x=2'), ('set', '-3; 3', '-3; 3'),
            ('pair', '(3; -4)', '(3; -4)'), ('range', '(-2; 3]', '(-2; 3]'),
            ('choice', 'a|*b', 'b'), ('order', 'a|b|c', '0|1|2'),
        ]
        self.client.force_login(self.student)
        for kind, reference, value in cases:
            with self.subTest(kind=kind):
                self.task.answer_mask = '{{' + kind + ': ' + reference + '}}'
                self.task.save()
                a = self.begin()
                p = a.variant.points.get()
                data = {'version': 0, f'p{p.pk}_s1': value}
                if kind == 'order':
                    tokens = parse_mask(p.snapshot['mask']).slots[0].order_tokens(f'p{p.pk}')
                    data = {'version': 0, **{f'p{p.pk}_s1_{i}': tokens[i] for i in range(3)}}
                response = self.client.post(self.url('save', a.pk, p.pk), data)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(a.answers.get().auto_check, 'ok')
                self.assertNotIn('checks', response.json())


from concurrent.futures import ThreadPoolExecutor
from django.db import connections, close_old_connections
from django.test import TransactionTestCase, skipUnlessDBFeature


@skipUnlessDBFeature('has_select_for_update')
@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class ConcurrentWorkTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.teacher = User.objects.create_user('load_teacher')
        work = Work.objects.create(owner=self.teacher, title='Нагрузка')
        position = Position.objects.create(work=work)
        task = Task.objects.create(text_latex='Два плюс два', answer_mask='{{number: 4}}')
        Candidate.objects.create(position=position, task=task)
        User.objects.bulk_create([User(username=f'load_{i}') for i in range(30)])
        self.students = list(User.objects.filter(username__regex=r'^load_[0-9]+$'))
        self.run = svc.prepare(work, self.teacher, [u.pk for u in self.students], max_variants=1)
        svc.issue(self.run.pk)
        self.ids = list(self.run.attempts.values_list('pk', flat=True))
        self.point_id = self.run.variants.get().points.get().pk

    def test_30_students_save_with_monitoring(self):
        def student(attempt_id):
            close_old_connections()
            try:
                svc.start(attempt_id)
                for version in range(3):
                    svc.save_answer(attempt_id, self.point_id, version, {'s1': str(version + 2)})
                svc.submit(attempt_id)
                return attempt_id
            finally:
                connections.close_all()
        def monitor():
            close_old_connections()
            try:
                from .views import progress_context
                for _ in range(5):
                    self.assertEqual(len(progress_context(self.run)['people']), 30)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=31) as pool:
            watching = pool.submit(monitor)
            results = list(pool.map(student, self.ids))
            watching.result()
        self.assertEqual(len(results), 30)
        self.assertEqual(Answer.objects.filter(attempt__run=self.run, version=3, auto_check='ok').count(), 30)
        self.assertEqual(self.run.attempts.filter(submitted_at__isnull=False).count(), 30)

    def test_parallel_start_and_version_conflict(self):
        attempt_id = self.ids[0]
        def begin(_):
            close_old_connections()
            try:
                a = svc.start(attempt_id)
                return a.started_at, a.ends_at
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=8) as pool:
            starts = list(pool.map(begin, range(8)))
        self.assertEqual(len(set(starts)), 1)
        def save(_):
            close_old_connections()
            try:
                svc.save_answer(attempt_id, self.point_id, 0, {'s1': '4'})
                return 'saved'
            except svc.WorkError:
                return 'conflict'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(save, range(8)))
        self.assertEqual(results.count('saved'), 1)
        self.assertEqual(results.count('conflict'), 7)

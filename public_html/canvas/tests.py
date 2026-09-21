"""Права, лимиты и заморозка страниц холста."""
import json

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Profile
from assignments.models import Assignment
from assignments.progress import answer_versions
from problems.models import Task
from problems.tests import make_student, make_teacher
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet

from .models import CanvasPage


def stroke(element_id='a1', color='#1d4ed8'):
    return {'id': element_id, 't': 'path', 'c': color, 'w': 4,
            'p': [[100, 100], [120, 110], [140, 130]]}


class CanvasBase(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.worksheet = make_worksheet(self.teacher)
        self.task = Task.objects.create(text_latex='Постройте график')
        self.item = WorksheetItem.objects.create(worksheet=self.worksheet, task=self.task, order=1)
        self.assignment = Assignment.objects.create(
            worksheet=self.worksheet, student=self.student, assigned_by=self.teacher)

    def url(self, name, number=None):
        args = [self.assignment.pk, self.task.pk]
        if number is not None:
            args.append(number)
        return reverse(f'canvas:{name}', args=args)

    def save(self, number=1, elements=None, layer='student', version=0, **extra):
        body = {'layer': layer, 'elements': elements if elements is not None else [stroke()],
                'background': 'grid', 'version': version}
        body.update(extra)
        return self.client.post(self.url('save', number), data=json.dumps(body),
                                content_type='application/json')

    def submit(self):
        self.client.force_login(self.student)
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        self.assignment.refresh_from_db()


class StudentCanvasTests(CanvasBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.student)

    def test_save_creates_submission_and_page(self):
        response = self.save()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['version'], 1)
        page = CanvasPage.objects.get()
        self.assertEqual(page.submission.task, self.task)
        self.assertEqual(page.student_elements[0]['id'], 'a1')
        self.assertEqual(page.created_by_role, 'student')
        data = self.client.get(self.url('pages')).json()
        self.assertEqual(len(data['pages']), 1)
        self.assertEqual(data['layer'], 'student')
        # До возврата слой учителя ученику не отдаётся вовсе
        self.assertNotIn('teacher', data['pages'][0])
        self.assertFalse(data['show_teacher_layer'])

    def test_schema_validation(self):
        bad = [
            [{'id': 'x', 't': 'text', 'c': '#000000', 'w': 2, 'p': [[1, 1]]}],
            [{'id': 'x', 't': 'path', 'c': 'javascript:alert(1)', 'w': 2, 'p': [[1, 1]]}],
            [{'id': 'x', 't': 'path', 'c': '#000000', 'w': 2, 'p': [['1', 1]]}],
            [{'id': 'x', 't': 'line', 'c': '#000000', 'w': 2, 'p': [[1, 1]]}],
            [{'id': 'x', 't': 'fn', 'k': 'sin', 'c': '#000000', 'w': 2, 'p': [[1, 1], [2, 2]]}],
            [{'id': 'x', 't': 'path', 'c': '#000000', 'w': 2, 'p': [[5000, 1]]}],
            [stroke('same'), stroke('same')],
            [stroke(f'e{i}') for i in range(CanvasPage.MAX_ELEMENTS + 1)],
        ]
        for elements in bad:
            self.assertEqual(self.save(elements=elements).status_code, 400, elements[0])
        self.assertFalse(CanvasPage.objects.exists())
        self.assertEqual(self.save(background='paper').status_code, 400)

    def test_extra_keys_dropped_and_fn_accepted(self):
        elements = [{'id': 'f1', 't': 'fn', 'k': 'parabola', 'c': '#1D4ED8', 'w': 2,
                     'p': [[500, 375], [525, 350]], 'onclick': 'x', 'g': 'grp1'}]
        self.assertEqual(self.save(elements=elements, background='plane',
                                   background_options={'cell': 50, 'origin': 'bottom_left'}).status_code, 200)
        page = CanvasPage.objects.get()
        self.assertEqual(page.student_elements, [{'id': 'f1', 't': 'fn', 'c': '#1d4ed8', 'w': 2,
                                                  'p': [[500, 375], [525, 350]], 'g': 'grp1', 'k': 'parabola'}])
        self.assertEqual(page.background_options, {'cell': 50, 'origin': 'bottom_left'})

    def test_version_conflict(self):
        self.assertEqual(self.save().status_code, 200)
        response = self.save(elements=[stroke('b2')], version=0)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['version'], 1)
        self.assertEqual(response.json()['elements'][0]['id'], 'a1')
        self.assertEqual(self.save(elements=[stroke('b2')], version=1).status_code, 200)

    def test_square_page_options_survive_background_changes(self):
        for version, background in enumerate(('plane', 'blank', 'grid')):
            response = self.save(version=version, background=background,
                                 background_options={'square': True, 'cell': 25, 'origin': 'center'})
            self.assertEqual(response.status_code, 200)
            page = CanvasPage.objects.get()
            self.assertTrue(page.background_options['square'])
        self.assertEqual(self.save(version=3, background_options={'square': 'yes'}).status_code, 400)

    def test_legacy_page_can_draw_at_top_of_square_view(self):
        element = stroke()
        element['p'] = [[0, -250], [10, -240]]
        self.assertEqual(self.save(elements=[element]).status_code, 200)

    def test_student_cannot_touch_teacher_layer(self):
        self.assertEqual(self.save(layer='teacher').status_code, 403)

    def test_page_order_and_limits(self):
        self.assertEqual(self.save(number=3).status_code, 409)
        for number in range(1, CanvasPage.STUDENT_PAGE_LIMIT + 1):
            self.assertEqual(self.save(number=number).status_code, 200)
        self.assertEqual(self.save(number=CanvasPage.STUDENT_PAGE_LIMIT + 1).status_code, 403)

    def test_delete_only_empty_last_page(self):
        self.save(number=1)
        self.save(number=2, elements=[])
        self.assertEqual(self.client.post(self.url('delete', 1)).status_code, 409)
        self.assertEqual(self.client.post(self.url('delete', 2)).status_code, 200)
        self.assertEqual(CanvasPage.objects.count(), 1)

    def test_last_page_can_be_deleted_after_clear(self):
        self.save()
        self.assertEqual(self.save(elements=[], version=1).status_code, 200)
        self.assertEqual(self.client.post(self.url('delete', 1)).status_code, 200)
        self.assertFalse(CanvasPage.objects.exists())

    def test_hidden_task_rejected(self):
        self.save()
        self.assignment.hidden_items.add(self.item)
        self.assertEqual(self.save().status_code, 404)
        self.assertEqual(self.client.get(self.url('pages')).status_code, 404)
        self.assertEqual(self.client.post(self.url('delete', 1)).status_code, 404)

    def test_malformed_values_return_validation_error(self):
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=value):
                element = stroke()
                element['p'][0][0] = value
                self.assertEqual(self.save(elements=[element]).status_code, 400)
                self.assertEqual(self.save(version=value).status_code, 400)
        for value in ([], {}):
            with self.subTest(value=value):
                element = stroke()
                element['t'] = value
                self.assertEqual(self.save(elements=[element]).status_code, 400)
                self.assertEqual(self.save(background=value).status_code, 400)
        self.assertFalse(CanvasPage.objects.exists())

    def test_live_signature_changes_after_save(self):
        before = answer_versions(self.assignment)
        self.save()
        self.assertNotEqual(before, answer_versions(self.assignment))

    def test_only_nonempty_student_layer_counts_as_answer(self):
        detail = reverse('assignment_detail', args=[self.assignment.pk])
        self.save(elements=[])
        self.assertEqual(self.client.get(detail).context['answered_count'], 0)
        self.save(version=1)
        self.assertEqual(self.client.get(detail).context['answered_count'], 1)
        self.save(elements=[], version=2)
        page = CanvasPage.objects.get()
        page.teacher_elements = [stroke('teacher')]
        page.save()
        self.assertEqual(self.client.get(detail).context['answered_count'], 0)

    def test_payload_too_large(self):
        big = [{'id': f'p{i}', 't': 'path', 'c': '#000000', 'w': 2,
                'p': [[j % 1000, (j * 7) % 750] for j in range(CanvasPage.MAX_POINTS)]}
               for i in range(20)]
        self.assertEqual(self.save(elements=big).status_code, 413)
        self.assertFalse(CanvasPage.objects.exists())

    @override_settings(CANVAS_ENABLED=False)
    def test_disabled_flag(self):
        self.assertEqual(self.save().status_code, 503)
        self.assertEqual(self.client.get(self.url('pages')).status_code, 503)
        response = self.client.get(reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertNotContains(response, 'data-canvas')


class SubmitAndTeacherTests(CanvasBase):
    def test_teacher_only_after_submit(self):
        self.client.force_login(self.student)
        self.save()
        self.client.force_login(self.teacher)
        self.assertEqual(self.save(layer='teacher', elements=[stroke('t1', '#dc2626')]).status_code, 403)
        data = self.client.get(self.url('pages')).json()
        self.assertIsNone(data['layer'])
        self.assertIn('teacher', data['pages'][0])

        self.submit()
        self.assertEqual(self.assignment.status, Assignment.STATUS_SUBMITTED)
        page = CanvasPage.objects.get()
        self.assertIsNotNone(page.locked_at)
        # Ученик больше не пишет, учитель — пишет
        self.assertEqual(self.save(elements=[stroke('b2')], version=1).status_code, 403)
        self.client.force_login(self.teacher)
        response = self.save(layer='teacher', elements=[stroke('t1', '#dc2626')])
        self.assertEqual(response.status_code, 200)
        page.refresh_from_db()
        self.assertEqual(page.teacher_by, self.teacher)
        self.assertEqual(page.student_elements[0]['id'], 'a1')
        self.assertEqual(page.teacher_elements[0]['id'], 't1')
        self.assertEqual(self.save(layer='student', version=1).status_code, 403)

    def test_background_belongs_to_page_creator(self):
        self.client.force_login(self.student)
        self.save(background='plane', background_options={'cell': 50, 'origin': 'center', 'square': True})
        self.submit()
        self.client.force_login(self.teacher)
        # Учитель шлёт другой фон (старый клиент или прямой POST) — фон ученика не меняется
        response = self.save(layer='teacher', background='blank', background_options={})
        self.assertEqual(response.status_code, 200)
        page = CanvasPage.objects.get()
        self.assertEqual(page.background, 'plane')
        self.assertEqual(page.background_options, {'cell': 50, 'origin': 'center', 'square': True})
        # На своей странице учитель фон задаёт
        self.assertEqual(self.save(number=2, layer='teacher', background='grid_large').status_code, 200)
        self.assertEqual(CanvasPage.objects.get(number=2).background, 'grid_large')

    def test_legacy_plane_keeps_small_cell(self):
        """Старая страница без cell сохраняется с мелкой клеткой — как её рисует клиент."""
        self.client.force_login(self.student)
        self.assertEqual(self.save(background='plane', background_options={}).status_code, 200)
        self.assertEqual(CanvasPage.objects.get().background_options, {'cell': 25, 'origin': 'center'})

    def test_teacher_pages_limit_and_role(self):
        self.submit()
        self.client.force_login(self.teacher)
        for number in range(1, CanvasPage.TEACHER_PAGE_LIMIT + 1):
            self.assertEqual(self.save(number=number, layer='teacher').status_code, 200)
        self.assertEqual(self.save(number=CanvasPage.TEACHER_PAGE_LIMIT + 1, layer='teacher').status_code, 403)
        self.assertEqual(CanvasPage.objects.filter(created_by_role='teacher').count(), CanvasPage.TEACHER_PAGE_LIMIT)

    def test_returned_work_continues_on_new_page(self):
        self.client.force_login(self.student)
        self.save()
        self.submit()
        self.client.force_login(self.teacher)
        self.save(layer='teacher', elements=[stroke('t1', '#dc2626')])
        self.client.post(reverse('save_review', args=[self.assignment.pk]), {'action': 'return'})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_RETURNED)

        self.client.force_login(self.student)
        data = self.client.get(self.url('pages')).json()
        self.assertTrue(data['show_teacher_layer'])
        self.assertTrue(data['pages'][0]['locked'])
        self.assertEqual(data['pages'][0]['teacher']['elements'][0]['id'], 't1')
        # Замороженная страница закрыта, новая — открыта и не считается в лимит
        self.assertEqual(self.save(number=1, version=1).status_code, 403)
        self.assertEqual(self.save(number=2).status_code, 200)
        # Учитель во время доработки только смотрит
        self.client.force_login(self.teacher)
        self.assertEqual(self.save(number=1, layer='teacher', version=1).status_code, 403)

    def test_teacher_page_stays_locked_after_return(self):
        self.submit()
        self.client.force_login(self.teacher)
        self.assertEqual(self.save(layer='teacher').status_code, 200)
        self.client.post(reverse('save_review', args=[self.assignment.pk]), {'action': 'return'})
        self.client.force_login(self.student)
        self.assertTrue(self.client.get(self.url('pages')).json()['pages'][0]['locked'])
        self.assertEqual(self.save(number=1).status_code, 403)
        self.assertEqual(self.save(number=2).status_code, 200)

    def test_foreign_teacher_and_student(self):
        other_teacher = make_teacher(username='other_teacher')
        self.client.force_login(other_teacher)
        self.assertEqual(self.client.get(self.url('pages')).status_code, 404)
        other_student = make_student(self.teacher, username='other_student')
        self.client.force_login(other_student)
        self.assertEqual(self.client.get(self.url('pages')).status_code, 404)

    def test_pages_rendered_in_templates(self):
        self.client.force_login(self.student)
        self.save()
        response = self.client.get(reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, 'data-canvas')
        self.assertContains(response, 'data-pages="1"')
        self.submit()
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(response, 'data-role="teacher"')
        self.assertContains(response, 'toggle-canvas')
        response = self.client.get(reverse('assignment_live', args=[self.assignment.pk]))
        self.assertContains(response, 'data-role=\\"viewer\\"')

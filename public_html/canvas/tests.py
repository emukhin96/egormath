"""Права, лимиты и заморозка страниц холста."""
import json
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Profile
from assignments.models import Assignment
from assignments.progress import answer_versions
from django.core.files.base import ContentFile

from problems.models import Task, TaskImage
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
        # Слой учителя отдаётся ученику всегда — учитель может писать во время работы
        self.assertEqual(data['pages'][0]['teacher'], {'elements': [], 'version': 0})
        self.assertTrue(data['show_teacher_layer'])
        self.assertTrue(data['can_add_pages'])

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
    def test_teacher_writes_while_student_works(self):
        """Слой учителя открыт и до отправки; слои не мешают друг другу."""
        self.client.force_login(self.student)
        self.save(background='plane', background_options={'cell': 50, 'origin': 'center', 'square': True})
        self.client.force_login(self.teacher)
        data = self.client.get(self.url('pages')).json()
        self.assertEqual(data['layer'], 'teacher')
        self.assertFalse(data['can_add_pages'])
        response = self.save(layer='teacher', elements=[stroke('t1', '#dc2626')], background='blank')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['other_version'], 1)
        page = CanvasPage.objects.get()
        self.assertEqual(page.teacher_elements[0]['id'], 't1')
        self.assertEqual(page.student_elements[0]['id'], 'a1')
        # фон остался ученический: чужой слой его не трогает
        self.assertEqual(page.background, 'plane')
        self.assertEqual(page.background_options['cell'], 50)
        # свои страницы учитель до отправки не добавляет
        self.assertEqual(self.save(number=2, layer='teacher').status_code, 403)
        # ученик видит пометку сразу, в статусе «Выдано»
        self.client.force_login(self.student)
        data = self.client.get(self.url('pages')).json()
        self.assertTrue(data['show_teacher_layer'])
        self.assertEqual(data['pages'][0]['teacher']['elements'][0]['id'], 't1')
        # и продолжает писать свой слой, не затирая учительский
        response = self.save(elements=[stroke('a1'), stroke('a2')], version=1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['other_version'], 1)
        page.refresh_from_db()
        self.assertEqual(len(page.student_elements), 2)
        self.assertEqual(page.teacher_elements[0]['id'], 't1')

        self.submit()
        self.assertEqual(self.assignment.status, Assignment.STATUS_SUBMITTED)
        page.refresh_from_db()
        self.assertIsNotNone(page.locked_at)
        # Ученик больше не пишет, учитель — пишет и может добавить свою страницу
        self.assertEqual(self.save(elements=[stroke('b2')], version=2).status_code, 403)
        self.client.force_login(self.teacher)
        self.assertTrue(self.client.get(self.url('pages')).json()['can_add_pages'])
        response = self.save(layer='teacher', elements=[stroke('t1', '#dc2626'), stroke('t2')], version=1)
        self.assertEqual(response.status_code, 200)
        page.refresh_from_db()
        self.assertEqual(page.teacher_by, self.teacher)
        self.assertEqual(len(page.student_elements), 2)
        self.assertEqual(len(page.teacher_elements), 2)
        self.assertEqual(self.save(layer='student', version=2).status_code, 403)

    def test_pages_etag(self):
        self.client.force_login(self.student)
        self.save()
        response = self.client.get(self.url('pages'))
        etag = response['ETag']
        self.assertEqual(self.client.get(self.url('pages'), HTTP_IF_NONE_MATCH=etag).status_code, 304)
        self.client.force_login(self.teacher)
        self.save(layer='teacher')
        self.client.force_login(self.student)
        response = self.client.get(self.url('pages'), HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response['ETag'], etag)
        # у учителя своя подпись: другой слой и другие права
        self.client.force_login(self.teacher)
        self.assertNotEqual(self.client.get(self.url('pages'))['ETag'], response['ETag'])

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
        # Учитель во время доработки пишет на любой странице, но свои не добавляет
        self.client.force_login(self.teacher)
        self.assertEqual(self.save(number=1, layer='teacher', version=1).status_code, 200)
        self.assertEqual(self.save(number=2, layer='teacher', version=0).status_code, 200)
        self.assertEqual(self.save(number=3, layer='teacher').status_code, 403)

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


def make_image(task, name='fig.png'):
    """Картинка задачи: PNG через PIL (save() сжимает растровые файлы) или PDF-заглушка."""
    import io
    from PIL import Image
    image = TaskImage(task=task, order=1)
    if name.endswith('.pdf'):
        image.image.save(name, ContentFile(b'%PDF-1.4'), save=True)
    else:
        buf = io.BytesIO()
        Image.new('RGB', (40, 30), 'white').save(buf, format='PNG')
        image.image.save(name, ContentFile(buf.getvalue()), save=True)
    return image


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ImageElementTests(CanvasBase):
    """Иллюстрация задачи на доске: только своя, только растровая."""

    def setUp(self):
        super().setUp()
        self.image = make_image(self.task)
        self.pdf = make_image(self.task, 'fig.pdf')
        self.foreign = make_image(Task.objects.create(text_latex='Другая задача'), 'other.png')
        self.client.force_login(self.student)

    def img(self, source, element_id='i1'):
        return {'id': element_id, 't': 'img', 's': source, 'w': 1, 'c': '#000000',
                'p': [[100, 100], [500, 100], [100, 400]]}

    def test_images_listed_without_pdf(self):
        data = self.client.get(self.url('pages')).json()
        self.assertEqual([i['id'] for i in data['images']], [self.image.pk])
        self.assertIn(f'/images/{self.image.pk}/file/', data['images'][0]['url'])

    def test_etag_changes_with_images(self):
        response = self.client.get(self.url('pages'))
        etag = response['ETag']
        self.assertEqual(self.client.get(self.url('pages'), HTTP_IF_NONE_MATCH=etag).status_code, 304)
        make_image(self.task, 'second.png')
        response = self.client.get(self.url('pages'), HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['images']), 2)
        self.image.delete()
        self.assertEqual(self.client.get(self.url('pages'), HTTP_IF_NONE_MATCH=response['ETag']).status_code, 200)

    def test_save_and_reject_foreign(self):
        self.assertEqual(self.save(elements=[stroke(), self.img(self.image.pk)]).status_code, 200)
        saved = CanvasPage.objects.get().student_elements[1]
        self.assertEqual((saved['t'], saved['s'], len(saved['p'])), ('img', self.image.pk, 3))
        self.assertEqual(saved['u'], f'/problems/images/{self.image.pk}/file/')
        response = self.save(elements=[self.img(self.foreign.pk)], version=1)
        self.assertEqual(response.status_code, 400)
        self.assertIn('этой задачи', response.json()['message'])
        self.assertEqual(self.save(elements=[self.img(self.pdf.pk)], version=1).status_code, 400)

    def test_schema(self):
        bad = self.img(self.image.pk); bad['p'] = bad['p'][:2]
        self.assertEqual(self.save(elements=[bad]).status_code, 400)
        bad = self.img(self.image.pk); del bad['s']
        self.assertEqual(self.save(elements=[bad]).status_code, 400)
        bad = self.img(self.image.pk); bad['s'] = 'x'
        self.assertEqual(self.save(elements=[bad]).status_code, 400)


class BoardsTests(CanvasBase):
    """Дашборд «Доски»: выборка, лимит, опрос изменений."""

    def live(self, etag=None, **params):
        extra = {'HTTP_IF_NONE_MATCH': etag} if etag else {}
        return self.client.get(reverse('worksheet_boards_live', args=[self.worksheet.pk]), params, **extra)

    def test_page_and_first_load(self):
        self.client.force_login(self.student)
        self.save()
        self.save(number=2, elements=[stroke('b1')])
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('worksheet_boards', args=[self.worksheet.pk]))
        self.assertContains(response, 'data-board="%d"' % self.assignment.pk)
        self.assertContains(response, 'boards.js')
        data = self.live().json()
        self.assertEqual([s['assignment'] for s in data['states']], [self.assignment.pk])
        self.assertEqual(data['states'][0]['status'], Assignment.STATUS_ASSIGNED)
        # первая загрузка — одна последняя страница на ученика…
        self.assertEqual(len(data['pages']), 1)
        self.assertEqual(data['pages'][0]['number'], 2)
        self.assertEqual(data['pages'][0]['task_no'], 1)
        # …и лёгкий список всех задач со страницами, включая старые
        self.assertEqual(data['tasks'], [{'assignment': self.assignment.pk, 'task': self.task.pk, 'task_no': 1, 'count': 2,
                                          'canvas_url': self.url('pages')}])
        self.assertEqual(data['pages'][0]['student']['elements'][0]['id'], 'b1')
        self.assertEqual(data['overflow'], 0)

    def test_first_load_lists_every_task_with_pages(self):
        other = Task.objects.create(text_latex='Вторая')
        WorksheetItem.objects.create(worksheet=self.worksheet, task=other, order=2)
        self.client.force_login(self.student)
        self.save()   # задача 1, раньше
        self.client.post(reverse('canvas:save', args=[self.assignment.pk, other.pk, 1]),
                         data=json.dumps({'layer': 'student', 'elements': [stroke()], 'background': 'grid', 'version': 0}),
                         content_type='application/json')
        self.client.force_login(self.teacher)
        data = self.live().json()
        self.assertEqual(len(data['pages']), 1)
        self.assertEqual(data['pages'][0]['task'], other.pk)
        self.assertEqual(sorted(t['task_no'] for t in data['tasks']), [1, 2])
        # при опросе с since список задач приходит снова (он в подписи; без изменений — 304)
        self.assertEqual(len(self.live(since=data['since']).json()['tasks']), 2)

    def test_task_filter(self):
        other = Task.objects.create(text_latex='Вторая')
        WorksheetItem.objects.create(worksheet=self.worksheet, task=other, order=2)
        self.client.force_login(self.student)
        self.save()
        self.client.post(reverse('canvas:save', args=[self.assignment.pk, other.pk, 1]),
                         data=json.dumps({'layer': 'student', 'elements': [stroke()], 'background': 'grid', 'version': 0}),
                         content_type='application/json')
        self.client.force_login(self.teacher)
        # без фильтра — последняя изменённая (задача 2); с фильтром — задача 1
        self.assertEqual(self.live().json()['pages'][0]['task'], other.pk)
        data = self.live(task=self.task.pk).json()
        self.assertEqual(data['task'], self.task.pk)
        self.assertEqual([p['task'] for p in data['pages']], [self.task.pk])
        self.assertEqual(sorted(t['task_no'] for t in data['tasks']), [1, 2])   # диалог видит обе
        # опрос с since отдаёт только изменения по выбранной задаче
        since = data['since']
        self.client.force_login(self.student)
        self.client.post(reverse('canvas:save', args=[self.assignment.pk, other.pk, 1]),
                         data=json.dumps({'layer': 'student', 'elements': [stroke(), stroke('b')], 'background': 'grid', 'version': 1}),
                         content_type='application/json')
        self.client.force_login(self.teacher)
        self.assertEqual(self.live(task=self.task.pk, since=since).json()['pages'], [])
        self.assertEqual(len(self.live(since=since).json()['pages']), 1)
        # новая доска третьей задачи появляется в tasks при опросе с фильтром, а не только при первой загрузке
        third = Task.objects.create(text_latex='Третья')
        WorksheetItem.objects.create(worksheet=self.worksheet, task=third, order=3)
        filtered = self.live(task=self.task.pk, since=since)
        self.client.force_login(self.student)
        self.client.post(reverse('canvas:save', args=[self.assignment.pk, third.pk, 1]),
                         data=json.dumps({'layer': 'student', 'elements': [stroke()], 'background': 'grid', 'version': 0}),
                         content_type='application/json')
        self.client.force_login(self.teacher)
        again = self.live(etag=filtered['ETag'], task=self.task.pk, since=filtered.json()['since'])
        self.assertEqual(again.status_code, 200)
        self.assertEqual(sorted(t['task_no'] for t in again.json()['tasks']), [1, 2, 3])
        self.assertEqual(again.json()['pages'], [])
        # у ученика без доски по выбранной задаче в tasks есть пустая запись этой задачи
        empty_student = make_student(self.teacher, username='empty')
        empty = Assignment.objects.create(worksheet=self.worksheet, student=empty_student, assigned_by=self.teacher)
        entry = [t for t in self.live(task=self.task.pk).json()['tasks'] if t['assignment'] == empty.pk]
        self.assertEqual(entry, [{'assignment': empty.pk, 'task': self.task.pk, 'task_no': 1, 'count': 0,
                                  'canvas_url': reverse('canvas:pages', args=[empty.pk, self.task.pk])}])
        # ETag различает фильтры; неизвестная задача = без фильтра
        self.assertNotEqual(self.live()['ETag'], self.live(task=self.task.pk)['ETag'])
        self.assertIsNone(self.live(task='999').json()['task'])
        response = self.client.get(reverse('worksheet_boards', args=[self.worksheet.pk]), {'task': self.task.pk})
        self.assertContains(response, 'data-task="%d"' % self.task.pk)
        self.assertContains(response, 'boards/live/?task=%d' % self.task.pk)

    def test_since_and_not_modified(self):
        self.client.force_login(self.student)
        self.save()
        self.client.force_login(self.teacher)
        first = self.live()
        since, etag = first.json()['since'], first['ETag']
        self.assertEqual(self.live(etag=etag, since=since).status_code, 304)
        self.assertEqual(self.live(since=since).json()['pages'], [])
        # ученик дописал — страница приходит, подпись меняется
        self.client.force_login(self.student)
        self.save(elements=[stroke(), stroke('a2')], version=1)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('worksheet_boards_live', args=[self.worksheet.pk]),
                                   {'since': since}, HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['pages']), 1)
        self.assertEqual(len(response.json()['pages'][0]['student']['elements']), 2)
        # пометка учителя тоже считается изменением
        since = response.json()['since']
        self.assertEqual(self.save(layer='teacher').status_code, 200)
        self.assertEqual(len(self.live(since=since).json()['pages']), 1)

    def test_limit_and_overflow(self):
        for i in range(17):
            student = make_student(self.teacher, username=f'st{i}')
            Assignment.objects.create(worksheet=self.worksheet, student=student, assigned_by=self.teacher)
        self.client.force_login(self.teacher)
        data = self.live().json()
        self.assertEqual(len(data['states']), 15)
        self.assertEqual(data['overflow'], 3)
        response = self.client.get(reverse('worksheet_boards', args=[self.worksheet.pk]))
        self.assertContains(response, 'ещё 3 не поместились')
        # недавно писавший ученик попадает на экран первым
        self.client.force_login(self.student)
        self.save()
        self.client.force_login(self.teacher)
        self.assertEqual(self.live().json()['states'][0]['assignment'], self.assignment.pk)

    def test_foreign_teacher(self):
        self.client.force_login(make_teacher(username='other_teacher'))
        self.assertEqual(self.live().status_code, 404)
        self.assertEqual(self.client.get(reverse('worksheet_boards', args=[self.worksheet.pk])).status_code, 404)
        self.client.force_login(self.student)
        self.assertIn(self.live().status_code, (302, 403, 404))

    @override_settings(CANVAS_ENABLED=False)
    def test_disabled(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.live().status_code, 503)

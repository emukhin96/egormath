"""Быстрый клон задачи: числа в условии, маска за ответом, сохранение."""
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from independentworks.models import Candidate, Family, Position, Work
from worksheets.models import Worksheet, WorksheetItem
from .clone_numbers import (find_numbers, follow_mask, mask_follows_answer,
                            replace_numbers, split_numbers)
from .models import Source, Task, TaskBlock, TaskImage, TaskSource
from .tests import make_student, make_teacher


def values(text):
    return [value for _, _, value in find_numbers(text)]


class FindNumbersTests(SimpleTestCase):
    """Строки — условия из базы задач (локальная копия, октябрь 2026)."""

    def test_fractions_powers_and_negative_exponents(self):
        text = (r'Вычислите \(\displaystyle \frac{128 \cdot 8^{-1} \cdot 3^{6}+6^{8}}'
                r'{4^{2} \cdot 9^{3} \cdot\left(\frac{1}{5}\right)^{-1}}:'
                r'\left(\frac{1}{29}\right)^{-1}\).')
        self.assertEqual(values(text), ['128', '8', '3', '6', '4', '9', '1', '5', '1', '29'])

    def test_indices_are_not_numbers(self):
        text = (r'\(b_{n}\) — геометрическая прогрессия. \(\displaystyle b_{1}=\frac{1}{128} ; '
                r'q=2\). Найдите номер члена прогрессии, равного 32.')
        self.assertEqual(values(text), ['1', '128', '2', '32'])
        text = (r'\(b_{n}\) — геометрическая прогрессия. \(\displaystyle b_{2}=37 \frac{1}{3} ; '
                r'b_{6}=2 \frac{1}{3}\). Найдите \(b_{1}\) и \(q\).')
        self.assertEqual(values(text), ['37', '1', '3', '2', '1', '3'])

    def test_root_index_is_skipped(self):
        text = (r'Расположите числа \(\displaystyle \sqrt[16]{64}, \sqrt[10]{7 \sqrt[4]{7}}, '
                r'\sqrt[4]{2 \sqrt{\frac{5}{4}}}\) в порядке возрастания.')
        self.assertEqual(values(text), ['64', '7', '7', '2', '5', '4'])

    def test_decimal_comma_and_braced_comma(self):
        text = (r'Определите знак выражения \(\displaystyle a=\frac{\sin 2,5 \cdot \cos 5}'
                r'{\operatorname{tg} 3}\).')
        self.assertEqual(values(text), ['2,5', '5', '3'])
        text = (r'Сократите дробь $\displaystyle \frac{10 x^2-13 x-3}{-2 x^2+x+3}$ и '
                r'вычислите её значение при $x=-6{,}2$.')
        # Минус — отдельный знак, x^2 — показатель
        self.assertEqual(values(text), ['10', '13', '3', '2', '3', '6{,}2'])
        self.assertEqual(values(r'Что больше \(\displaystyle -\frac{2}{3}\) или \(\cos 2,3\)?'),
                         ['2', '3', '2,3'])

    def test_comment_is_skipped(self):
        text = ('%\\annot{12}\nНайдите наименьшее целое число решения\r\n$\\displaystyle \r\n'
                '\\frac{4 x-3}{3}<\\frac{7 x-9}{4}-\\frac{3 x-8}{12}.\r\n$')
        self.assertEqual(values(text), ['4', '3', '3', '7', '9', '4', '3', '8', '12'])

    def test_exponent_with_expression(self):
        text = (r'При каких \(x\) числа \(32^{x} ; 6^{x^{2}+1}\) и \(3^{5 x}\) являются '
                r'последовательными членами геометрической прогрессии?')
        self.assertEqual(values(text), ['32', '6', '3'])

    def test_table_spec_and_hspace_are_skipped(self):
        text = ('В таблице представлены данные о контрольном измерении партии яиц первой '
                'категории (от 55 до 65 г).\n\n\\hspace{-1cm}\\begin{tabular}{|l|c|c|c|}\n'
                '\\hline № & $\\mathbf{1}$ & $\\mathbf{2}$ & $\\mathbf{3}$ \\\\\n'
                '\\hline Macca, г & 55,4 & 63,2 & 56,4 \\\\\n\\hline\n\\end{tabular}\n\n'
                'медиана отличается от среднего больше, чем на $10 \\%$ размаха.')
        self.assertEqual(values(text), ['55', '65', '1', '2', '3', '55,4', '63,2', '56,4', '10'])

    def test_taskpic_and_makebox_widths_are_skipped(self):
        text = ('Докажите, что треугольник $A B C$ на рисунке равнобедренный.\n\n'
                '\\taskpic{1}\n\\taskpic{2}\\par\n\\makebox[30mm][c]{\\textit{К задаче 4}}\n'
                '\\makebox[45mm][c]{\\textit{К задаче 5}}')
        self.assertEqual(values(text), ['4', '5'])
        text = (r'Известно, что $A B=18$, $B C=9$. Найдите отрезки.' '\n\n'
                r'\taskpic{1}' '\n\n' r'\par' '\n' r'\makebox[45mm][c]{\textit{К задаче 1}}')
        self.assertEqual(values(text), ['18', '9', '1'])

    def test_degrees_and_trig(self):
        text = (r'Вычислите \(\displaystyle \frac{1-\operatorname{tg} 74^{\circ} \cdot '
                r'\operatorname{ctg} 14^{\circ}}{\operatorname{tg} 74^{\circ}-\operatorname{tg} 104^{\circ}}\).')
        self.assertEqual(values(text), ['1', '74', '14', '74', '104'])

    def test_service_commands_units_and_environments(self):
        text = (r'\includegraphics[width=3cm]{pic1.png}\vspace{2mm}Сторона 5 см\label{eq:1}'
                r'\\[2mm] ширина 0.5\textwidth, \ref{f2} и x_{12}+a^23, x=3.5, равна 7.'
                '\n\\begin{array}{l}x=4\\end{array}'
                '\n\\begin{tikzpicture}\\draw (0,0) -- (1,2);\\end{tikzpicture} 8')
        self.assertEqual(values(text), ['5', '3', '3.5', '7', '4', '8'])

    def test_lists_are_not_decimals(self):
        self.assertEqual(values('числа 1,2,3 и 4,5'), ['1', '2', '3', '4,5'])
        self.assertEqual(values(r'\(x \in [1; 2]\), \(\left[3;4\right]\)'), ['1', '2', '3', '4'])

    def test_split_and_replace_round_trip(self):
        text = r'Решите уравнение \(3x^2-12=0\).'
        segments = split_numbers(text)
        self.assertEqual([s.get('num') for s in segments if 'num' in s], ['3', '12', '0'])
        self.assertEqual(''.join(s.get('text', s.get('num')) for s in segments), text)
        self.assertEqual(replace_numbers(text, ['7', '28', '0']), r'Решите уравнение \(7x^2-28=0\).')
        with self.assertRaises(ValueError):
            replace_numbers(text, ['1'])


class MaskFollowTests(SimpleTestCase):
    def test_simple_mask_follows_answer(self):
        mask = '$MB=${{number: 4}}, $BD=${{number:10}}'
        self.assertTrue(mask_follows_answer(mask, '$4$; $10$'))
        self.assertEqual(follow_mask(mask, '$4$; $10$', '$5$; $12$'),
                         '$MB=${{number: 5}}, $BD=${{number:12}}')

    def test_set_tolerance_and_decimal(self):
        self.assertEqual(follow_mask('{{set: -1; 1}}', '$-1; 1$', '$-2; 2$'), '{{set: -2; 2}}')
        self.assertEqual(follow_mask('{{number: 3,14 ~ 0,01}}', '$3{,}14$', '$2{,}72$'),
                         '{{number: 2,72 ~ 0,01}}')

    def test_sign_change_breaks_follow(self):
        # Ответ −3 → 5: в маске не должно остаться «−5»
        self.assertTrue(mask_follows_answer('{{number: -3}}', '$-3$'))
        self.assertIsNone(follow_mask('{{number: -3}}', '$-3$', '$5$'))
        self.assertIsNone(follow_mask('{{number: 2}}', '$2$', '$-2$'))
        self.assertIsNone(follow_mask('{{set: -1; 1}}', '$-1; 1$', '$1; -1$'))
        self.assertEqual(follow_mask('{{number: -3}}', '$-3$', '$-7$'), '{{number: -7}}')
        self.assertEqual(follow_mask('{{number: -3}}', '$−3$', '$ − 4$'), '{{number: -4}}')
        # Знак маски и ответа расходятся — маска не «простая»
        self.assertFalse(mask_follows_answer('{{number: 3}}', '$-3$'))
        self.assertFalse(mask_follows_answer('{{number: -3}}', '$3$'))

    def test_complex_masks_do_not_follow(self):
        self.assertFalse(mask_follows_answer('{{choice: 1|*2}}', '2'))
        self.assertFalse(mask_follows_answer('{{number: 8}}', '$9$'))
        self.assertFalse(mask_follows_answer('', '$9$'))
        self.assertFalse(mask_follows_answer('{{yesno: да}}', 'да'))
        # В новом ответе другое количество чисел
        self.assertIsNone(follow_mask('{{number: 8}}', '$8$', '$8$ и $9$'))


class CloneViewTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)
        self.task = Task.objects.create(
            created_by=self.teacher, text_latex=r'Решите уравнение \(3x^2-12=0\).',
            author_answer_latex='$-2; 2$', answer_latex='AI: $\\pm 2$',
            author_solution_latex='Авторское решение', solution_latex='AI решение',
            answer_mask='{{set: -2; 2}}')
        self.sub = self.task.subitems.create(
            order=1, text_latex='Найдите сумму корней, увеличенную на 5',
            answer_latex='$5$', solution_latex='Решение подпункта', answer_mask='{{number: 5}}')
        self.book = Source.objects.create(title='Книга')
        TaskSource.objects.create(task=self.task, source=self.book, number='398')
        self.url = reverse('task_clone', args=[self.task.pk])

    def data(self, **extra):
        data = {
            'task-text': r'Решите уравнение \(7x^2-28=0\).',
            'task-answer': '$-2; 2$', 'task-mask': '{{set: -2; 2}}', 'task-mask_follow': '1',
            f'sub-{self.sub.pk}-text': 'Найдите сумму корней, увеличенную на 6',
            f'sub-{self.sub.pk}-answer': '$6$', f'sub-{self.sub.pk}-mask': '{{number: 6}}',
            f'sub-{self.sub.pk}-mask_follow': '1',
        }
        data.update(extra)
        return data

    def test_dialog_fragment(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Клон задачи · Книга, №398')
        self.assertContains(response, 'Источник: аналог к Книга, №398')
        self.assertContains(response, 'class="num-in"', count=4)
        self.assertContains(response, '✓ следует за ответом', count=2)
        self.assertContains(response, 'Новая задача в базе')
        self.assertContains(response, 'Оставить решение')

    def test_clone_without_context(self):
        response = self.client.post(self.url, self.data(**{'task-answer': '$-3; 3$',
                                                           'task-mask': 'устаревшая'}))
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertFalse(payload['reload'])
        copy = Task.objects.get(pk=payload['task_id'])
        self.assertEqual(payload['url'], reverse('task_detail', args=[copy.pk]))
        self.assertIsNone(copy.variant_of_id)
        self.assertEqual(copy.text_latex, r'Решите уравнение \(7x^2-28=0\).')
        # Правится действующий (авторский) ответ, AI-версия очищена
        self.assertEqual((copy.author_answer_latex, copy.answer_latex), ('$-3; 3$', ''))
        # Простая маска пересчитана на сервере, клиентская строка не нужна
        self.assertEqual(copy.answer_mask, '{{set: -3; 3}}')
        self.assertEqual((copy.solution_latex, copy.author_solution_latex), ('', ''))
        sub = copy.subitems.get()
        self.assertEqual((sub.text_latex, sub.answer_latex, sub.answer_mask, sub.solution_latex),
                         ('Найдите сумму корней, увеличенную на 6', '$6$', '{{number: 6}}', ''))
        # Номер задачника не наследуется; связь — через семейство аналогов
        self.assertFalse(copy.source_refs.exists())
        self.assertEqual(set(copy.analog_families.get().tasks.all()), {self.task, copy})
        self.task.refresh_from_db()
        self.assertEqual(self.task.answer_latex, 'AI: $\\pm 2$')
        self.assertEqual(self.task.source_refs.count(), 1)

    def test_keep_solution_and_second_clone_joins_family(self):
        self.client.post(self.url, self.data())
        response = self.client.post(self.url, self.data(keep_solution='1'))
        copy = Task.objects.get(pk=response.json()['task_id'])
        self.assertEqual(copy.author_solution_latex, 'Авторское решение')
        self.assertEqual(copy.subitems.get().solution_latex, 'Решение подпункта')
        self.assertEqual(Family.objects.count(), 1)
        self.assertEqual(Family.objects.get().tasks.count(), 3)

    def test_manual_and_invalid_masks(self):
        response = self.client.post(self.url, self.data(**{
            'task-mask_follow': '0', 'task-mask': '{{range: 1; 4}}'}))
        self.assertEqual(Task.objects.get(pk=response.json()['task_id']).answer_mask, '{{range: 1; 4}}')
        before = Task.objects.count()
        response = self.client.post(self.url, self.data(**{
            'task-mask_follow': '0', 'task-mask': '{{numbr: 3}}'}))
        self.assertEqual(response.status_code, 400)
        self.assertIn('Маска', response.json()['errors'][0])
        self.assertEqual(Task.objects.count(), before)
        # Знак сменился — сервер не пересчитывает маску, берёт присланную
        response = self.client.post(self.url, self.data(**{
            'task-answer': '$2; 3$', 'task-mask': '{{set: 2; 3}}'}))
        self.assertEqual(Task.objects.get(pk=response.json()['task_id']).answer_mask, '{{set: 2; 3}}')
        # Число чисел в ответе изменилось — простая маска не пересчитывается
        response = self.client.post(self.url, self.data(**{
            'task-answer': '$1$', 'task-mask': '{{number: 1}}'}))
        self.assertEqual(Task.objects.get(pk=response.json()['task_id']).answer_mask, '{{number: 1}}')

    def test_multiline_answer_survives_textarea(self):
        Task.objects.filter(pk=self.task.pk).update(
            author_answer_latex='$D<a \\Rightarrow$\nкорней нет % см. рис. 3\n$x=2$',
            answer_mask='{{number: 2}}')
        self.task.refresh_from_db()
        page = self.client.get(self.url)
        self.assertContains(page, 'name="task-answer" rows="1" data-answer')
        original = self.task.author_answer_latex
        # Браузер присылает textarea с CRLF; ответ не трогали — он остаётся как был
        response = self.client.post(self.url, self.data(**{
            'task-answer': original.replace('\n', '\r\n'), 'task-mask': '{{number: 2}}'}))
        copy = Task.objects.get(pk=response.json()['task_id'])
        self.assertEqual(copy.author_answer_latex, original)
        self.assertEqual(copy.answer_mask, '{{number: 2}}')
        # Изменённый многострочный ответ сохраняет переводы строк, маска следует
        response = self.client.post(self.url, self.data(**{
            'task-answer': original.replace('x=2', 'x=5').replace('\n', '\r\n'),
            'task-mask': '{{number: 2}}'}))
        copy = Task.objects.get(pk=response.json()['task_id'])
        self.assertEqual(copy.author_answer_latex, original.replace('x=2', 'x=5'))
        self.assertEqual(copy.answer_mask, '{{number: 5}}')
        # Подпункт: многострочный ответ без изменений
        self.sub.answer_latex = 'а) $1$\n% хвост\nб) $5$'
        self.sub.answer_mask = ''
        self.sub.save()
        response = self.client.post(self.url, self.data(**{
            f'sub-{self.sub.pk}-answer': self.sub.answer_latex.replace('\n', '\r\n'),
            f'sub-{self.sub.pk}-mask': '', f'sub-{self.sub.pk}-mask_follow': '0'}))
        sub = Task.objects.get(pk=response.json()['task_id']).subitems.get()
        self.assertEqual(sub.answer_latex, 'а) $1$\n% хвост\nб) $5$')

    def test_editor_answer_is_edited_when_no_author_answer(self):
        self.client.post(self.url, self.data(**{f'sub-{self.sub.pk}-answer': '$11$'}))
        sub = Task.objects.exclude(pk=self.task.pk).get().subitems.get()
        self.assertEqual((sub.author_answer_latex, sub.answer_latex, sub.answer_mask),
                         ('', '$11$', '{{number: 11}}'))

    def test_clone_into_worksheet_after_item(self):
        ws = Worksheet.objects.create(owner=self.teacher, title='Листок')
        item = WorksheetItem.objects.create(worksheet=ws, task=self.task, order=10,
                                            all_subitems=False, stars_override=2)
        item.subitems.add(self.sub)
        last = WorksheetItem.objects.create(worksheet=ws, text_latex='После', order=20)
        page = self.client.get(self.url + f'?worksheet={ws.pk}&item={item.pk}')
        self.assertContains(page, 'Добавится в листок «Листок»')
        response = self.client.post(self.url, self.data(worksheet=ws.pk, item=item.pk))
        payload = response.json()
        self.assertTrue(payload['reload'])
        rows = list(ws.ordered_items())
        self.assertEqual([rows[0].pk, rows[2].pk], [item.pk, last.pk])
        self.assertEqual(rows[1].task_id, payload['task_id'])
        self.assertIsNone(rows[1].task.variant_of_id)
        self.assertEqual(rows[1].stars_override, 2)
        self.assertEqual(list(rows[1].subitems.values_list('text_latex', flat=True)),
                         ['Найдите сумму корней, увеличенную на 6'])
        detail = self.client.get(reverse('worksheet_detail', args=[ws.pk]))
        # Успех показывает тост диалога, flash-плашки не копятся
        self.assertNotContains(detail, 'ws-toast-src')
        self.assertContains(detail, 'клон рядом')

    def test_next_clones_follow_previous_clone(self):
        ws = Worksheet.objects.create(owner=self.teacher, title='Листок')
        item = WorksheetItem.objects.create(worksheet=ws, task=self.task, order=10)
        last = WorksheetItem.objects.create(worksheet=ws, text_latex='После', order=20)
        first = self.client.post(self.url, self.data(worksheet=ws.pk, item=item.pk)).json()
        second = self.client.post(self.url, self.data(
            worksheet=ws.pk, item=item.pk, after=first['item_id'])).json()
        self.assertEqual(list(ws.ordered_items().values_list('pk', flat=True)),
                         [item.pk, first['item_id'], second['item_id'], last.pk])
        self.assertEqual(WorksheetItem.objects.get(pk=second['item_id']).task_id, second['task_id'])
        # Строка другого листка как «после чего» не принимается
        other = WorksheetItem.objects.create(
            worksheet=Worksheet.objects.create(owner=self.teacher, title='Другой'), text_latex='x')
        response = self.client.post(self.url, self.data(worksheet=ws.pk, item=item.pk, after=other.pk))
        self.assertEqual(response.status_code, 404)

    @override_settings(INDEPENDENT_WORKS_ENABLED=True)
    def test_clone_into_independent_position(self):
        work = Work.objects.create(owner=self.teacher, title='С-3')
        position = Position.objects.create(work=work)
        Candidate.objects.create(position=position, task=self.task)
        page = self.client.get(self.url + f'?position={position.pk}')
        self.assertContains(page, 'Добавится вариантом в №1 · С-3')
        response = self.client.post(self.url, self.data(position=position.pk))
        copy = Task.objects.get(pk=response.json()['task_id'])
        self.assertTrue(response.json()['reload'])
        self.assertEqual(set(position.candidates.values_list('task_id', flat=True)),
                         {self.task.pk, copy.pk})
        self.assertEqual(set(copy.analog_families.get().tasks.all()), {self.task, copy})
        self.assertFalse(copy.source_refs.exists())
        pick = self.client.get(reverse('independentworks:pick', args=[position.pk]))
        self.assertContains(pick, 'Клон в этот номер')
        self.assertContains(pick, 'Полная форма')
        edit = self.client.get(reverse('independentworks:edit', args=[work.pk]))
        self.assertContains(edit, f'?position={position.pk}')

    @override_settings(INDEPENDENT_WORKS_ENABLED=True)
    def test_permissions(self):
        other = make_teacher('other')
        ws = Worksheet.objects.create(owner=other, title='Чужой')
        item = WorksheetItem.objects.create(worksheet=ws, task=self.task)
        self.assertEqual(self.client.post(self.url, self.data(worksheet=ws.pk, item=item.pk)).status_code, 403)
        position = Position.objects.create(work=Work.objects.create(owner=other, title='Чужая'))
        self.assertEqual(self.client.post(self.url, self.data(position=position.pk)).status_code, 404)
        # Локальная копия годится как исходная только из своего номера
        own = Position.objects.create(work=Work.objects.create(owner=self.teacher, title='Своя'))
        local = self.task.make_variant(self.teacher)
        self.assertEqual(self.client.get(
            reverse('task_clone', args=[local.pk]) + f'?position={own.pk}').status_code, 404)
        with override_settings(INDEPENDENT_WORKS_ENABLED=False):
            self.assertEqual(self.client.get(self.url + f'?position={own.pk}').status_code, 404)
        self.client.force_login(make_student(self.teacher))
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(Task.objects.count(), 2)

    def test_block_task_is_refused(self):
        block = TaskBlock.objects.create(source=self.book, key='b', title='Блок', size=1)
        Task.objects.filter(pk=self.task.pk).update(block=block, block_position=1)
        self.assertContains(self.client.get(self.url), 'используйте «дублировать»')
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 400)
        self.assertEqual(Task.objects.count(), 1)

    def test_preview(self):
        response = self.client.post(reverse('task_clone_preview', args=[self.task.pk]),
                                    {'text': r'Решите \(7x=1\)', 'sub': ['Первый']})
        self.assertIn('math-content', response.json()['html'])
        self.assertIn('Первый', response.json()['html'])


def png_file(name='new.png', color='red'):
    buffer = io.BytesIO()
    Image.new('RGB', (4, 4), color).save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


class CloneImageTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)
        self.task = Task.objects.create(
            text_latex='Рисунки \\taskpic{1} и \\taskpic{2} и \\taskpic{3}',
            author_solution_latex='См. \\taskpic{3}')
        self.images = [TaskImage.objects.create(task=self.task, image=f'task_images/p{i}.png')
                       for i in range(3)]
        self.url = reverse('task_clone', args=[self.task.pk])

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_dialog_lists_images(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Проверьте, что числа на рисунке согласованы с условием')
        self.assertContains(response, 'data-pic-warn', count=3)
        self.assertContains(response, 'accept="image/png,image/jpeg,application/pdf,.pdf"', count=3)

    def test_keep_replace_remove(self):
        first, second, third = self.images
        response = self.client.post(self.url, {
            'task-text': self.task.text_latex, 'keep_solution': '1',
            f'image-{first.pk}': 'remove', f'image-{second.pk}': 'replace',
            f'image-{second.pk}-file': png_file(), f'image-{third.pk}': 'keep',
        })
        self.assertEqual(response.status_code, 200, response.content)
        copy = Task.objects.get(pk=response.json()['task_id'])
        rows = list(copy.images.all())
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].image.name.startswith('task_images/new'))
        self.assertEqual(rows[1].image.name, 'task_images/p2.png')
        # Ссылка на убранный рисунок удалена, остальные перенумерованы
        self.assertEqual(copy.text_latex, 'Рисунки  и \\taskpic{1} и \\taskpic{2}')
        self.assertEqual(copy.author_solution_latex, 'См. \\taskpic{2}')
        # Исходная задача и её файлы не тронуты
        self.assertEqual([img.image.name for img in self.task.images.all()],
                         ['task_images/p0.png', 'task_images/p1.png', 'task_images/p2.png'])
        self.assertIn('\\taskpic{1}', Task.objects.get(pk=self.task.pk).text_latex)

    def test_replace_requires_file(self):
        response = self.client.post(self.url, {
            'task-text': self.task.text_latex, f'image-{self.images[0].pk}': 'replace'})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(self.url, {
            'task-text': self.task.text_latex, f'image-{self.images[0].pk}': 'replace',
            f'image-{self.images[0].pk}-file': SimpleUploadedFile('a.txt', b'x')})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Task.objects.count(), 1)

import json
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from problems.models import Task, TaskSubitem
from problems.tests import make_student, make_teacher

from .beamer import normalize_beamer_options, worksheet_to_beamer
from .latex import task_to_tex, worksheet_to_tex
from .models import ShareLink, Worksheet, WorksheetItem, WorksheetPdf
from .services import LatexCompileError


def make_worksheet(owner, title='Квадратные уравнения', n_tasks=2):
    worksheet = Worksheet.objects.create(
        title=title, grade_label='8 класс', owner=owner)
    for i in range(n_tasks):
        task = Task.objects.create(
            text_latex=f'Решите уравнение $x^2-{i + 2}x={i}$.',
            answer_latex=f'{i}; {i + 2}', stars=1, created_by=owner)
        WorksheetItem.objects.create(
            worksheet=worksheet, task=task, order=(i + 1) * 10)
    return worksheet


def make_item(worksheet, task, **kwargs):
    return WorksheetItem.objects.create(
        worksheet=worksheet, task=task, order=1000, **kwargs)


def make_rubric(worksheet, name, order, note=''):
    return WorksheetItem.objects.create(
        worksheet=worksheet, rubric=name, rubric_note=note, order=order)


class LatexGenerationTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = Worksheet.objects.create(
            title='Тест', owner=self.teacher)

    def test_task_to_tex_full(self):
        task = Task.objects.create(
            text_latex='Вычислите:', columns=2,
            answer_latex='4', solution_latex='Очевидно.', stars=1)
        TaskSubitem.objects.create(task=task, order=10, text_latex='$2+2$;')
        item = make_item(self.worksheet, task)
        tex = task_to_tex(item)
        self.assertIn('\\task{1}{2}{%', tex)
        self.assertIn('[{\\item $2+2$;}]', tex)
        self.assertIn('[{4}]', tex)
        self.assertIn(
            '[{\\mbox{}\\\\ \\begin{minipage}[t]{\\linewidth}%\n'
            'Очевидно.%\n\\end{minipage}}]', tex)

    def test_task_to_tex_omits_trailing_args(self):
        task = Task.objects.create(text_latex='Просто задача')
        tex = task_to_tex(make_item(self.worksheet, task))
        self.assertNotIn('[', tex.replace('\\[', ''))

    def test_answer_with_brackets_is_protected(self):
        task = Task.objects.create(
            text_latex='Неравенство', answer_latex='$x \\in [1; 2]$')
        tex = task_to_tex(make_item(self.worksheet, task))
        self.assertIn('[{$x \\in [1; 2]$}]', tex)

    def test_overrides(self):
        task = Task.objects.create(text_latex='Задача', stars=1, columns=0)
        TaskSubitem.objects.create(task=task, order=10, text_latex='пункт')
        item = make_item(self.worksheet, task,
                         stars_override=3, columns_override=2)
        tex = task_to_tex(item)
        self.assertIn('\\task{3}{2}{%', tex)

    def test_columns_zeroed_without_subitems(self):
        # columns>=1 без подпунктов дают пустой список и «missing \item»
        # при компиляции; без подпунктов колонки принудительно 0
        task = Task.objects.create(
            text_latex='Задача', columns=2, answer_latex='7')
        tex = task_to_tex(make_item(self.worksheet, task))
        self.assertIn('\\task{0}{0}{%', tex)
        self.assertIn('[{}][{7}]', tex)

    def test_subitem_punctuation(self):
        # В базе подпункты без знаков препинания — система расставляет
        # «;» между пунктами и «.» после последнего
        task = Task.objects.create(text_latex='Вычислите:')
        for i, text in enumerate(['$1+1$', '$2+2$', '$3+3$']):
            TaskSubitem.objects.create(
                task=task, order=(i + 1) * 10, text_latex=text)
        tex = task_to_tex(make_item(self.worksheet, task))
        self.assertIn(
            '[{\\item $1+1$;\n\\item $2+2$;\n\\item $3+3$.}]', tex)

    def test_subitem_punctuation_follows_selection(self):
        # Последний ВЫБРАННЫЙ подпункт получает точку
        task = Task.objects.create(text_latex='Вычислите:')
        s1 = TaskSubitem.objects.create(
            task=task, order=10, text_latex='$1+1$')
        TaskSubitem.objects.create(task=task, order=20, text_latex='$2+2$')
        item = make_item(self.worksheet, task, all_subitems=False)
        item.subitems.set([s1])
        tex = task_to_tex(item)
        self.assertIn('\\item $1+1$.', tex)

    def test_subitem_selection_and_answers(self):
        task = Task.objects.create(text_latex='Вычислите:')
        s1 = TaskSubitem.objects.create(
            task=task, order=10, text_latex='$1+1$;', answer_latex='2')
        TaskSubitem.objects.create(
            task=task, order=20, text_latex='$2+2$;', answer_latex='4')
        s3 = TaskSubitem.objects.create(
            task=task, order=30, text_latex='$3+3$;', answer_latex='6')
        item = make_item(self.worksheet, task, all_subitems=False)
        item.subitems.set([s1, s3])
        tex = task_to_tex(item)
        self.assertIn('\\item $1+1$;', tex)
        self.assertNotIn('$2+2$', tex)
        self.assertIn('\\item $3+3$;', tex)
        # Ответы перенумерованы заново: а) и б)
        self.assertIn(r'[{\shortstack[l]{а)~2 \\ б)~6}}]', tex)

    def test_subitem_solutions_combined(self):
        # Решения подпунктов собираются в 6-й аргумент \task как ответы
        task = Task.objects.create(text_latex='Вычислите:')
        TaskSubitem.objects.create(
            task=task, order=10, text_latex='$1+1$', answer_latex='2',
            solution_latex='Складываем единицы')
        TaskSubitem.objects.create(
            task=task, order=20, text_latex='$2+2$', answer_latex='4',
            solution_latex='Складываем двойки')
        item = make_item(self.worksheet, task)
        tex = task_to_tex(item)
        self.assertIn(
            '\\mbox{}\\\\ \\begin{minipage}[t]{\\linewidth}%\n'
            'а)~Складываем единицы \\mbox{}\\\\ б)~Складываем двойки%\n'
            '\\end{minipage}', tex)
        # Общее решение задачи идёт перед решениями подпунктов
        task.solution_latex = 'Общий план.\n\nСначала оценки.'
        task.save()
        tex = task_to_tex(item)
        self.assertIn('\\begin{minipage}[t]{\\linewidth}', tex)
        self.assertIn(
            'Общий план. \\mbox{}\\\\ Сначала оценки. \\mbox{}\\\\ '
            'а)~Складываем', tex)
        self.assertIn('\\end{minipage}', tex)

    def test_array_bidi_shim(self):
        # Заглушка после \usepackage{egor}: иначе array в \plaintext
        # (и tabular/cases) падают на TeX Live 2025 + bidi/xelatex
        from .latex import ARRAY_BIDI_SHIM
        worksheet = make_worksheet(self.teacher)
        tex = worksheet_to_tex(worksheet, 'student')
        pos_pkg = tex.index('\\usepackage{egor}')
        pos_shim = tex.index(ARRAY_BIDI_SHIM)
        pos_begin = tex.index('\\begin{document}')
        self.assertLess(pos_pkg, pos_shim)
        self.assertLess(pos_shim, pos_begin)

    def test_worksheet_variants(self):
        worksheet = make_worksheet(self.teacher)
        student_tex = worksheet_to_tex(worksheet, 'student')
        self.assertIn('\\usepackage{egor}', student_tex)
        self.assertIn('\\bighead{Квадратные уравнения}{8 класс}', student_tex)
        # Рубрик нет — список стартует вручную, без \rubr
        self.assertNotIn('\\rubr', student_tex)
        self.assertIn('\\begin{enumerate}', student_tex)
        self.assertIn('\\end{enumerate}', student_tex)

        answers_tex = worksheet_to_tex(worksheet, 'answers')
        self.assertIn('\\usepackage[answers=table]{egor}', answers_tex)

        teacher_tex = worksheet_to_tex(worksheet, 'teacher')
        self.assertIn('\\usepackage[answers=inline,solutions]{egor}',
                      teacher_tex)

    def test_rubric_items(self):
        worksheet = make_worksheet(self.teacher, n_tasks=3)
        # Рубрики — самостоятельные элементы перед задачами 1 и 3
        make_rubric(worksheet, 'Разминка', order=5)
        make_rubric(worksheet, 'Основная часть', order=25,
                    note='Решаем письменно')
        tex = worksheet_to_tex(worksheet, 'student')
        self.assertIn('\\rubr{Разминка}', tex)
        self.assertIn('\\rubr{Основная часть}[{Решаем письменно}]', tex)
        self.assertEqual(tex.count('\\rubr'), 2)
        # \rubr сам открывает список — ручного \begin{enumerate} нет
        self.assertNotIn('\\begin{enumerate}', tex)
        self.assertEqual(tex.count('\\end{enumerate}'), 1)

    def test_task_before_first_rubric_opens_list(self):
        worksheet = make_worksheet(self.teacher, n_tasks=2)
        # Рубрика после первой задачи: список уже открыт вручную
        make_rubric(worksheet, 'Основная часть', order=15)
        tex = worksheet_to_tex(worksheet, 'student')
        self.assertEqual(tex.count('\\begin{enumerate}'), 1)
        self.assertLess(tex.index('\\begin{enumerate}'), tex.index('\\rubr'))

    def test_text_item(self):
        worksheet = make_worksheet(self.teacher)
        WorksheetItem.objects.create(
            worksheet=worksheet, order=15,
            text_latex='Вспомните формулу дискриминанта.')
        tex = worksheet_to_tex(worksheet, 'student')
        self.assertIn('\\plaintext{%', tex)
        self.assertIn('Вспомните формулу дискриминанта.', tex)
        # Текст между задачами — без пустого \item[]
        self.assertNotIn('\\item[]', tex)

    def test_text_item_styles(self):
        # Стиль текстового элемента выбирает команду egor
        worksheet = make_worksheet(self.teacher)
        for style, command in (('rule', 'ruletext'), ('light', 'lighttext'),
                               ('memo', 'memotext')):
            item = WorksheetItem.objects.create(
                worksheet=worksheet, order=15,
                text_latex='Правило.', text_style=style)
            tex = worksheet_to_tex(worksheet, 'student')
            self.assertIn('\\%s{%%' % command, tex)
            item.delete()

    def test_text_right_after_rubric(self):
        # \plaintext сразу после \rubr требует пустого \item[] —
        # иначе LaTeX падает на тексте внутри enumerate до первого пункта
        worksheet = make_worksheet(self.teacher)
        make_rubric(worksheet, 'Разминка', order=5)
        WorksheetItem.objects.create(
            worksheet=worksheet, order=6, text_latex='Считаем устно.')
        tex = worksheet_to_tex(worksheet, 'student')
        pos_rubr = tex.index('\\rubr{Разминка}')
        pos_item = tex.index('\\item[]')
        pos_text = tex.index('\\plaintext')
        self.assertLess(pos_rubr, pos_item)
        self.assertLess(pos_item, pos_text)
        self.assertEqual(tex.count('\\item[]'), 1)

    def test_worksheet_duplicate(self):
        worksheet = make_worksheet(self.teacher)
        make_rubric(worksheet, 'Разминка', order=5)
        items = list(worksheet.ordered_items())
        items[1].stars_override = 2
        items[1].save()
        copy = worksheet.duplicate()
        self.assertEqual(copy.title, 'Квадратные уравнения (копия)')
        self.assertEqual(copy.items.count(), worksheet.items.count())
        copied = list(copy.ordered_items())
        self.assertEqual(copied[0].rubric, 'Разминка')
        self.assertTrue(copied[0].is_rubric)
        self.assertEqual(copied[1].stars_override, 2)
        self.assertEqual(copied[1].task_id, items[1].task_id)

    def test_task_images_in_tex(self):
        task = Task.objects.create(text_latex='Задача с картинкой')
        task.images.create(image='task_images/pic1.png', order=10)
        task.images.create(image='task_images/pic2.jpg', order=20)
        item = make_item(self.worksheet, task)
        tex = task_to_tex(item)
        self.assertIn('\\taskpic{pic1.png}', tex)
        self.assertIn('\\taskpic{pic2.jpg}', tex)
        ws_tex = worksheet_to_tex(self.worksheet, 'student')
        self.assertIn('\\flushpics', ws_tex)
        self.assertLess(ws_tex.index('\\end{enumerate}'),
                        ws_tex.index('\\flushpics'))
        # Без картинок \flushpics не выводится
        other = make_worksheet(self.teacher, title='Без картинок')
        self.assertNotIn('\\flushpics', worksheet_to_tex(other, 'student'))

    def test_taskpic_refs_in_text(self):
        # \taskpic{N} в тексте → имя файла; лишние ссылки убираются;
        # картинки без ссылки — автоматически в конец условия
        task = Task.objects.create(
            text_latex='См.\\ рисунок \\taskpic{1} и \\taskpic{3}.')
        task.images.create(image='task_images/a.png', order=10)
        task.images.create(image='task_images/b.png', order=20)
        tex = task_to_tex(make_item(self.worksheet, task))
        self.assertIn('рисунок \\taskpic{a.png}', tex)
        self.assertNotIn('\\taskpic{1}', tex)
        self.assertNotIn('\\taskpic{3}', tex)  # картинки №3 нет — удалена
        # b.png не упомянута в тексте — добавлена в конец условия
        self.assertEqual(tex.count('\\taskpic{b.png}'), 1)
        self.assertLess(tex.index('a.png'), tex.index('b.png'))

    def test_taskpic_ref_in_subitem(self):
        task = Task.objects.create(text_latex='Задача')
        task.images.create(image='task_images/a.png', order=10)
        TaskSubitem.objects.create(
            task=task, order=10, text_latex='пункт с рисунком \\taskpic{1}')
        tex = task_to_tex(make_item(self.worksheet, task))
        # Ссылка из подпункта учтена — в конец условия не дублируется
        self.assertEqual(tex.count('\\taskpic{a.png}'), 1)

    def test_collect_assets(self):
        import io
        import tempfile

        from django.core.files.base import ContentFile
        from django.test import override_settings
        from PIL import Image

        from .services import collect_assets

        buf = io.BytesIO()
        Image.new('RGB', (10, 10), 'white').save(buf, format='PNG')
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MEDIA_ROOT=tmp):
                task = Task.objects.create(text_latex='С файлом')
                image = task.images.create(order=10)
                image.image.save('схема.png', ContentFile(buf.getvalue()),
                                 save=True)
                item = make_item(self.worksheet, task)
                assets = collect_assets(self.worksheet)
                hidden = collect_assets(self.worksheet, exclude_ids={item.pk})
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]['filename'], image.filename)
        self.assertTrue(assets[0]['content_base64'])
        self.assertEqual(hidden, [])

    def test_header_escaping(self):
        worksheet = Worksheet.objects.create(
            title='Проценты & дроби 50%', grade_label='7_класс',
            owner=self.teacher)
        tex = worksheet_to_tex(worksheet, 'student')
        self.assertIn(r'Проценты \& дроби 50\%', tex)
        self.assertIn(r'7\_класс', tex)


class BeamerGenerationTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = Worksheet.objects.create(
            title='Дроби & проценты', grade_label='8 класс',
            subtitle='Осень', author_name='И. Иванов', owner=self.teacher)

    def test_preamble_defaults(self):
        tex = worksheet_to_beamer(self.worksheet)
        self.assertIn(
            '\\documentclass[aspectratio=169,12pt]{beamer}', tex)
        self.assertIn(
            '\\usepackage[theme=light,content=problems,reveal=click,'
            'items=all,itemflow=stack,font=school,stars,footer]{egorbeamer}', tex)
        self.assertIn(
            '\\egortitle{Дроби \\& проценты}{8 класс}{И. Иванов}[{Осень}]',
            tex)
        self.assertTrue(tex.strip().endswith('\\end{document}'))

    def test_option_overrides_and_unknowns(self):
        tex = worksheet_to_beamer(
            self.worksheet, theme='night', aspect='43', size='14pt',
            content='solutions', reveal='show', stars=False, footer=False)
        self.assertIn('\\documentclass[aspectratio=43,14pt]{beamer}', tex)
        self.assertIn(
            '\\usepackage[theme=night,content=solutions,reveal=show,'
            'items=all,itemflow=stack,font=school,nostars,nofooter]{egorbeamer}', tex)
        tex = worksheet_to_beamer(
            self.worksheet, theme='grid', content='solutions', reveal='end',
            items='click', itemflow='solo', font='cm')
        self.assertIn(
            '\\usepackage[theme=grid,content=solutions,reveal=end,'
            'items=click,itemflow=solo,font=cm,stars,footer]{egorbeamer}', tex)
        opts = normalize_beamer_options(
            theme='paper', size='20pt', reveal='end', items='maybe',
            itemflow='bounce', font='comic')
        self.assertEqual(opts['theme'], 'light')
        self.assertEqual(opts['size'], '12pt')
        self.assertEqual(opts['reveal'], 'end')
        self.assertEqual(opts['items'], 'all')
        self.assertEqual(opts['itemflow'], 'stack')
        self.assertEqual(opts['font'], 'school')

    def test_rubric_task_text_and_numbering(self):
        make_rubric(self.worksheet, 'Разминка', order=5, note='Устно')
        task = Task.objects.create(
            text_latex='Вычислите $1+1$.', answer_latex='2',
            solution_latex='Складываем.', stars=2, created_by=self.teacher)
        WorksheetItem.objects.create(
            worksheet=self.worksheet, task=task, order=10)
        WorksheetItem.objects.create(
            worksheet=self.worksheet, order=15,
            text_latex='Вспомните правило.', text_style='memo')
        tex = worksheet_to_beamer(self.worksheet)
        self.assertIn('\\egorsection{Разминка}[{Устно}]', tex)
        self.assertIn(
            '\\begin{frame}[fragile,t,label=egortask-1]{1.\\ \\egorstars{2}}',
            tex)
        self.assertIn('\\egortask{1}', tex)
        self.assertIn('Вычислите $1+1$.', tex)
        self.assertIn('\\egoranswer{%', tex)
        self.assertIn('\\egorsolution{%', tex)
        self.assertIn('\\egorappendix', tex)
        self.assertIn('\\egorworkarea', tex)
        self.assertLess(tex.find('\\egorworkarea'), tex.find('\\egoranswer'))
        self.assertIn('\\begin{frame}[fragile,t]', tex)
        self.assertIn('\\parbox[c][\\textheight][c]', tex)
        self.assertIn('Памятка', tex)
        self.assertEqual(tex.count('\\begin{frame}'), 2)
        self.assertEqual(tex.count('\\egortitle'), 1)
        self.assertEqual(tex.count('\\egorsection'), 1)

    def test_optional_args_protect_brackets(self):
        self.worksheet.subtitle = 'Тема [часть 1]'
        self.worksheet.save(update_fields=['subtitle'])
        make_rubric(self.worksheet, 'Раздел', order=1, note='см. [стр. 4]')
        task = Task.objects.create(text_latex='Вычислите.', created_by=self.teacher)
        make_item(self.worksheet, task)
        tex = worksheet_to_beamer(self.worksheet)
        self.assertIn('\\egortitle{Дроби \\& проценты}{8 класс}{И. Иванов}'
                      '[{Тема [часть 1]}]', tex)
        self.assertIn('\\egorsection{Раздел}[{см. [стр. 4]}]', tex)

    def test_task_frame_is_fragile_for_verbatim(self):
        task = Task.objects.create(
            text_latex=r'Команда \verb|\frac|.', created_by=self.teacher)
        make_item(self.worksheet, task)
        tex = worksheet_to_beamer(self.worksheet)
        self.assertIn('\\begin{frame}[fragile,t,label=egortask-1]{1.}', tex)
        self.assertIn(r'\verb|\frac|', tex)

    def test_solution_frame_can_break(self):
        task = Task.objects.create(
            text_latex='Вычислите.', solution_latex='Длинное решение.',
            created_by=self.teacher)
        make_item(self.worksheet, task)
        tex = worksheet_to_beamer(
            self.worksheet, content='solutions', reveal='show')
        self.assertIn(
            '\\begin{frame}[fragile,t,allowframebreaks,label=egortask-1]',
            tex)
        tex_click = worksheet_to_beamer(
            self.worksheet, content='solutions', reveal='click')
        self.assertNotIn('allowframebreaks', tex_click)

    def test_subitems_and_taskpic(self):
        task = Task.objects.create(text_latex='См. \\taskpic{1}', columns=2)
        TaskSubitem.objects.create(
            task=task, order=10, text_latex='$1+1$', answer_latex='2')
        TaskSubitem.objects.create(
            task=task, order=20, text_latex='$2+2$', answer_latex='4')
        task.images.create(image='task_images/pic.png', order=10)
        make_item(self.worksheet, task)
        tex = worksheet_to_beamer(self.worksheet)
        self.assertIn('\\taskpic{pic.png}', tex)
        self.assertNotIn('\\taskpic{1}', tex)
        self.assertIn('\\item[{а)}] $1+1$;', tex)
        self.assertIn('\\item[{б)}] $2+2$.', tex)
        self.assertIn('\\begin{egoritems}[2]', tex)
        self.assertIn('а)~2', tex)
        self.assertIn('б)~4', tex)

    def test_empty_rubric_dropped_and_hidden_items(self):
        make_rubric(self.worksheet, 'Пустая', order=1)
        task = Task.objects.create(text_latex='Задача', created_by=self.teacher)
        item = WorksheetItem.objects.create(
            worksheet=self.worksheet, task=task, order=10)
        tex = worksheet_to_beamer(self.worksheet, exclude_ids={item.pk})
        self.assertNotIn('\\egorsection{Пустая}', tex)
        self.assertNotIn('Задача', tex)
        self.assertIn('\\egortitle', tex)

    def test_collect_beamer_assets_includes_sty(self):
        from .services import (EGORBEAMER_GRID_STY, EGORBEAMER_STY,
                               collect_beamer_assets)
        assets = collect_beamer_assets(self.worksheet)
        self.assertEqual(assets[0]['filename'], 'egorbeamer.sty')
        self.assertEqual(assets[1]['filename'], 'egorbeamer-grid.sty')
        self.assertTrue(assets[0]['content_base64'])
        self.assertTrue(EGORBEAMER_STY.is_file())
        self.assertTrue(EGORBEAMER_GRID_STY.is_file())

    def test_collect_beamer_assets_rejects_too_many_images(self):
        from .services import (BEAMER_IMAGE_ASSET_LIMIT, collect_beamer_assets)
        fake = [{'filename': f'p{i}.png', 'content_base64': 'eA=='}
                for i in range(BEAMER_IMAGE_ASSET_LIMIT + 1)]
        with mock.patch('worksheets.services.collect_assets', return_value=fake):
            with self.assertRaises(LatexCompileError) as ctx:
                collect_beamer_assets(self.worksheet)
        self.assertIn('картинок', str(ctx.exception))

    def test_beamer_filename(self):
        self.worksheet.pdf_basename = 'alg8-drobi'
        self.worksheet.save()
        self.assertEqual(
            self.worksheet.beamer_filename(), 'alg8-drobi-prezentaciya.pdf')


class WorksheetViewTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.other_teacher = make_teacher('teacher2')
        self.student = make_student(self.teacher)
        self.worksheet = make_worksheet(self.teacher)

    def login_teacher(self):
        self.client.login(username='teacher1', password='pass12345')

    def test_builder_owner_only(self):
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.get(
            reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertEqual(response.status_code, 404)

    def test_builder_renders(self):
        self.login_teacher()
        from problems.models import TaskSubitem
        make_rubric(self.worksheet, 'Разминка', order=5)
        item = self.worksheet.ordered_items()[1]
        TaskSubitem.objects.create(
            task=item.task, order=10, text_latex='подпункт а')
        WorksheetItem.objects.create(
            worksheet=self.worksheet, order=99, text_latex='Текст-вставка')
        response = self.client.get(
            reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertContains(response, 'Разминка')
        self.assertContains(response, 'подпункт а')
        self.assertContains(response, 'Текст-вставка')
        self.assertContains(response, 'Дублировать')
        self.assertContains(response, 'data-neuro="apply-answers"')
        self.assertContains(response, 'data-neuro="apply-all"')
        self.assertContains(response, 'data-no-answer="1"')
        self.assertContains(response, 'Дописать AI-ответ к решениям')
        self.assertContains(response, 'Презентация')
        self.assertContains(response, 'Собрать презентацию')
        self.assertContains(response, reverse(
            'worksheet_beamer_editor', args=[self.worksheet.pk]))
        self.assertContains(response, 'Добавить AI-решения и ответ')
        self.assertNotContains(response, 'без ответа')
        self.assertContains(response, 'js/neuro.js')

    def test_add_and_move_and_remove_task(self):
        self.login_teacher()
        task = Task.objects.create(text_latex='Новая задача')
        self.client.post(
            reverse('worksheet_add_task', args=[self.worksheet.pk]),
            {'task_id': task.pk})
        items = list(self.worksheet.ordered_items())
        self.assertEqual(items[-1].task, task)

        self.client.post(reverse(
            'worksheet_move_item',
            args=[self.worksheet.pk, items[-1].pk, 'up']))
        items2 = list(self.worksheet.ordered_items())
        self.assertEqual(items2[1].task, task)

        self.client.post(reverse(
            'worksheet_remove_item', args=[self.worksheet.pk, items2[1].pk]))
        # Мягкое удаление: элемент скрыт, но остаётся до следующего удаления
        self.assertEqual(self.worksheet.ordered_items().count(), 2)
        self.assertEqual(self.worksheet.items.count(), 3)

    def test_reorder(self):
        self.login_teacher()
        items = list(self.worksheet.ordered_items())
        ids = ','.join(str(i.pk) for i in reversed(items))
        response = self.client.post(
            reverse('worksheet_reorder', args=[self.worksheet.pk]),
            {'order': ids})
        self.assertEqual(response.status_code, 200)
        new_items = list(self.worksheet.ordered_items())
        self.assertEqual([i.pk for i in new_items],
                         [i.pk for i in reversed(items)])

    def test_list_filters_and_sort(self):
        from problems.models import Topic
        self.login_teacher()
        topic = Topic.objects.create(name='Уравнения')
        # Тема у самого листка
        ws_manual = make_worksheet(self.teacher, title='А-листок')
        ws_manual.grade = 8
        ws_manual.save()
        ws_manual.topics.add(topic)
        # Тема у задачи листка
        ws_by_task = make_worksheet(self.teacher, title='Б-листок')
        ws_by_task.ordered_items()[0].task.topics.add(topic)

        url = reverse('worksheet_list')
        response = self.client.get(url, {'topic': topic.pk})
        titles = [w.title for w in response.context['worksheets']]
        self.assertIn('А-листок', titles)
        self.assertIn('Б-листок', titles)
        self.assertNotIn(self.worksheet.title, titles)

        response = self.client.get(url, {'grade': '8'})
        titles = [w.title for w in response.context['worksheets']]
        self.assertEqual(titles, ['А-листок'])

        response = self.client.get(url, {'order': 'title'})
        titles = [w.title for w in response.context['worksheets']]
        self.assertEqual(titles, sorted(titles))

        # Невалидные параметры не роняют страницу
        response = self.client.get(url, {
            'order': 'hack', 'created_from': 'garbage', 'grade': 'x'})
        self.assertEqual(response.status_code, 200)

    def test_rename(self):
        self.login_teacher()
        response = self.client.post(
            reverse('worksheet_rename', args=[self.worksheet.pk]),
            {'title': 'Новое имя'})
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.worksheet.refresh_from_db()
        self.assertEqual(self.worksheet.title, 'Новое имя')
        # Пустое имя не сохраняется
        self.client.post(
            reverse('worksheet_rename', args=[self.worksheet.pk]),
            {'title': '  '})
        self.worksheet.refresh_from_db()
        self.assertEqual(self.worksheet.title, 'Новое имя')

    def test_copy_view(self):
        self.login_teacher()
        response = self.client.post(
            reverse('worksheet_copy', args=[self.worksheet.pk]))
        copy = Worksheet.objects.get(title__endswith='(копия)')
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[copy.pk]))
        self.assertEqual(copy.items.count(), self.worksheet.items.count())

    def test_copy_with_overrides(self):
        from problems.models import Topic
        self.login_teacher()
        topic = Topic.objects.create(name='Алгебра')
        self.worksheet.topics.add(topic)
        response = self.client.post(
            reverse('worksheet_copy', args=[self.worksheet.pk]), {
                'title': 'Копия для 9-х',
                'grade_label': '9 класс',
                'grade': '9',
                'pdf_basename': 'alg9-kv_ur',
            })
        copy = Worksheet.objects.get(title='Копия для 9-х')
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[copy.pk]))
        self.assertEqual(copy.grade_label, '9 класс')
        self.assertEqual(copy.grade, 9)
        self.assertEqual(copy.pdf_basename, 'alg9-kv_ur')
        self.assertEqual(list(copy.topics.all()), [topic])
        self.assertEqual(copy.items.count(), self.worksheet.items.count())

    def test_pdf_filename(self):
        from problems.models import Topic
        self.worksheet.grade = 8
        self.worksheet.title = 'Квадратные уравнения'
        self.worksheet.save()
        self.worksheet.topics.add(Topic.objects.get(code='ALG'))
        self.assertEqual(self.worksheet.pdf_filename('student'), 'alg8-kv_ur.pdf')
        self.assertEqual(
            self.worksheet.pdf_filename('answers'), 'alg8-kv_ur-otvety.pdf')
        self.assertEqual(
            self.worksheet.pdf_filename('teacher'), 'alg8-kv_ur-uchitel.pdf')
        # Ручное имя приоритетнее автогенерации
        self.worksheet.pdf_basename = 'custom_name'
        self.assertEqual(self.worksheet.pdf_filename('student'), 'custom_name.pdf')
        # Без темы и класса — безопасный fallback
        other = Worksheet.objects.create(title='Тест', owner=self.teacher)
        self.assertEqual(other.pdf_filename('student'), 'list-te.pdf')

    def test_delete(self):
        # Чужой учитель удалить не может
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.post(
            reverse('worksheet_delete', args=[self.worksheet.pk]))
        self.assertEqual(response.status_code, 404)
        # Владелец удаляет, редирект в список
        self.login_teacher()
        response = self.client.post(
            reverse('worksheet_delete', args=[self.worksheet.pk]))
        self.assertRedirects(response, reverse('worksheet_list'))
        self.assertFalse(
            Worksheet.objects.filter(pk=self.worksheet.pk).exists())

    def test_bulk_delete(self):
        other = Worksheet.objects.create(
            title='Чужой', owner=self.other_teacher)
        second = Worksheet.objects.create(title='Второй', owner=self.teacher)
        self.login_teacher()
        response = self.client.post(reverse('worksheet_bulk_delete'), {
            'ids': [self.worksheet.pk, second.pk, other.pk]})
        self.assertRedirects(response, reverse('worksheet_list'))
        # Свои удалены, чужой листок не тронут
        self.assertFalse(Worksheet.objects.filter(
            pk__in=[self.worksheet.pk, second.pk]).exists())
        self.assertTrue(Worksheet.objects.filter(pk=other.pk).exists())

    def test_bulk_update_without_fields_does_not_delete(self):
        self.login_teacher()
        response = self.client.post(reverse('worksheet_bulk_update'), {
            'ids': [self.worksheet.pk]})
        self.assertRedirects(response, reverse('worksheet_list'))
        self.assertTrue(Worksheet.objects.filter(pk=self.worksheet.pk).exists())

    def test_bulk_assign(self):
        from problems.models import Topic
        topic = Topic.objects.create(name='Геометрия')
        second = Worksheet.objects.create(title='Второй', owner=self.teacher)
        self.login_teacher()
        response = self.client.post(reverse('worksheet_bulk_update'), {
            'ids': [self.worksheet.pk, second.pk],
            'grade': '8', 'topic_id': topic.pk, 'apply': '1'})
        self.assertRedirects(response, reverse('worksheet_list'))
        for ws in (self.worksheet, second):
            ws.refresh_from_db()
            self.assertEqual(ws.grade, 8)
            self.assertIn(topic, ws.topics.all())

    def test_quick_update(self):
        from problems.models import Topic
        self.login_teacher()
        topic = Topic.objects.create(name='Уравнения')
        url = reverse('worksheet_quick_update', args=[self.worksheet.pk])

        # Класс: сохранение и сброс, ответ JSON для fetch-автосохранения
        response = self.client.post(
            url, {'grade': '8'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.worksheet.refresh_from_db()
        self.assertEqual(self.worksheet.grade, 8)
        self.client.post(
            url, {'grade': ''}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.worksheet.refresh_from_db()
        self.assertIsNone(self.worksheet.grade)
        # Недопустимый класс отклоняется
        response = self.client.post(
            url, {'grade': '99'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)

        # Подзаголовок (grade_label) — для inline-редактирования в конструкторе
        response = self.client.post(
            url, {'grade_label': '9 класс'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.worksheet.refresh_from_db()
        self.assertEqual(self.worksheet.grade_label, '9 класс')

        # Темы: назначение и полное снятие (маркер topics_submitted)
        before = self.worksheet.updated_at
        response = self.client.post(
            url, {'topics_submitted': '1', 'topics': [str(topic.pk)]})
        self.assertRedirects(response, reverse('worksheet_list'))
        self.assertEqual(list(self.worksheet.topics.all()), [topic])
        # Смена тем обновляет дату изменения (M2M не трогает auto_now сам)
        self.worksheet.refresh_from_db()
        self.assertGreater(self.worksheet.updated_at, before)
        self.client.post(url, {'topics_submitted': '1'})
        self.assertEqual(self.worksheet.topics.count(), 0)

    def test_topics_dialog_shows_deep_tree(self):
        # Тема-«внук» попадает в JSON каталога виджета
        from problems.models import Topic
        root = Topic.objects.create(name='Тестовое дерево')
        child = Topic.objects.create(name='Ветвь уравнений', parent=root)
        grand = Topic.objects.create(name='Квадратные тест', parent=child)
        self.worksheet.topics.add(grand)
        self.login_teacher()
        response = self.client.get(reverse('worksheet_list'))
        ws = response.context['worksheets']
        self.assertTrue(any(grand.pk in json.loads(w.taxonomy_json)['topics']
                            for w in ws))

    def test_remove_item_soft_delete_and_undo(self):
        self.login_teacher()
        item = self.worksheet.items.order_by('order').first()
        self.client.post(reverse(
            'worksheet_remove_item', args=[self.worksheet.pk, item.pk]))
        item.refresh_from_db()
        self.assertIsNotNone(item.deleted_at)
        # Скрыт из конструктора и из .tex, но плашка отмены на месте
        response = self.client.get(
            reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertNotIn(item.pk,
                         [r['item'].pk for r in response.context['rows']])
        self.assertContains(response, 'undo-bar')
        self.assertContains(response, 'ws-toast-src')
        self.assertContains(response, 'Задача удалена из листка.')
        self.assertNotIn(item.task.text_latex,
                         worksheet_to_tex(self.worksheet, 'student'))
        # «Отменить» возвращает элемент
        restore = self.client.post(reverse(
            'worksheet_restore_item', args=[self.worksheet.pk]), follow=True)
        item.refresh_from_db()
        self.assertIsNone(item.deleted_at)
        self.assertContains(restore, 'Задача возвращена в листок.')

    def test_second_remove_purges_previous_trash(self):
        # Отмена одноуровневая: новое удаление затирает прежний «мусор»
        self.login_teacher()
        first, second = list(self.worksheet.items.order_by('order'))
        self.client.post(reverse(
            'worksheet_remove_item', args=[self.worksheet.pk, first.pk]))
        self.client.post(reverse(
            'worksheet_remove_item', args=[self.worksheet.pk, second.pk]))
        self.assertFalse(
            self.worksheet.items.filter(pk=first.pk).exists())
        second.refresh_from_db()
        self.assertIsNotNone(second.deleted_at)

    def test_readd_restores_trashed_task_instead_of_duplicate(self):
        # Повторное добавление задачи из корзины восстанавливает элемент,
        # «Отменить» после этого не плодит дубль
        self.login_teacher()
        item = self.worksheet.items.order_by('order').first()
        task = item.task
        self.client.post(reverse(
            'worksheet_remove_item', args=[self.worksheet.pk, item.pk]))
        self.client.post(reverse(
            'worksheet_add_task', args=[self.worksheet.pk]),
            {'task_id': task.pk})
        item.refresh_from_db()
        self.assertIsNone(item.deleted_at)
        self.assertEqual(
            self.worksheet.items.filter(task=task).count(), 1)
        self.client.post(reverse(
            'worksheet_restore_item', args=[self.worksheet.pk]))
        self.assertEqual(
            self.worksheet.items.filter(
                task=task, deleted_at__isnull=True).count(), 1)

    def test_duplicate_skips_deleted(self):
        item = self.worksheet.items.order_by('order').first()
        item.deleted_at = timezone.now()
        item.save(update_fields=['deleted_at'])
        copy = self.worksheet.duplicate()
        self.assertEqual(copy.items.count(), 1)

    def test_add_text_and_edit(self):
        self.login_teacher()
        self.client.post(
            reverse('worksheet_add_element', args=[self.worksheet.pk]),
            {'kind': 'text', 'text_latex': 'Пояснение к листку'})
        item = self.worksheet.items.get(task__isnull=True)
        self.assertEqual(item.text_latex, 'Пояснение к листку')
        self.client.post(
            reverse('worksheet_edit_text',
                    args=[self.worksheet.pk, item.pk]),
            {'text_latex': 'Новый текст'})
        item.refresh_from_db()
        self.assertEqual(item.text_latex, 'Новый текст')
        # Смена стиля текста сохраняется, мусорное значение игнорируется
        self.client.post(
            reverse('worksheet_edit_text',
                    args=[self.worksheet.pk, item.pk]),
            {'text_latex': 'Новый текст', 'text_style': 'memo'})
        item.refresh_from_db()
        self.assertEqual(item.text_style, 'memo')
        self.client.post(
            reverse('worksheet_edit_text',
                    args=[self.worksheet.pk, item.pk]),
            {'text_latex': 'Новый текст', 'text_style': 'hacked'})
        item.refresh_from_db()
        self.assertEqual(item.text_style, 'memo')
        # Переключатель стиля отображается в конструкторе
        response = self.client.get(
            reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertContains(response, 'style-seg')
        self.assertContains(response, 'name="text_style"')

    def test_add_edit_delete_rubric(self):
        self.login_teacher()
        self.client.post(
            reverse('worksheet_add_element', args=[self.worksheet.pk]),
            {'kind': 'rubric', 'rubric': 'Разминка', 'rubric_note': 'устно'})
        item = self.worksheet.items.get(task__isnull=True)
        self.assertTrue(item.is_rubric)
        self.assertEqual(item.rubric, 'Разминка')
        self.assertEqual(item.rubric_note, 'устно')
        # Рубрика добавляется в конец
        self.assertEqual(list(self.worksheet.ordered_items())[-1].pk, item.pk)

        self.client.post(
            reverse('worksheet_set_rubric',
                    args=[self.worksheet.pk, item.pk]),
            {'rubric': 'Основная часть', 'rubric_note': ''})
        item.refresh_from_db()
        self.assertEqual(item.rubric, 'Основная часть')
        self.assertEqual(item.rubric_note, '')

        self.client.post(
            reverse('worksheet_remove_item',
                    args=[self.worksheet.pk, item.pk]))
        # Мягкое удаление: рубрика исчезает из конструктора и .tex
        self.assertNotIn(
            item.pk, [i.pk for i in self.worksheet.ordered_items()])

    def test_item_settings(self):
        self.login_teacher()
        from problems.models import TaskSubitem
        item = self.worksheet.ordered_items()[0]
        s1 = TaskSubitem.objects.create(
            task=item.task, order=10, text_latex='а-пункт')
        TaskSubitem.objects.create(
            task=item.task, order=20, text_latex='б-пункт')
        self.client.post(
            reverse('worksheet_item_settings',
                    args=[self.worksheet.pk, item.pk]),
            {'stars': '2', 'columns': '3', 'subitems': [str(s1.pk)]})
        item.refresh_from_db()
        self.assertEqual(item.stars_override, 2)
        self.assertEqual(item.columns_override, 3)
        self.assertFalse(item.all_subitems)
        self.assertEqual([s.pk for s in item.selected_subitems()], [s1.pk])

    def test_autosave_returns_json(self):
        self.login_teacher()
        item = self.worksheet.ordered_items()[0]
        response = self.client.post(
            reverse('worksheet_item_settings',
                    args=[self.worksheet.pk, item.pk]),
            {'stars': '2'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        item.refresh_from_db()
        self.assertEqual(item.stars_override, 2)

        # Ошибка (пустое название) → JSON с ok=False и статус 400
        response = self.client.post(
            reverse('worksheet_rename', args=[self.worksheet.pk]),
            {'title': ' '}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])

    @mock.patch('worksheets.services.compile_latex',
                return_value=b'%PDF-1.5 fake')
    def test_pdf_generation_and_cache(self, mocked):
        self.login_teacher()
        url = reverse('worksheet_pdf', args=[self.worksheet.pk])
        response = self.client.get(url, {'variant': 'student'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(mocked.call_count, 1)

        # Повторный запрос без изменений — из кэша
        response = self.client.get(url, {'variant': 'student'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked.call_count, 1)

        # Изменение листка → перегенерация
        make_rubric(self.worksheet, 'Новая рубрика', order=5)
        response = self.client.get(url, {'variant': 'student'})
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(
            WorksheetPdf.objects.filter(worksheet=self.worksheet).count(), 1)

    def test_pdf_editor_page(self):
        self.login_teacher()
        response = self.client.get(
            reverse('worksheet_pdf_editor', args=[self.worksheet.pk]),
            {'variant': 'answers'})
        self.assertContains(response, 'id="tex-source"')
        self.assertContains(response, '\\documentclass')
        self.assertContains(response, 'С ответами')
        # LaTeX API настроен — все три шрифта доступны по умолчанию
        self.assertContains(response, 'data-value="cm"')
        self.assertContains(response, 'data-value="school"')
        self.assertContains(response, 'data-value="palatino"')
        # Переключатель режима диагностики (опция diagn пакета egor)
        self.assertContains(response, 'data-switch="diagn"')
        # Для окружения без шрифтов выбор сужается настройкой
        with self.settings(PDF_EDITOR_FONTS=['cm']):
            response = self.client.get(
                reverse('worksheet_pdf_editor', args=[self.worksheet.pk]))
            self.assertNotContains(response, 'data-value="palatino"')
        # Чужой листок недоступен
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.get(
            reverse('worksheet_pdf_editor', args=[self.worksheet.pk]))
        self.assertEqual(response.status_code, 404)

    @mock.patch('worksheets.views.compile_latex',
                return_value=b'%PDF-1.5 fake')
    def test_pdf_editor_compile(self, mocked):
        self.login_teacher()
        url = reverse('worksheet_pdf_compile', args=[self.worksheet.pk])
        response = self.client.post(url, {'tex': r'\documentclass{article}'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(
            mocked.call_args.args[0], r'\documentclass{article}')
        # Черновая сборка не пишет в кэш PDF
        self.assertEqual(
            WorksheetPdf.objects.filter(worksheet=self.worksheet).count(), 0)

        # Пустой документ — 400
        response = self.client.post(url, {'tex': '  '})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])

        # Слишком большой исходник — 400 без похода в LaTeX API
        from worksheets.views import PDF_EDITOR_TEX_LIMIT
        calls_before = mocked.call_count
        response = self.client.post(
            url, {'tex': 'x' * (PDF_EDITOR_TEX_LIMIT + 1)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(mocked.call_count, calls_before)

    @mock.patch('worksheets.views.collect_assets')
    @mock.patch('worksheets.views.compile_latex', return_value=b'%PDF-1.5')
    def test_pdf_editor_compile_locked(self, mocked, mocked_assets):
        # Пока идёт сборка пользователя, вторая параллельная — 429.
        # Lock хранится в БД (PdfCompileLock) — общий для всех процессов
        from worksheets.models import PdfCompileLock
        self.login_teacher()
        url = reverse('worksheet_pdf_compile', args=[self.worksheet.pk])
        PdfCompileLock.objects.create(user=self.teacher)
        response = self.client.post(url, {'tex': r'\documentclass{article}'})
        self.assertEqual(response.status_code, 429)
        mocked.assert_not_called()
        mocked_assets.assert_not_called()
        # Протухший lock (упавший процесс) снимается автоматически
        from worksheets.views import PDF_EDITOR_LOCK_TIMEOUT
        PdfCompileLock.objects.update(
            created_at=timezone.now() - PDF_EDITOR_LOCK_TIMEOUT * 2)
        response = self.client.post(url, {'tex': r'\documentclass{article}'})
        self.assertEqual(response.status_code, 200)
        # После завершения lock снят — сборка снова доступна
        self.assertEqual(PdfCompileLock.objects.count(), 0)
        response = self.client.post(url, {'tex': r'\documentclass{article}'})
        self.assertEqual(response.status_code, 200)

    def test_beamer_editor_page(self):
        self.login_teacher()
        response = self.client.get(
            reverse('worksheet_beamer_editor', args=[self.worksheet.pk]))
        self.assertContains(response, 'id="tex-source"')
        self.assertContains(response, '\\documentclass[aspectratio=169,12pt]{beamer}')
        self.assertContains(response, 'data-switch="theme"')
        self.assertContains(response, 'data-value="grid"')
        self.assertContains(response, 'data-switch="reveal"')
        self.assertContains(response, 'data-value="end"')
        self.assertContains(response, 'data-switch="items"')
        self.assertContains(response, 'data-switch="itemflow"')
        self.assertContains(response, 'data-value="stack"')
        self.assertContains(response, 'data-switch="font"')
        self.assertContains(response, 'data-value="school"')
        self.assertContains(response, 'id="sidebar-compile-btn"')
        self.assertNotContains(response, 'data-value="paper"')
        self.assertNotContains(response, 'Тетрадь')
        self.assertContains(response, 'beamer_editor.js')
        self.assertContains(response, self.worksheet.beamer_filename())
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.get(
            reverse('worksheet_beamer_editor', args=[self.worksheet.pk]))
        self.assertEqual(response.status_code, 404)

    @mock.patch('worksheets.views.compile_latex',
                return_value=b'%PDF-1.5 fake')
    def test_beamer_editor_compile(self, mocked):
        self.login_teacher()
        url = reverse('worksheet_beamer_compile', args=[self.worksheet.pk])
        response = self.client.post(url, {'tex': r'\documentclass{beamer}'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(
            mocked.call_args.args[0], r'\documentclass{beamer}')
        assets = mocked.call_args.kwargs.get('assets') or []
        self.assertTrue(any(a['filename'] == 'egorbeamer.sty' for a in assets))
        self.assertTrue(
            any(a['filename'] == 'egorbeamer-grid.sty' for a in assets))
        self.assertEqual(
            WorksheetPdf.objects.filter(worksheet=self.worksheet).count(), 0)
        response = self.client.post(url, {'tex': '  '})
        self.assertEqual(response.status_code, 400)

    @mock.patch('worksheets.views.collect_beamer_assets',
                side_effect=LatexCompileError('Слишком много картинок'))
    @mock.patch('worksheets.views.compile_latex', return_value=b'%PDF-1.5')
    def test_beamer_editor_compile_too_many_images(self, mocked_compile, _assets):
        self.login_teacher()
        response = self.client.post(
            reverse('worksheet_beamer_compile', args=[self.worksheet.pk]),
            {'tex': r'\documentclass{beamer}'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('картинок', response.json()['message'])
        mocked_compile.assert_not_called()

    @mock.patch('worksheets.views.compile_latex',
                side_effect=LatexCompileError(
                    'Ошибка компиляции LaTeX.', log='! Undefined control'))
    def test_pdf_editor_compile_error(self, mocked):
        self.login_teacher()
        response = self.client.post(
            reverse('worksheet_pdf_compile', args=[self.worksheet.pk]),
            {'tex': r'\bad'})
        self.assertEqual(response.status_code, 502)
        data = response.json()
        self.assertFalse(data['ok'])
        self.assertIn('Undefined control', data['log'])

    @mock.patch('worksheets.services.compile_latex',
                return_value=b'%PDF-1.5 fake')
    def test_student_pdf_access(self, mocked):
        from assignments.models import Assignment
        Assignment.objects.create(
            worksheet=self.worksheet, student=self.student,
            assigned_by=self.teacher)
        self.client.login(username='student1', password='pass12345')
        url = reverse('worksheet_pdf', args=[self.worksheet.pk])
        response = self.client.get(url, {'variant': 'student'})
        self.assertEqual(response.status_code, 200)
        # Вариант с ответами ученику запрещён
        response = self.client.get(url, {'variant': 'teacher'})
        self.assertEqual(response.status_code, 403)


SAMPLE_TEX = r'''\documentclass[a5paper,10pt]{article}
\usepackage{egor}
\begin{document}
\bighead{Дроби \& проценты}{8 класс}{И. Иванов}[{Осень}]

\rubr{Разминка}[{Устно}]

\task{1}{0}{%
Вычислите $\frac{1}{2}+\frac{1}{3}$.%
}[{}][{$\frac56$}]

\plaintext{%
Дальше — письменно.%
}

\rubr{Основная часть}

\task{2}{2}{%
Найдите значение:%
}[{\item $2+2$; \item $3 \cdot [1+2]$.}][{а)~4; б)~9}][{Считаем в столбик.}]

\end{document}
'''


class ImportTexTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()

    def test_parse(self):
        from .import_tex import parse_tex
        parsed = parse_tex(SAMPLE_TEX)
        self.assertEqual(parsed['header']['title'], 'Дроби & проценты')
        self.assertEqual(parsed['header']['left'], '8 класс')
        self.assertEqual(parsed['header']['right'], 'И. Иванов')
        self.assertEqual(parsed['header']['subtitle'], 'Осень')
        kinds = [k for k, _ in parsed['elements']]
        self.assertEqual(kinds, ['rubric', 'task', 'text', 'rubric', 'task'])
        rubric = parsed['elements'][0][1]
        self.assertEqual(rubric['rubric'], 'Разминка')
        self.assertEqual(rubric['note'], 'Устно')
        task1 = parsed['elements'][1][1]
        self.assertEqual(task1['stars'], 1)
        self.assertEqual(task1['text'], 'Вычислите $\\frac{1}{2}+\\frac{1}{3}$.')
        self.assertEqual(task1['answer'], '$\\frac56$')
        task2 = parsed['elements'][4][1]
        self.assertEqual(task2['columns'], 2)
        # Скобка ] внутри {…} не ломает разбор опциональных аргументов;
        # хвостовые «;» и «.» срезаются — их расставляет система
        self.assertEqual(task2['subitems'],
                         ['$2+2$', '$3 \\cdot [1+2]$'])
        self.assertEqual(task2['solution'], 'Считаем в столбик.')

    def test_parse_text_styles(self):
        # \ruletext/\lighttext/\memotext импортируются со своим стилем
        from .import_tex import create_worksheet, parse_tex
        tex = ('\\begin{document}\n'
               '\\ruletext{Правило.}\n'
               '\\lighttext{Замечание.}\n'
               '\\memotext{Запомни!}\n'
               '\\plaintext{Просто текст.}\n'
               '\\end{document}')
        parsed = parse_tex(tex)
        styles = [data['style'] for kind, data in parsed['elements']]
        self.assertEqual(styles, ['rule', 'light', 'memo', 'plain'])
        worksheet, _ = create_worksheet(parsed, owner=self.teacher)
        saved = [item.text_style for item in worksheet.ordered_items()]
        self.assertEqual(saved, ['rule', 'light', 'memo', 'plain'])

    def test_create_and_dedup(self):
        from .import_tex import create_worksheet, parse_tex
        existing = Task.objects.create(
            text_latex='Вычислите  $\\frac{1}{2}+\\frac{1}{3}$.',
            created_by=self.teacher)
        parsed = parse_tex(SAMPLE_TEX)
        worksheet, missing = create_worksheet(parsed, owner=self.teacher)
        self.assertEqual(missing, [])
        self.assertEqual(worksheet.title, 'Дроби & проценты')
        self.assertEqual(worksheet.grade_label, '8 класс')
        items = list(worksheet.ordered_items())
        self.assertEqual(len(items), 5)
        # Первая задача найдена в базе (нормализация пробелов), вторая создана
        self.assertEqual(items[1].task_id, existing.pk)
        new_task = items[4].task
        self.assertEqual(new_task.stars, 2)
        self.assertEqual(new_task.subitems.count(), 2)
        self.assertEqual(Task.objects.count(), 2)

    def test_dedup_considers_subitems(self):
        from .import_tex import create_worksheet, find_existing_task, \
            parse_tex
        # Одинаковое основное условие, разные подпункты — разные задачи
        base = Task.objects.create(
            text_latex='Решите уравнение:', created_by=self.teacher)
        base.subitems.create(order=10, text_latex='$x^2=4$')
        base.subitems.create(order=20, text_latex='$x^2=9$')
        tex = ('\\begin{document}\n'
               '\\task{0}{0}{Решите уравнение:}'
               '[{\\item $x^2=16$; \\item $x^2=25$.}]\n'
               '\\end{document}')
        worksheet, _ = create_worksheet(parse_tex(tex), owner=self.teacher)
        new_task = worksheet.items.get(task__isnull=False).task
        self.assertNotEqual(new_task.pk, base.pk)
        # Полное совпадение (условие + подпункты) — задача находится
        self.assertEqual(
            find_existing_task('Решите уравнение:', ['$x^2=4$', '$x^2=9$']),
            base.pk)
        self.assertIsNone(
            find_existing_task('Решите уравнение:', ['$x^2=4$']))

    def test_dedup_ignores_subitem_trailing_punct(self):
        from .import_tex import create_worksheet, find_existing_task, \
            parse_tex
        # Старые записи без точки; новые предложения импортируются с точкой
        existing = Task.objects.create(
            text_latex='Докажите:', created_by=self.teacher)
        existing.subitems.create(order=10, text_latex='Докажите неравенство')
        tex = ('\\begin{document}\n'
               '\\task{0}{0}{Докажите:}'
               '[{\\item Докажите неравенство.}]\n'
               '\\end{document}')
        worksheet, _ = create_worksheet(parse_tex(tex), owner=self.teacher)
        self.assertEqual(worksheet.items.get().task_id, existing.pk)
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(
            find_existing_task('Докажите:', ['Докажите неравенство.']),
            existing.pk)

    def test_import_updates_existing_answer(self):
        # Горячее добавление ответа/решения к задаче, найденной в базе
        existing = Task.objects.create(
            text_latex='Вычислите  $\\frac{1}{2}+\\frac{1}{3}$.',
            created_by=self.teacher)
        self.client.login(username='teacher1', password='pass12345')
        self.client.post(reverse('worksheet_import'), {
            'tex': SAMPLE_TEX, 'action': 'create',
            'answer_1': '$5/6$', 'solution_1': 'Общий знаменатель 6.',
        })
        existing.refresh_from_db()
        self.assertEqual(existing.answer_latex, '$5/6$')
        self.assertEqual(existing.solution_latex, 'Общий знаменатель 6.')

    def test_round_trip(self):
        from .import_tex import create_worksheet, parse_tex
        parsed = parse_tex(SAMPLE_TEX)
        worksheet, _ = create_worksheet(parsed, owner=self.teacher)
        tex = worksheet_to_tex(worksheet, 'teacher')
        reparsed = parse_tex(tex)
        self.assertEqual(reparsed['header'], parsed['header'])
        self.assertEqual(
            [k for k, _ in reparsed['elements']],
            [k for k, _ in parsed['elements']])
        for (_, orig), (_, again) in zip(parsed['elements'],
                                         reparsed['elements']):
            if 'text' in orig:
                self.assertEqual(orig['text'], again['text'])
            if 'subitems' in orig:
                self.assertEqual(orig['subitems'], again['subitems'])

    def test_import_graphics(self):
        from .import_tex import create_worksheet, parse_tex
        tex = ('\\begin{document}\n'
               '\\task{0}{0}{%\n'
               'См.\\ рисунок \\includegraphics[width=4cm]{pic-a.png}, '
               'снова \\includegraphics{pic-a.png}, '
               '\\taskpic{pic-b.jpg} '
               'и \\includegraphics[height=6.5cm]{apo-math-wave11-pic1.pdf}.%\n}\n'
               '\\end{document}')
        parsed = parse_tex(tex)
        data = parsed['elements'][0][1]
        self.assertEqual(data['images'],
                         ['pic-a.png', 'pic-b.jpg', 'apo-math-wave11-pic1.pdf'])
        self.assertNotIn('includegraphics', data['text'])
        # Один файл — одна ссылка-номер, даже при повторном упоминании
        self.assertEqual(data['text'].count('\\taskpic{1}'), 2)
        self.assertIn('\\taskpic{2}', data['text'])
        self.assertIn('\\taskpic{3}', data['text'])  # PDF-графика — тоже

        worksheet, missing = create_worksheet(parsed, owner=self.teacher)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['files'],
                         ['pic-a.png', 'pic-b.jpg', 'apo-math-wave11-pic1.pdf'])
        self.assertEqual(missing[0]['task'],
                         worksheet.ordered_items()[0].task)

    def test_import_view(self):
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('worksheet_import')
        response = self.client.post(
            url, {'tex': SAMPLE_TEX, 'action': 'preview'})
        self.assertContains(response, 'новая')
        self.assertContains(response, 'Разминка')
        # В предпросмотре видны сами подпункты, а не только их количество
        self.assertContains(response, '$2+2$')
        # И поля назначений для новых задач
        self.assertContains(response, 'name="grade_1"')
        self.assertContains(response, 'name="answer_1"')
        # У задачи с подпунктами (индекс 4) — поля на каждый подпункт,
        # общих task-level полей нет
        self.assertContains(response, 'name="answer_4_0"')
        self.assertContains(response, 'name="solution_4_1"')
        self.assertNotContains(response, 'name="answer_4"')
        # Тумблер показа ответов и панель массовых действий
        self.assertContains(response, 'toggle-import-answers')
        self.assertContains(response, 'import-bulk-form')
        self.assertContains(response, 'Удалить из импорта')

        response = self.client.post(
            url, {'tex': SAMPLE_TEX, 'action': 'create'})
        worksheet = Worksheet.objects.get(owner=self.teacher)
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[worksheet.pk]))
        self.assertEqual(worksheet.items.count(), 5)

        response = self.client.post(
            url, {'tex': 'нет команд', 'action': 'preview'})
        self.assertContains(response, 'Ошибка разбора')

    def test_import_create_with_overrides(self):
        from problems.models import Topic
        from problems.rubricator import seed_rubricator
        seed_rubricator()
        topic = Topic.objects.create(name='Дроби')
        self.client.login(username='teacher1', password='pass12345')
        # Элемент с индексом 1 — первая задача (после рубрики «Разминка»)
        self.client.post(reverse('worksheet_import'), {
            'tex': SAMPLE_TEX, 'action': 'create',
            'grade_1': '8', 'topic_1': str(topic.pk), 'stars_1': '3',
            'answer_1': '5/6', 'solution_1': 'Общий знаменатель 6.',
        })
        worksheet = Worksheet.objects.get(owner=self.teacher)
        task = worksheet.items.filter(task__isnull=False).first().task
        self.assertEqual(task.grade_level, 8)
        self.assertEqual(
            list(task.grade_bands.values_list('code', flat=True)), ['GRADE_8'])
        self.assertEqual(list(task.topics.all()), [topic])
        self.assertEqual(task.stars, 3)
        self.assertEqual(task.answer_latex, '5/6')
        self.assertEqual(task.solution_latex, 'Общий знаменатель 6.')

    def test_import_subitem_answers(self):
        # Ответы/решения по подпунктам сохраняются в новые TaskSubitem
        self.client.login(username='teacher1', password='pass12345')
        self.client.post(reverse('worksheet_import'), {
            'tex': SAMPLE_TEX, 'action': 'create',
            'answer_4_0': '4', 'solution_4_0': 'Сложение.',
            'answer_4_1': '9',
        })
        worksheet = Worksheet.objects.get(owner=self.teacher)
        task = worksheet.ordered_items()[4].task
        subs = list(task.subitems.all())
        self.assertEqual(subs[0].answer_latex, '4')
        self.assertEqual(subs[0].solution_latex, 'Сложение.')
        self.assertEqual(subs[1].answer_latex, '9')
        self.assertEqual(subs[1].solution_latex, '')

    def test_import_updates_existing_subitem_answers(self):
        # Горячая правка ответов подпунктов у задачи, найденной в базе
        existing = Task.objects.create(
            text_latex='Найдите значение:', created_by=self.teacher)
        existing.subitems.create(order=10, text_latex='$2+2$')
        existing.subitems.create(
            order=20, text_latex='$3 \\cdot [1+2]$', answer_latex='8')
        self.client.login(username='teacher1', password='pass12345')
        self.client.post(reverse('worksheet_import'), {
            'tex': SAMPLE_TEX, 'action': 'create',
            'answer_4_0': '4', 'answer_4_1': '9',
        })
        subs = list(existing.subitems.all())
        self.assertEqual(subs[0].answer_latex, '4')
        self.assertEqual(subs[1].answer_latex, '9')

    def test_import_skip_row(self):
        # Помеченная «удалить из импорта» задача не создаётся и не попадает
        # в листок
        self.client.login(username='teacher1', password='pass12345')
        self.client.post(reverse('worksheet_import'), {
            'tex': SAMPLE_TEX, 'action': 'create', 'skip_1': '1',
        })
        worksheet = Worksheet.objects.get(owner=self.teacher)
        self.assertEqual(worksheet.items.count(), 4)
        self.assertFalse(Task.objects.filter(
            text_latex__contains='\\frac{1}{2}').exists())
        # Пустое значение skip_N (флажок не взводился) ничего не пропускает
        Worksheet.objects.all().delete()
        self.client.post(reverse('worksheet_import'), {
            'tex': SAMPLE_TEX, 'action': 'create', 'skip_1': '',
        })
        worksheet = Worksheet.objects.get(owner=self.teacher)
        self.assertEqual(worksheet.items.count(), 5)

    def test_import_create_ignores_unknown_topic(self):
        # Поддельный/удалённый id темы не должен ронять создание (500)
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(reverse('worksheet_import'), {
            'tex': SAMPLE_TEX, 'action': 'create', 'topic_1': '99999',
        })
        self.assertEqual(response.status_code, 302)
        worksheet = Worksheet.objects.get(owner=self.teacher)
        task = worksheet.items.filter(task__isnull=False).first().task
        self.assertEqual(task.topics.count(), 0)

    def test_import_preview_has_neuro_controls(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(
            reverse('worksheet_import'), {'tex': SAMPLE_TEX,
                                          'action': 'preview'})
        self.assertContains(response, 'neuro-btn')
        self.assertContains(response, 'bulk-solve')
        self.assertContains(response, 'Добавить AI-решение')
        self.assertNotContains(response, '✨')
        # Исходные LaTeX-тексты задач для запросов генерации
        self.assertContains(response, 'import-solve-data')
        self.assertContains(response, reverse('task_neuro_solve'))
        from pathlib import Path
        from django.conf import settings
        js = (Path(settings.BASE_DIR) / 'static/js/import.js').read_text()
        self.assertIn('!String(value).trim()', js)

    def test_import_solve_endpoint(self):
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('worksheet_import_solve')
        drafts = {'answer': '4', 'solution': 'Сложение.',
                  'subitem_answers': [], 'subitem_solutions': []}
        with mock.patch('problems.neuro.solve_task',
                        return_value=drafts) as solve:
            response = self.client.post(
                url, {'text': '$2+2$?', 'subitems': []},
                content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), drafts)
        solve.assert_called_once_with('$2+2$?', [])

    def test_import_solve_reports_neuro_error(self):
        from problems.neuro import NeuroError
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('worksheet_import_solve')
        with mock.patch('problems.neuro.solve_task',
                        side_effect=NeuroError('нет ключа')):
            response = self.client.post(
                url, {'text': 'Задача', 'subitems': []},
                content_type='application/json')
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error'], 'нет ключа')
        # Мусор в теле запроса — 400, а не 500
        response = self.client.post(
            url, 'не json', content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_import_solve_rate_limit(self):
        from problems.neuro import NeuroQuotaError
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('worksheet_import_solve')
        with mock.patch('problems.neuro.acquire_quota',
                        side_effect=NeuroQuotaError('подождите')):
            response = self.client.post(
                url, {'text': 'Задача', 'subitems': []},
                content_type='application/json')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['error'], 'подождите')

    def test_import_solve_requires_teacher(self):
        make_student(self.teacher)
        self.client.login(username='student1', password='pass12345')
        response = self.client.post(
            reverse('worksheet_import_solve'), {'text': 'x'},
            content_type='application/json')
        self.assertEqual(response.status_code, 403)


class ShareLinkTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = make_worksheet(self.teacher)
        self.link = ShareLink.objects.create(worksheet=self.worksheet)

    def test_public_page_without_login(self):
        response = self.client.get(
            reverse('public_worksheet', args=[self.link.token]))
        self.assertContains(response, 'Квадратные уравнения')
        # Ответы не показываются
        self.assertNotContains(response, 'Ответ')

    def test_public_subtitle_skips_empty_parts(self):
        # Пустые grade_label/subtitle не оставляют «висячих» разделителей
        self.worksheet.grade_label = ''
        self.worksheet.subtitle = ''
        self.worksheet.save()
        response = self.client.get(
            reverse('public_worksheet', args=[self.link.token]))
        line = response.context['subtitle_line']
        self.assertFalse(line.startswith('·'))
        self.assertNotIn('· ·', line)
        # Заполненные части соединяются через «·»
        self.worksheet.grade_label = 'Алгебра · 8 класс'
        self.worksheet.subtitle = 'Вариант 1'
        self.worksheet.save()
        response = self.client.get(
            reverse('public_worksheet', args=[self.link.token]))
        self.assertIn('Вариант 1 ·', response.context['subtitle_line'])

    def test_hidden_items_excluded_from_public_page(self):
        first = self.worksheet.items.order_by('order').first()
        self.link.hidden_items.add(first)
        response = self.client.get(
            reverse('public_worksheet', args=[self.link.token]))
        self.assertNotContains(response, 'x^2-2x=0')
        # Нумерация пересчитана: оставшаяся задача — под номером 1
        rows = response.context['rows']
        self.assertEqual([r['number'] for r in rows], [1])
        # Другая ссылка того же листка показывает всё
        other = ShareLink.objects.create(worksheet=self.worksheet)
        response = self.client.get(
            reverse('public_worksheet', args=[other.token]))
        self.assertEqual(len(response.context['rows']), 2)

    def test_hidden_items_excluded_from_tex(self):
        first = self.worksheet.items.order_by('order').first()
        tex_full = worksheet_to_tex(self.worksheet, 'student')
        tex_cut = worksheet_to_tex(self.worksheet, 'student',
                                   exclude_ids={first.pk})
        self.assertIn(first.task.text_latex, tex_full)
        self.assertNotIn(first.task.text_latex, tex_cut)

    def test_empty_rubric_dropped_when_tasks_hidden(self):
        # Рубрика, все задачи которой скрыты, не должна оставлять
        # пустой enumerate — иначе PDF падает на «missing \\item»
        last = self.worksheet.items.order_by('order').last()
        rubric = make_rubric(self.worksheet, 'Дополнительно', order=50)
        extra = Task.objects.create(
            text_latex='Скрытая задача хвоста', created_by=self.teacher)
        tail = WorksheetItem.objects.create(
            worksheet=self.worksheet, task=extra, order=60)
        tex = worksheet_to_tex(self.worksheet, 'student',
                               exclude_ids={tail.pk})
        self.assertNotIn('\\rubr{Дополнительно}', tex)
        self.assertIn(last.task.text_latex, tex)
        self.assertNotIn('Скрытая задача хвоста', tex)

    def test_visibility_endpoint(self):
        self.client.login(username='teacher1', password='pass12345')
        first = self.worksheet.items.order_by('order').first()
        url = reverse('worksheet_item_visibility',
                      args=[self.worksheet.pk, first.pk])
        self.client.post(url, {'hide_links': [self.link.pk]})
        self.assertEqual(set(self.link.hidden_items.all()), {first})
        # Повторный POST без галочки — задача снова видна
        self.client.post(url, {})
        self.assertEqual(self.link.hidden_items.count(), 0)

    def test_visibility_dialog_in_builder(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(
            reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertContains(response, 'vis-btn')
        self.assertContains(response, 'hide_links')
        # Пока ни у кого не скрыта — обычный глаз, не перечёркнутый
        self.assertContains(response, 'Видна всем ссылкам и ученикам')
        self.assertNotContains(response, 'vis-on')

        first = self.worksheet.items.order_by('order').first()
        self.link.hidden_items.add(first)
        response = self.client.get(
            reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertContains(response, 'vis-on')
        self.assertContains(response, 'Скрыта у части ссылок или учеников')

    @mock.patch('worksheets.services.compile_latex',
                return_value=b'%PDF-1.5 fake')
    def test_filtered_pdf_is_cached(self, mocked):
        first = self.worksheet.items.order_by('order').first()
        self.link.hidden_items.add(first)
        url = reverse('public_worksheet_pdf', args=[self.link.token])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(mocked.call_count, 1)
        # Другая ссылка без скрытий — полный tex, отдельный кэш
        other = ShareLink.objects.create(worksheet=self.worksheet)
        other_url = reverse('public_worksheet_pdf', args=[other.token])
        self.assertEqual(self.client.get(other_url).status_code, 200)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(self.client.get(other_url).status_code, 200)
        self.assertEqual(mocked.call_count, 2)
        # Полный PDF не вытесняет отфильтрованный
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(mocked.call_count, 2)

    def test_public_page_minimal_for_logged_in(self):
        # Даже залогиненный учитель видит публичную страницу без контекстной панели
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(
            reverse('public_worksheet', args=[self.link.token]))
        self.assertNotContains(response, 'context-sidebar')
        self.assertContains(response, 'minimal-body')
        self.assertContains(response, 'task-row')

    def test_inactive_link_404(self):
        self.link.is_active = False
        self.link.save()
        response = self.client.get(
            reverse('public_worksheet', args=[self.link.token]))
        self.assertEqual(response.status_code, 404)

    def test_wrong_token_404(self):
        response = self.client.get(
            reverse('public_worksheet', args=['nonexistent-token']))
        self.assertEqual(response.status_code, 404)

    @mock.patch('worksheets.services.compile_latex',
                return_value=b'%PDF-1.5 fake')
    def test_public_pdf(self, mocked):
        response = self.client.get(
            reverse('public_worksheet_pdf', args=[self.link.token]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

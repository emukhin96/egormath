"""Импорт корпуса листков: разбор, классификация, сверка, загрузка."""

import sys
import tempfile
from pathlib import Path
from unittest import mock

_TOOLS = Path(__file__).resolve().parents[2] / 'tools'
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from problems.models import ExamItem, Task, Topic
from problems.rubricator import seed_rubricator
from problems.tests import make_teacher

from problems.test_textbook_import import TINY_PNG

from .corpus import commit_draft, push_draft, reattach_draft_images
from .corpus_solve import apply_neuro_solution, tasks_missing_solutions
from .models import Worksheet


def _sample_draft(key='6 класс/promatvert/math6-07-percent', **extra):
    draft = {
        'schema_version': 1,
        'id': key,
        'source_path': '/tmp/math6-07-percent.tex',
        'rel_path': key + '.tex',
        'dialect': 'egor',
        'grade': 6,
        'title': 'Процент от числа',
        'header': {
            'title': 'Процент от числа',
            'left': '6 класс. Углублённый уровень',
            'right': 'Е.А. Мухин',
            'subtitle': '',
        },
        'status': 'approved',
        'verdict': 'include',
        'warnings': [],
        'topic_code': 'ARI.04.04',
        'topic_codes': ['ARI.04.04'],
        'topic_ids': [],
        'topic_candidates': [],
        'exam_item_codes': [],
        'elements': [
            {'kind': 'rubric', 'rubric': 'Нахождение процента', 'note': ''},
            {
                'kind': 'task',
                'text': 'Найдите $57\\%$ от 200.',
                'subitems': [],
                'stars': 1,
                'columns': 0,
                'answer': '114',
                'solution': '',
                'subitem_answers': [],
                'subitem_solutions': [],
                'images': [],
                'image_files': [],
                'warnings': [],
                'status': 'needs_review',
                'skip': False,
            },
            {
                'kind': 'task',
                'text': 'Найдите:',
                'subitems': ['$10\\%$ от 50', '$20\\%$ от 80'],
                'stars': 1,
                'columns': 2,
                'answer': '',
                'solution': '',
                'subitem_answers': ['5', '16'],
                'subitem_solutions': ['$10\\%$ от $50$ — это $5$.', '$20\\%$ от $80$ — это $16$.'],
                'images': [],
                'image_files': [],
                'warnings': [],
                'status': 'needs_review',
                'skip': False,
            },
        ],
    }
    draft.update(extra)
    return draft


class CorpusParseEgorTests(TestCase):
    def test_starredtask_and_hwork(self):
        from worksheet_corpus.parse import parse_egor_source
        src = (
            r'\documentclass{article}\usepackage{mathneo}'
            r'\begin{document}'
            r'\bighead{Делимость}{7 класс}{Е.А. Мухин}'
            r'\task{1}{0}{Найдите НОД $12$ и $18$.}'
            r'\hwork '
            r'\starredtask{2}{\columned{2}{Решите:}{'
            r'\item $x=1$; \item $x=2$.}}'
            r'\end{document}'
        )
        parsed = parse_egor_source(src)
        kinds = [el['kind'] for el in parsed['elements']]
        self.assertIn('task', kinds)
        self.assertIn('rubric', kinds)
        tasks = [el for el in parsed['elements'] if el['kind'] == 'task']
        self.assertGreaterEqual(len(tasks), 2)
        starred = tasks[-1]
        self.assertEqual(starred['stars'], 2)
        self.assertEqual(len(starred['subitems']), 2)

    def test_inline_alpha_in_task_stem(self):
        from worksheet_corpus.parse import parse_egor_source
        src = (
            '\\documentclass{article}\\usepackage{mathneo}\n'
            '\\begin{document}\n'
            '\\bighead{Функции}{Алгебра}{7 класс}\n'
            '\\task{0}{0}{%\n'
            'Дана функция $y=f(x)$, где\n'
            '$$\n'
            'f(x)=x\n'
            '$$\n'
            'a) Найдите $f(1)$;\\\\\n'
            'б) Постройте график функции $y=f(x)$.\n'
            '}[][][]\n'
            '\\end{document}\n'
        )
        parsed = parse_egor_source(src)
        task = [el for el in parsed['elements'] if el['kind'] == 'task'][0]
        self.assertEqual(len(task['subitems']), 2)
        self.assertIn('f(1)', task['subitems'][0])
        self.assertIn('график', task['subitems'][1])
        self.assertNotIn('a)', task['text'])
        self.assertNotIn('б)', task['text'])


class CorpusClassifyTests(TestCase):
    def test_percent_and_oge_number(self):
        from worksheet_corpus.classify import classify_draft
        seed_rubricator()
        draft = _sample_draft(
            key='9 класс/oge-16',
            title='16. Окружность',
            rel_path='9 класс/oge-16.tex')
        draft['header']['title'] = '16. Окружность'
        draft['topic_code'] = ''
        classify_draft(draft, overwrite=True)
        self.assertIn('OGE_2026_16', draft['exam_item_codes'])
        self.assertIn('OGE_2026', draft['exam_item_codes'])
        self.assertTrue(
            draft.get('topic_code') in ('GEO.04', 'GEO.04.01', 'GEO.04.06')
            or draft.get('topic_candidates'))
        light = _sample_draft(
            key='9 класс/oge9-light-course/oge-01-podob',
            title='Подобие',
            rel_path='9 класс/oge9-light-course/oge-01-podob.tex')
        light['topic_code'] = ''
        classify_draft(light, overwrite=True)
        self.assertIn('OGE_2026_01', light['exam_item_codes'])
        self.assertIn('OGE_2026', light['exam_item_codes'])
        self.assertNotIn('OGE_2026_09', light['exam_item_codes'])
        ege = _sample_draft(
            key='6 класс/math11-stereom',
            title='Стереометрия',
            rel_path='6 класс/math11-stereom.tex')
        ege['header']['left'] = 'Подготовка к ЕГЭ'
        ege['topic_code'] = 'GEO.08'
        classify_draft(ege, overwrite=True)
        self.assertEqual(ege['exam_item_codes'], ['EGE_PROFILE_2026'])
        tagged = _sample_draft(
            key='9 класс/zamena-oge-tag',
            title='Замена',
            rel_path='9 класс/zamena-alg.tex')
        tagged['topic_code'] = ''
        tagged['exam_item_codes'] = []
        tagged['header']['title'] = 'Замена'
        tagged['elements'][1]['text'] = r'\oge Решите уравнение.'
        classify_draft(tagged, overwrite=True)
        self.assertIn('OGE_2026', tagged['exam_item_codes'])
        duga = _sample_draft(
            key='9 класс/matvert9-teorver-geom_ver-duga',
            title='Геометрическая вероятность. Дуга',
            rel_path='9 класс/matvert9-teorver-geom_ver-duga.tex')
        duga['topic_code'] = ''
        duga['header']['title'] = 'Геометрическая вероятность. Дуга'
        classify_draft(duga, overwrite=True)
        self.assertEqual(duga.get('topic_code'), 'STA.03.05')
        self.assertTrue(duga['elements'][1].get('topic_code'))

    def test_exam_lines_seeded(self):
        seed_rubricator()
        self.assertTrue(ExamItem.objects.filter(code='OGE_2026').exists())
        self.assertTrue(ExamItem.objects.filter(code='OGE_2026_19').exists())
        self.assertTrue(
            ExamItem.objects.filter(code='EGE_PROFILE_2026').exists())


class CorpusLoadTests(TestCase):
    def setUp(self):
        seed_rubricator()
        self.teacher = make_teacher()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.patcher = mock.patch(
            'worksheet_corpus.paths.OUTPUT_DIR', self.out)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_commit_creates_worksheet_and_tasks(self):
        from worksheet_corpus.store import save_draft
        draft = _sample_draft()
        save_draft(draft)
        worksheet, info = commit_draft(draft, self.teacher)
        self.assertEqual(info['created'], 2)
        self.assertEqual(worksheet.title, 'Процент от числа')
        self.assertEqual(worksheet.items.filter(task__isnull=False).count(), 2)
        task = worksheet.items.filter(task__isnull=False).first().task
        self.assertTrue(task.topics.filter(code='ARI.04.04').exists())
        self.assertEqual(task.grade_level, 6)
        self.assertEqual(task.stars, 0)
        again, info2 = commit_draft(draft, self.teacher)
        self.assertTrue(info2['skipped'])
        self.assertEqual(again.pk, worksheet.pk)

    def test_dedup_reuses_task(self):
        from worksheet_corpus.store import save_draft
        first = _sample_draft(key='a/one')
        save_draft(first)
        commit_draft(first, self.teacher)
        second = _sample_draft(key='a/two', title='Другой листок')
        second['header']['title'] = 'Другой листок'
        second['status'] = 'approved'
        save_draft(second)
        ws, info = commit_draft(second, self.teacher)
        self.assertEqual(info['reused'], 2)
        self.assertEqual(info['created'], 0)
        self.assertEqual(Task.objects.filter(variant_of__isnull=True).count(), 2)

    def test_commit_does_not_reuse_same_text_with_different_images(self):
        from worksheet_corpus.store import save_draft
        key = '9 класс/matvert9-geom-cheva_menelay'
        pic_a = 'menelay-a.png'
        pic_b = 'menelay-b.png'
        self._put_asset(key, pic_a)
        self._put_asset(key, pic_b)
        draft = _sample_draft(key=key)
        draft['header']['title'] = 'Теорема Менелая'
        draft['elements'] = [
            {
                'kind': 'task',
                'text': 'Найдите $x$ на рисунке.',
                'subitems': [],
                'stars': 0,
                'columns': 0,
                'answer': '',
                'solution': '',
                'subitem_answers': [],
                'subitem_solutions': [],
                'images': [],
                'image_files': [],
                'image_names': [pic_a],
                'warnings': [],
                'status': 'needs_review',
                'skip': False,
            },
            {
                'kind': 'task',
                'text': 'Найдите $x$ на рисунке.',
                'subitems': [],
                'stars': 0,
                'columns': 0,
                'answer': '',
                'solution': '',
                'subitem_answers': [],
                'subitem_solutions': [],
                'images': [],
                'image_files': [],
                'image_names': [pic_b],
                'warnings': [],
                'status': 'needs_review',
                'skip': False,
            },
        ]
        save_draft(draft)
        media = Path(self.tmp.name) / 'media'
        with override_settings(MEDIA_ROOT=str(media)):
            worksheet, info = commit_draft(draft, self.teacher)
        self.assertEqual(info['created'], 2)
        self.assertEqual(info['reused'], 0)
        tasks = [
            item.task for item in
            worksheet.items.filter(task__isnull=False).order_by('order')]
        self.assertNotEqual(tasks[0].pk, tasks[1].pk)
        self.assertEqual(
            [img.filename for img in tasks[0].images.all()], [pic_a])
        self.assertEqual(
            [img.filename for img in tasks[1].images.all()], [pic_b])

    def test_find_imported_does_not_match_longer_key(self):
        from worksheet_corpus.store import save_draft
        from .corpus import find_imported_worksheet
        long = _sample_draft(key='8 класс/matvert8-geom-prop_otr_treug')
        long['header']['title'] = 'В треугольнике'
        save_draft(long)
        worksheet, _ = commit_draft(long, self.teacher)
        self.assertIsNone(find_imported_worksheet(
            self.teacher, '8 класс/matvert8-geom-prop_otr'))
        self.assertEqual(
            find_imported_worksheet(
                self.teacher, '8 класс/matvert8-geom-prop_otr_treug').pk,
            worksheet.pk)

    def test_skip_element(self):
        from worksheet_corpus.store import save_draft
        draft = _sample_draft(key='b/skip')
        draft['elements'][1]['skip'] = True
        save_draft(draft)
        worksheet, info = commit_draft(draft, self.teacher)
        self.assertEqual(info['created'], 1)
        self.assertEqual(worksheet.items.filter(task__isnull=False).count(), 1)

    def test_commit_writes_subitem_answers(self):
        from worksheet_corpus.store import save_draft
        draft = _sample_draft(key='b/subs')
        save_draft(draft)
        worksheet, info = commit_draft(draft, self.teacher)
        self.assertEqual(info['created'], 2)
        task = worksheet.items.filter(task__isnull=False).last().task
        subs = list(task.subitems.all())
        self.assertEqual(len(subs), 2)
        self.assertEqual(subs[0].answer_latex, '5')
        self.assertEqual(subs[1].answer_latex, '16')
        self.assertTrue(subs[0].solution_latex)
        self.assertFalse((task.answer_latex or '').strip())

    def _put_asset(self, key, name):
        dest = self.out / 'assets' / key.replace('/', '__')
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / name
        path.write_bytes(TINY_PNG)
        return path

    def test_commit_attaches_images_from_assets_not_host_path(self):
        from worksheet_corpus.store import save_draft
        key = '8 класс/matvert8-geom-prop_otr'
        name = 'matvert8-geom-fales-pic1.png'
        self._put_asset(key, name)
        draft = _sample_draft(key=key)
        draft['elements'][1]['image_names'] = [name]
        draft['elements'][1]['image_files'] = [
            '/Users/other/egormath-web/var/worksheets-import/assets/'
            f'{key.replace("/", "__")}/{name}'
        ]
        save_draft(draft)
        media = Path(self.tmp.name) / 'media'
        with override_settings(MEDIA_ROOT=str(media)):
            worksheet, info = commit_draft(draft, self.teacher)
        self.assertFalse(info.get('skipped'))
        task = worksheet.items.filter(task__isnull=False).first().task
        self.assertEqual(task.images.count(), 1)
        self.assertEqual(task.images.get().filename, name)

    def test_reattach_fills_images_on_existing_worksheet(self):
        from worksheet_corpus.store import save_draft
        key = '8 класс/matvert8-geom-prop_otr'
        name = 'matvert8-geom-prop_otr-pic4.png'
        draft = _sample_draft(key=key)
        draft['elements'][1]['image_names'] = [name]
        draft['elements'][1]['image_files'] = [
            f'/missing/host/{name}'
        ]
        save_draft(draft)
        media = Path(self.tmp.name) / 'media'
        with override_settings(MEDIA_ROOT=str(media)):
            worksheet, _ = commit_draft(draft, self.teacher)
            self.assertEqual(
                worksheet.items.filter(task__isnull=False).first()
                .task.images.count(), 0)
            self._put_asset(key, name)
            _, info = reattach_draft_images(draft, self.teacher)
            self.assertEqual(info['attached'], 1)
            self.assertEqual(
                worksheet.items.filter(task__isnull=False).first()
                .task.images.count(), 1)
            again, info2 = push_draft(draft, self.teacher)
            self.assertEqual(again.pk, worksheet.pk)
            self.assertTrue(info2.get('skipped'))
            self.assertEqual(info2.get('attached'), 0)

    def test_reattach_command_heals_imported_worksheet(self):
        from io import StringIO

        from worksheet_corpus.store import save_draft
        key = '8 класс/matvert8-geom-prop_otr'
        name = 'matvert8-geom-fales-pic1.png'
        draft = _sample_draft(key=key)
        draft['status'] = 'imported'
        draft['elements'][1]['image_names'] = [name]
        draft['elements'][1]['image_files'] = [f'/missing/{name}']
        save_draft(draft)
        media = Path(self.tmp.name) / 'media'
        with override_settings(MEDIA_ROOT=str(media)):
            worksheet, _ = commit_draft(draft, self.teacher, force=True)
            self._put_asset(key, name)
            out = StringIO()
            call_command('reattach_corpus_images', '--key', key, stdout=out)
            self.assertEqual(
                worksheet.items.filter(task__isnull=False).first()
                .task.images.count(), 1)
            self.assertIn('догружено 1', out.getvalue())

    def test_parse_file_stores_image_names_not_host_paths(self):
        from worksheet_corpus.parse import parse_file
        src = Path(self.tmp.name) / 'src'
        src.mkdir()
        (src / 'fig.png').write_bytes(TINY_PNG)
        tex = src / 'sheet.tex'
        tex.write_text(
            '\\documentclass{article}\\usepackage{mathneo}\n'
            '\\begin{document}\n'
            '\\bighead{Рисунки}{8 класс}{Е.А. Мухин}\n'
            '\\task{0}{0}{См. \\includegraphics{fig.png}}\n'
            '\\end{document}\n',
            encoding='utf-8')
        draft = parse_file(tex, rel_path='8 класс/sheet.tex', grade=8)
        task = next(el for el in draft['elements'] if el['kind'] == 'task')
        self.assertEqual(task['image_names'], ['fig.png'])
        self.assertEqual(task['image_files'], ['fig.png'])
        for raw in task['image_files']:
            self.assertFalse(Path(raw).is_absolute())
        stored = (
            self.out / 'assets' / '8 класс__sheet' / 'fig.png')
        self.assertTrue(stored.is_file())


class CorpusViewTests(TestCase):
    def setUp(self):
        seed_rubricator()
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patcher = mock.patch(
            'worksheet_corpus.paths.OUTPUT_DIR', Path(self.tmp.name))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_list_and_approve(self):
        from worksheet_corpus.store import save_draft
        draft = _sample_draft()
        draft['status'] = 'needs_review'
        save_draft(draft)
        resp = self.client.get(reverse('worksheet_corpus_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Процент от числа')
        url = reverse('worksheet_corpus_detail', args=[draft['id']])
        resp = self.client.post(url, {
            'title': 'Процент от числа',
            'topic_code': 'ARI.04.04',
            'text_1': 'Найдите $57\\%$ от 200.',
            'action': 'approve',
        })
        self.assertEqual(resp.status_code, 302)
        from worksheet_corpus.store import load_draft
        saved = load_draft(draft['id'])
        self.assertEqual(saved['status'], 'approved')

    def test_commit_from_detail(self):
        from worksheet_corpus.store import save_draft
        draft = _sample_draft()
        save_draft(draft)
        url = reverse('worksheet_corpus_detail', args=[draft['id']])
        resp = self.client.post(url, {
            'title': draft['title'],
            'topic_code': 'ARI.04.04',
            'text_1': draft['elements'][1]['text'],
            'action': 'commit',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Worksheet.objects.filter(
            title='Процент от числа').exists())

    def test_approve_clean(self):
        from worksheet_corpus.store import load_draft, save_draft
        from .corpus import approve_clean_drafts
        clean = _sample_draft(key='clean/one')
        clean['status'] = 'needs_review'
        save_draft(clean)
        dirty = _sample_draft(key='dirty/one', title='С ошибкой')
        dirty['status'] = 'needs_review'
        dirty['warnings'] = ['нет рисунка']
        save_draft(dirty)
        approved = approve_clean_drafts()
        self.assertIn('clean/one', approved)
        self.assertNotIn('dirty/one', approved)
        self.assertEqual(load_draft('clean/one')['status'], 'approved')

    def test_exam_picker_and_skip_toggle(self):
        from worksheet_corpus.store import load_draft, save_draft
        draft = _sample_draft()
        draft['status'] = 'needs_review'
        draft['elements'][1]['choices'] = ['10;−10', 'нет корней']
        save_draft(draft)
        detail = self.client.get(
            reverse('worksheet_corpus_detail', args=[draft['id']]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'value="OGE_2026"')
        self.assertContains(detail, 'Варианты ответа')
        self.assertContains(detail, 'ОГЭ №19 (геом. высказывания)')
        self.assertContains(detail, 'Распознанные подпункты')
        self.assertContains(detail, 'name="answer_2_0"')
        self.assertContains(detail, 'name="solution_2_1"')
        listing = self.client.get(reverse('worksheet_corpus_list'))
        self.assertContains(listing, 'пропустить')
        self.assertContains(detail, 'corpus-task-skip')
        self.assertContains(detail, 'corpus-draft-skip')
        self.assertContains(detail, 'data-autosave="change"')
        self.assertContains(detail, 'data-dirty-guard')
        self.assertContains(detail, 'data-autosave-ignore')
        self.assertContains(detail, 'data-corpus-exam-chips')
        self.assertContains(detail, 'Выбрать ОГЭ / ЕГЭ / МЦКО')
        skip_url = reverse('worksheet_corpus_toggle_skip', args=[draft['id']])
        resp = self.client.post(skip_url, {'skip': '1'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(load_draft(draft['id'])['status'], 'skipped')
        listing = self.client.get(reverse('worksheet_corpus_list'))
        self.assertNotContains(listing, 'Процент от числа')
        listing = self.client.get(
            reverse('worksheet_corpus_list'), {'status': 'skipped'})
        self.assertContains(listing, 'is-skipped')
        self.assertContains(listing, 'Процент от числа')
        ajax = self.client.post(
            skip_url, {'skip': '0'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(ajax.status_code, 200)
        payload = ajax.json()
        self.assertTrue(payload['ok'])
        self.assertFalse(payload['skipped'])
        self.assertEqual(payload['status'], 'needs_review')
        self.assertEqual(load_draft(draft['id'])['status'], 'needs_review')
        task_ajax = self.client.post(
            skip_url, {'skip': '1', 'index': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(task_ajax.status_code, 200)
        self.assertTrue(task_ajax.json()['skipped'])
        self.assertTrue(load_draft(draft['id'])['elements'][1]['skip'])
        save = self.client.post(
            reverse('worksheet_corpus_detail', args=[draft['id']]), {
                'title': draft['title'],
                'action': 'save',
                'text_1': draft['elements'][1]['text'],
            })
        self.assertEqual(save.status_code, 302)
        self.assertTrue(load_draft(draft['id'])['elements'][1]['skip'])

    def test_autosave_topic_returns_json(self):
        from worksheet_corpus.store import load_draft, save_draft
        draft = _sample_draft()
        draft['topic_code'] = ''
        save_draft(draft)
        topic = Topic.objects.get(code='STA.03.05')
        url = reverse('worksheet_corpus_detail', args=[draft['id']])
        resp = self.client.post(url, {
            'title': draft['title'],
            'topics': str(topic.pk),
            'topics_submitted': '1',
            'text_1': draft['elements'][1]['text'],
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload['ok'])
        saved = load_draft(draft['id'])
        self.assertEqual(saved['topic_code'], 'STA.03.05')
        self.assertEqual(saved.get('topic_codes'), ['STA.03.05'])
        self.assertFalse(saved.get('needs_topic_review'))
        self.assertEqual(saved['elements'][1].get('topic_code'), 'STA.03.05')

    def test_detail_picker_allows_multiple_topics(self):
        from worksheet_corpus.store import load_draft, save_draft
        draft = _sample_draft()
        save_draft(draft)
        url = reverse('worksheet_corpus_detail', args=[draft['id']])
        page = self.client.get(url)
        self.assertContains(page, 'data-single="0"')
        first = Topic.objects.get(code='ARI.04.04')
        second = Topic.objects.get(code='STA.03.05')
        resp = self.client.post(url, {
            'title': draft['title'],
            'topics': [str(first.pk), str(second.pk)],
            'primary_topic': str(first.pk),
            'topics_submitted': '1',
            'text_1': draft['elements'][1]['text'],
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        saved = load_draft(draft['id'])
        self.assertEqual(saved['topic_code'], 'ARI.04.04')
        self.assertEqual(saved['topic_codes'], ['ARI.04.04', 'STA.03.05'])
        self.assertEqual(
            saved['elements'][1].get('topic_codes'),
            ['ARI.04.04', 'STA.03.05'])

    def test_autosave_exam_tag_returns_json(self):
        from worksheet_corpus.store import load_draft, save_draft
        draft = _sample_draft()
        save_draft(draft)
        url = reverse('worksheet_corpus_detail', args=[draft['id']])
        resp = self.client.post(url, {
            'title': draft['title'],
            'exams_submitted': '1',
            'exam_item_codes': ['EGE_PROFILE_2026_15'],
            'text_1': draft['elements'][1]['text'],
            'action': 'save',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        saved = load_draft(draft['id'])
        self.assertEqual(
            set(saved['exam_item_codes']),
            {'EGE_PROFILE_2026', 'EGE_PROFILE_2026_15'})

    def test_push_and_unpush(self):
        from worksheet_corpus.store import load_draft, save_draft
        draft = _sample_draft()
        draft['status'] = 'needs_review'
        save_draft(draft)
        push = self.client.post(
            reverse('worksheet_corpus_push', args=[draft['id']]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(push.status_code, 200)
        payload = push.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(load_draft(draft['id'])['status'], 'imported')
        ws = Worksheet.objects.get(title='Процент от числа')
        listing = self.client.get(reverse('worksheet_list'))
        self.assertContains(listing, 'Убрать из каталога')
        unpush = self.client.post(
            reverse('worksheet_corpus_unpush', args=[ws.pk]))
        self.assertEqual(unpush.status_code, 302)
        self.assertFalse(Worksheet.objects.filter(pk=ws.pk).exists())
        self.assertEqual(load_draft(draft['id'])['status'], 'needs_review')

    def test_push_long_rubric_note(self):
        from worksheet_corpus.store import save_draft
        from worksheets.models import WorksheetItem
        draft = _sample_draft('9 класс/math9-course/alg09-func-01')
        draft['elements'][0]['note'] = 'x' * 430
        save_draft(draft)
        push = self.client.post(
            reverse('worksheet_corpus_push', args=[draft['id']]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(push.status_code, 200)
        self.assertTrue(push.json()['ok'])
        note = WorksheetItem.objects.get(
            worksheet__comment__startswith='corpus:' + draft['id'],
            rubric='Нахождение процента').rubric_note
        self.assertEqual(len(note), 430)

    def test_push_skips_empty_text_block(self):
        from worksheet_corpus.store import save_draft
        from worksheets.models import WorksheetItem
        draft = _sample_draft()
        draft['elements'].insert(0, {
            'kind': 'text', 'text': '', 'style': 'rule'})
        save_draft(draft)
        push = self.client.post(
            reverse('worksheet_corpus_push', args=[draft['id']]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(push.status_code, 200)
        self.assertTrue(push.json()['ok'])
        ws = WorksheetItem.objects.filter(
            worksheet__comment__startswith='corpus:' + draft['id'])
        self.assertFalse(ws.filter(task__isnull=True, rubric='', text_latex='').exists())

    def test_tex_export(self):
        from worksheet_corpus.store import save_draft
        draft = _sample_draft()
        save_draft(draft)
        resp = self.client.get(
            reverse('worksheet_corpus_tex', args=[draft['id']]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'\\task{1}{0}', resp.content)


class CorpusSolveTests(TestCase):
    def setUp(self):
        seed_rubricator()
        self.teacher = make_teacher()

    def test_fill_empty_solution(self):
        from .corpus import SOURCE_TITLE, corpus_mark
        from .models import WorksheetItem
        ws = Worksheet.objects.create(
            title='Пилот', owner=self.teacher,
            comment=corpus_mark('pilot/one'))
        task = Task.objects.create(
            text_latex='2+2', created_by=self.teacher)
        WorksheetItem.objects.create(worksheet=ws, task=task, order=10)
        self.assertEqual(len(tasks_missing_solutions(ws)), 1)
        with mock.patch('worksheets.corpus_solve.solve_task', return_value={
            'answer': '4', 'solution': 'Сложение.',
            'subitem_answers': [], 'subitem_solutions': [],
        }):
            apply_neuro_solution(task)
        task.refresh_from_db()
        self.assertEqual(task.solution_latex, 'Сложение.')
        self.assertEqual(task.answer_latex, '4')
        self.assertEqual(len(tasks_missing_solutions(ws)), 0)
        self.assertEqual(SOURCE_TITLE, 'Авторские листки')


class CorpusTitleOriginViewTests(TestCase):
    def setUp(self):
        seed_rubricator()
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patcher = mock.patch(
            'worksheet_corpus.paths.OUTPUT_DIR', Path(self.tmp.name))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_proposed_title_shown_on_list_and_detail(self):
        from worksheet_corpus.latex_scan import TITLE_PROPOSED_WARNING
        from worksheet_corpus.store import save_draft
        draft = _sample_draft(key='9 класс/teorver-duga')
        draft['status'] = 'needs_review'
        draft['title'] = 'Геометрическая вероятность. Дуга'
        draft['header']['title'] = draft['title']
        draft['title_origin'] = 'proposed'
        draft['warnings'] = [TITLE_PROPOSED_WARNING]
        save_draft(draft)
        listing = self.client.get(reverse('worksheet_corpus_list'))
        self.assertContains(listing, 'заголовок предложен')
        detail = self.client.get(
            reverse('worksheet_corpus_detail', args=[draft['id']]))
        self.assertContains(detail, 'Заголовок предложен по содержанию')
        self.assertContains(detail, 'corpus-title-flag')

    def test_commit_uses_task_topic_code(self):
        from worksheet_corpus.store import save_draft
        draft = _sample_draft(key='9 класс/mixed-topics')
        draft['topic_code'] = 'STA.03.05'
        draft['elements'][1]['topic_code'] = 'ARI.04.04'
        save_draft(draft)
        worksheet, info = commit_draft(draft, self.teacher)
        self.assertEqual(info['created'], 2)
        first = worksheet.items.filter(task__isnull=False).order_by('order')[0]
        self.assertTrue(first.task.topics.filter(code='ARI.04.04').exists())
        self.assertFalse(first.task.topics.filter(code='STA.03.05').exists())

    def test_commit_keeps_all_worksheet_topics(self):
        from worksheet_corpus.store import save_draft
        draft = _sample_draft(key='8 класс/two-topics')
        draft['topic_code'] = 'ARI.03.01'
        draft['topic_codes'] = ['ARI.03.01', 'ARI.03.04']
        save_draft(draft)
        worksheet, info = commit_draft(draft, self.teacher)
        self.assertEqual(info['created'], 2)
        codes = set(worksheet.topics.values_list('code', flat=True))
        self.assertEqual(codes, {'ARI.03.01', 'ARI.03.04'})
        task = worksheet.items.filter(task__isnull=False).first().task
        self.assertEqual(
            set(task.topics.values_list('code', flat=True)),
            {'ARI.03.01', 'ARI.03.04'})

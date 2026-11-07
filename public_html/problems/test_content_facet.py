"""Каркас фасета CONTENT («Содержание задачи», этап 07.11.2026):
словарь, сид дерева, промпт и разбор ответа классификатора, запись
разметки, команда label_content и защита разметки от формы задачи.
"""
import json
import re
import tempfile
from pathlib import Path
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from . import content_tags as ct
from .content_data import (CONTENT_FACET_CODE, CONTENT_GROUPS,
                           content_codes)
from .models import FacetType, FacetValue, Task
from .rubricator import seed_content_facet, set_task_facets


class DictionaryTests(SimpleTestCase):
    def test_codes_unique_and_well_formed(self):
        codes = content_codes() + [g for g, _n, _v in CONTENT_GROUPS]
        self.assertEqual(len(codes), len(set(codes)))
        for code in codes:
            self.assertRegex(code, r'^[A-Z][A-Z0-9_]{1,63}$')

    def test_every_value_has_definition(self):
        for _g, gname, values in CONTENT_GROUPS:
            self.assertTrue(values, gname)
            for code, name, when, _overlap in values:
                self.assertTrue(name.strip(), code)
                self.assertGreater(len(when), 15, code)

    def test_size_in_planned_range(self):
        self.assertTrue(80 <= len(content_codes()) <= 150)


class PromptTests(SimpleTestCase):
    items = [
        {'id': 7, 'text': 'Решите уравнение $|x^2-4|=3x$.',
         'subitems': [], 'answer': '$4$', 'solution': ''},
        {'id': 9, 'text': 'Найдите площадь трапеции.',
         'subitems': ['а) …', ''], 'answer': '', 'solution': 'x' * 2000},
    ]

    def test_prompt_lists_vocabulary_and_tasks(self):
        prompt = ct.build_prompt(self.items)
        self.assertIn('ABS_EQ — Уравнение с модулем', prompt)
        self.assertIn('### id=7', prompt)
        self.assertIn('1) а) …', prompt)
        self.assertNotIn('2) ', prompt)       # пустой подпункт не шлём
        self.assertLess(prompt.count('x'), 2000)  # решение обрезано

    def test_parse_keeps_only_known_codes_and_batch_ids(self):
        raw = json.dumps({'items': [
            {'id': 7, 'codes': ['ABS_EQ', 'abs_eq', 'ABS', 'MADE_UP']},
            {'id': 9, 'codes': ['QUAD_TRAPEZOID', 'QUAD_AREA']},
            {'id': 100, 'codes': ['TRI_AREA']},
        ]})
        labels, dropped = ct.parse_response(raw, [7, 9])
        self.assertEqual(labels, {7: ['ABS_EQ'],
                                  9: ['QUAD_TRAPEZOID', 'QUAD_AREA']})
        # Код группы задаче не ставится — только значения.
        self.assertEqual(sorted(dropped), ['ABS', 'MADE_UP'])

    def test_parse_rejects_garbage(self):
        with self.assertRaises(ct.ContentLabelError):
            ct.parse_response('{"foo": 1}', [1])
        with self.assertRaises(ct.ContentLabelError):
            ct.parse_response('не JSON', [1])

    def test_batch_file_and_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            answer = ct.write_batch(self.items, Path(tmp) / 'batch_001.md')
            text = (Path(tmp) / 'batch_001.md').read_text(encoding='utf-8')
            self.assertIn('### id=9', text)
            self.assertIn(answer.name, text)
            answer.write_text('{"items": [{"id": 7, "codes": ["ABS_EQ"]}]}',
                              encoding='utf-8')
            labels, _ = ct.read_answer(answer, [7, 9])
        self.assertEqual(labels, {7: ['ABS_EQ']})   # 9 не вернулся


class SeedTests(TestCase):
    def test_seed_builds_two_level_tree(self):
        seed_content_facet()
        facet = FacetType.objects.get(code=CONTENT_FACET_CODE)
        values = FacetValue.objects.filter(facet_type=facet)
        self.assertEqual(values.filter(parent__isnull=True).count(),
                         len(CONTENT_GROUPS))
        self.assertEqual(values.filter(parent__isnull=False).count(),
                         len(content_codes()))
        abs_eq = values.get(code='ABS_EQ')
        self.assertEqual(abs_eq.parent.code, 'ABS')

    def test_seed_is_idempotent(self):
        seed_content_facet()
        self.assertEqual(seed_content_facet()['created'], 0)

    def test_stale_value_removed_only_without_tasks(self):
        groups = [('G', 'Группа', [
            ('G_A', 'А', 'Ставить, когда есть А в условии.', ''),
            ('G_B', 'Б', 'Ставить, когда есть Б в условии.', '')])]
        seed_content_facet(groups)
        task = Task.objects.create(text_latex='т')
        task.facet_values.add(FacetValue.objects.get(code='G_A'))
        stats = seed_content_facet([('H', 'Другая', [
            ('H_A', 'В', 'Ставить, когда есть В в условии.', '')])])
        # G_B удалено; G_A стоит у задачи — остаётся, а с ним и группа G.
        self.assertEqual(stats['removed'], 1)
        self.assertEqual(sorted(stats['kept']), ['G', 'G_A'])
        codes = set(FacetValue.objects.filter(
            facet_type__code=CONTENT_FACET_CODE).values_list('code', flat=True))
        self.assertEqual(codes, {'G', 'G_A', 'H', 'H_A'})


class ApplyTests(TestCase):
    def setUp(self):
        seed_content_facet()
        level, _ = FacetType.objects.get_or_create(
            code='LEVEL', defaults={'name': 'Уровень'})
        self.base, _ = FacetValue.objects.get_or_create(
            facet_type=level, code='BASE', defaults={'name': 'Базовый'})
        self.task = Task.objects.create(text_latex='$|x|=1$')
        self.task.facet_values.add(self.base)

    def codes(self):
        return set(self.task.facet_values.values_list('code', flat=True))

    def test_add_then_replace_keeps_other_facets(self):
        stats = ct.apply_labels({self.task.pk: ['ABS_EQ', 'NOPE']})
        self.assertEqual((stats['added'], stats['unknown']), (1, 1))
        self.assertEqual(self.codes(), {'BASE', 'ABS_EQ'})
        ct.apply_labels({self.task.pk: ['ABS_INEQ']}, replace=True)
        self.assertEqual(self.codes(), {'BASE', 'ABS_INEQ'})

    def test_task_form_does_not_wipe_content(self):
        ct.apply_labels({self.task.pk: ['ABS_EQ']})
        abs_eq = FacetValue.objects.get(code='ABS_EQ')
        # Пикер формы присылает только уровни/методы; CONTENT в запросе —
        # подделка и тоже не записывается.
        set_task_facets(self.task, [])
        self.assertEqual(self.codes(), {'ABS_EQ'})
        set_task_facets(self.task, [self.base.pk, abs_eq.pk])
        self.assertEqual(self.codes(), {'BASE', 'ABS_EQ'})


class CommandTests(TestCase):
    def setUp(self):
        self.task = Task.objects.create(text_latex='Куб')
        call_command('label_content', '--seed', stdout=StringIO())

    def run_cmd(self, *args):
        out = StringIO()
        call_command('label_content', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        with tempfile.NamedTemporaryFile('w', suffix='.jsonl',
                                         delete=False) as fh:
            fh.write(json.dumps({'id': self.task.pk, 'codes': ['ST_CUBE',
                                                               'BAD']}) + '\n')
        out = self.run_cmd('--from', fh.name)
        self.assertIn('Пробный прогон', out)
        self.assertIn('BAD', out)
        self.assertFalse(self.task.facet_values.exists())
        out = self.run_cmd('--from', fh.name, '--apply')
        self.assertTrue(re.search(r'добавлено 1\b', out))
        self.assertEqual(
            list(self.task.facet_values.values_list('code', flat=True)),
            ['ST_CUBE'])

    def test_load_labels_accepts_dict_file(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json',
                                         delete=False) as fh:
            json.dump({str(self.task.pk): ['ST_CUBE']}, fh)
        self.assertEqual(ct.load_labels(fh.name), {self.task.pk: ['ST_CUBE']})

    def test_batches_and_answers_from_folder(self):
        other = Task.objects.create(text_latex='Трапеция')
        with tempfile.TemporaryDirectory() as tmp:
            out = self.run_cmd('--make-batches', tmp, '--size', '1',
                               '--ids', f'{self.task.pk},{other.pk}')
            self.assertIn('Пакетов 2', out)
            manifest = json.loads((Path(tmp) / 'manifest.json').read_text())
            self.assertEqual(sorted(manifest), ['batch_001.md', 'batch_002.md'])
            (Path(tmp) / 'batch_001.answer.json').write_text(json.dumps(
                {'items': [{'id': self.task.pk, 'codes': ['ST_CUBE']}]}))
            err = StringIO()
            call_command('label_content', '--from', tmp, '--apply',
                         stdout=StringIO(), stderr=err)
        self.assertIn('batch_002.md', err.getvalue())   # нет ответа
        self.assertEqual(
            list(self.task.facet_values.values_list('code', flat=True)),
            ['ST_CUBE'])
        self.assertFalse(other.facet_values.exists())


class GuardTests(TestCase):
    def setUp(self):
        seed_content_facet()
        self.task = Task.objects.create(text_latex='$|x|=1$')

    def test_stale_text_is_skipped_and_backup_written(self):
        good = {str(self.task.pk): ct.task_text_hash(self.task)}
        other = Task.objects.create(text_latex='Старый текст')
        bad = {str(other.pk): ct.text_hash('Другой текст')}
        with tempfile.TemporaryDirectory() as tmp:
            labels = Path(tmp) / 'labels.json'
            labels.write_text(json.dumps({str(self.task.pk): ['ABS_EQ'],
                                          str(other.pk): ['ABS_EQ']}))
            hashes = Path(tmp) / 'hashes.json'
            hashes.write_text(json.dumps({**good, **bad}))
            backup = Path(tmp) / 'rollback.json'
            out = StringIO()
            call_command('label_content', '--from', str(labels), '--apply',
                         '--hashes', str(hashes), '--backup', str(backup),
                         stdout=out)
            self.assertIn('пропущено задач 1', out.getvalue())
            self.assertEqual(json.loads(backup.read_text()),
                             {str(self.task.pk): []})
        self.assertTrue(self.task.facet_values.filter(code='ABS_EQ').exists())
        self.assertFalse(other.facet_values.exists())

    def test_param_tag_dropped_only_with_param_value(self):
        from .models import Tag
        tag = Tag.objects.create(name='задача с параметром')
        plain = Task.objects.create(text_latex='при каких a')
        self.task.tags.add(tag)
        plain.tags.add(tag)
        ct.apply_labels({self.task.pk: ['PARAM_EQ']})
        stats = ct.drop_param_tag()
        self.assertEqual(stats, {'removed': [self.task.pk], 'kept': [plain.pk]})
        self.assertFalse(self.task.tags.exists())
        self.assertTrue(plain.tags.exists())

    def test_backup_failure_leaves_tag(self):
        from .models import Tag
        tag = Tag.objects.create(name='задача с параметром')
        self.task.tags.add(tag)
        ct.apply_labels({self.task.pk: ['PARAM_EQ']})
        with self.assertRaises(OSError):
            call_command('label_content', '--drop-param-tag', '--apply',
                         '--backup', '/нет/такого/каталога/rollback.json',
                         stdout=StringIO())
        self.assertTrue(self.task.tags.filter(pk=tag.pk).exists())


class BatchHashesTests(TestCase):
    def setUp(self):
        call_command('label_content', '--seed', stdout=StringIO())

    def test_folder_brings_its_own_hashes(self):
        same = Task.objects.create(text_latex='Куб')
        edited = Task.objects.create(text_latex='Трапеция')
        with tempfile.TemporaryDirectory() as tmp:
            call_command('label_content', '--make-batches', tmp, '--ids',
                         f'{same.pk},{edited.pk}', stdout=StringIO())
            hashes = json.loads((Path(tmp) / ct.HASHES_NAME).read_text())
            self.assertEqual(hashes[str(same.pk)], ct.task_text_hash(same))
            (Path(tmp) / 'batch_001.answer.json').write_text(json.dumps(
                {'items': [{'id': same.pk, 'codes': ['ST_CUBE']},
                           {'id': edited.pk, 'codes': ['QUAD_TRAPEZOID']}]}))
            edited.text_latex = 'Трапеция, исправленное условие'
            edited.save(update_fields=['text_latex'])
            out, err = StringIO(), StringIO()
            call_command('label_content', '--from', tmp, '--apply',
                         stdout=out, stderr=err)
        self.assertIn('пропущено задач 1', out.getvalue())
        self.assertNotIn('Без отпечатков', err.getvalue())
        self.assertTrue(same.facet_values.filter(code='ST_CUBE').exists())
        self.assertFalse(edited.facet_values.exists())

    def test_warns_without_hashes(self):
        task = Task.objects.create(text_latex='Куб')
        with tempfile.NamedTemporaryFile('w', suffix='.json',
                                         delete=False) as fh:
            json.dump({str(task.pk): ['ST_CUBE']}, fh)
        err = StringIO()
        call_command('label_content', '--from', fh.name, stdout=StringIO(),
                     stderr=err)
        self.assertIn('Без отпечатков', err.getvalue())

"""Исключения применяются только к совпавшему источнику и полному блоку."""
import hashlib
from copy import deepcopy
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase
from .ostromogilsky_pdf_repairs import matching_repairs, attach_pdf_repairs, PLOT_IDS, read_repair_spec
from .textbook_parser import ImportBundle, TaskDraft


class VerifiedPdfRepairTests(SimpleTestCase):
    def setUp(self):
        self.spec = read_repair_spec()
        self.sources = {key:row['source'] for key,row in self.spec['tasks'].items()}
        self.image = b'original-image'
        self.spec['shared']['image_sha256'] = hashlib.sha256(self.image).hexdigest()
        self.spec['shared']['mask_sha256'] = hashlib.sha256(b'').hexdigest()
        self.common = self.spec['shared']['source']

    def test_any_changed_question_or_image_rejects_whole_plot(self):
        for key in PLOT_IDS:
            sources = dict(self.sources)
            sources[key] += ' Другой вопрос.'
            self.assertEqual(list(matching_repairs(sources,self.common,self.image,self.spec)),['8.32'])
        self.assertEqual(list(matching_repairs(self.sources,self.common,b'changed-image',self.spec)),['8.32'])
        self.assertEqual(list(matching_repairs(self.sources,self.common+' Изменение.',self.image,self.spec)),['8.32'])

    def test_radical_requires_its_exact_source(self):
        sources = dict(self.sources)
        sources['8.32'] = sources['8.32'].replace('16','18')
        self.assertNotIn('8.32',matching_repairs(sources,self.common,self.image,self.spec))
        result=matching_repairs(self.sources,self.common,self.image,self.spec)
        self.assertIn(r'\sqrt{\frac{4a^{16}}{a^{12}}}',result['8.32']['body'])

    def test_plot_is_consecutive_with_own_numbers_answers_and_no_mutation(self):
        def draft(key):
            return TaskDraft(external_id=key,source_number=key,source_path=['Практические задачи'],
                             collection_key='oge',collection_title='ОГЭ',topic_original='Участки',
                             text_latex='Исходный вопрос',review_status='approved',tags=['DEMO'])
        initial=[draft(key) for key in ['2.4','3.4','4.4','5.4','8.31']]
        original=deepcopy(initial)
        bundle=ImportBundle(1,'ostromogilsky',{},initial,{'missing_task_ids':['1.4','8.32']})
        repairs=matching_repairs(self.sources,self.common,self.image,self.spec)
        answers={key:f'${n}$' for n,key in enumerate(PLOT_IDS+['8.32'],1)}
        with TemporaryDirectory() as directory:
            attach_pdf_repairs(bundle,repairs,answers,directory)
            self.assertEqual([t.external_id for t in bundle.tasks],PLOT_IDS+['8.31','8.32'])
            self.assertEqual([t.author_answer_latex for t in bundle.tasks[:5]],[answers[k] for k in PLOT_IDS])
            self.assertEqual([t.exam_item_codes for t in bundle.tasks[:5]],[[f'OGE_2026_{n:02}'] for n in range(1,6)])
            self.assertEqual(bundle.tasks[0].review_status,'needs_review')
            self.assertEqual(bundle.tasks[0].tags,[])
            self.assertEqual(bundle.tasks[1].review_status,'approved')
            self.assertEqual(bundle.diagnostics['missing_task_ids'],[])
            before=deepcopy(bundle.tasks)
            attach_pdf_repairs(bundle,repairs,answers,directory)
            self.assertEqual(bundle.tasks,before)
            self.assertEqual(initial,original)

    def test_missing_answer_does_not_partially_restore_shared_block(self):
        reference=TaskDraft(external_id='2.4',source_number='2.4',source_path=[],collection_key='',
                            collection_title='',topic_original='',text_latex='Вопрос')
        bundle=ImportBundle(1,'ostromogilsky',{},[reference],{})
        repairs=matching_repairs(self.sources,self.common,self.image,self.spec)
        with TemporaryDirectory() as directory:
            self.assertEqual(attach_pdf_repairs(bundle,repairs,{'1.4':'$7425$'},directory),[])
            self.assertEqual(bundle.tasks,[reference])

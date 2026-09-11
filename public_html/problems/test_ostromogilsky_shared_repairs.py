"""Общий блок восстанавливается целиком, а не по отдельным совпавшим вопросам."""
import hashlib
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase
from .ostromogilsky_shared_repairs import match_shared_repair,attach_shared_repairs
from .textbook_parser import ImportBundle,TaskDraft


class SharedRepairTests(SimpleTestCase):
    def test_pdf_soft_mask_is_composited_on_white_without_resizing(self):
        from io import BytesIO
        import pymupdf
        from PIL import Image
        from .ostromogilsky_pdf_repairs import pdf_image_on_white
        image=Image.new('RGBA',(2,1))
        image.putdata([(0,0,0,255),(0,0,0,0)])
        stream=BytesIO()
        image.save(stream,format='PNG')
        with pymupdf.open() as doc:
            page=doc.new_page()
            page.insert_image(pymupdf.Rect(0,0,20,10),stream=stream.getvalue())
            info=page.get_images()[0]
            self.assertTrue(info[1])
            result=Image.open(BytesIO(pdf_image_on_white(doc,info)))
            self.assertEqual(result.size,(2,1))
            self.assertEqual(result.getpixel((0,0)),(0,0,0))
            self.assertEqual(result.getpixel((1,0)),(255,255,255))

    def setUp(self):
        self.keys=[f'{n}.7.4' for n in range(1,6)]
        self.spec={'suffix':'7.4','source':'Общий текст.', 'common_latex':'Общий текст.\\taskpic{1}',
                   'image_sha256':hashlib.sha256(b'plan').hexdigest(),'image_stem':'shared-plan',
                   'questions':{key:{'source':f'Вопрос {n}.','latex':f'Вопрос ${n}$.'} for n,key in enumerate(self.keys,1)}}
        self.sources={key:row['source'] for key,row in self.spec['questions'].items()}

    def test_each_question_and_image_are_required(self):
        self.assertTrue(match_shared_repair(self.spec,'Общий текст.',self.sources,b'plan'))
        for key in self.keys:
            damaged={**self.sources,key:'Другое условие.'}
            self.assertFalse(match_shared_repair(self.spec,'Общий текст.',damaged,b'plan'))
        self.assertFalse(match_shared_repair(self.spec,'Общий текст.',self.sources,b'other-plan'))
        self.assertFalse(match_shared_repair(self.spec,'Другой текст.',self.sources,b'plan'))
        self.assertFalse(match_shared_repair(self.spec,'Общий текст.',self.sources,b'plan',b'changed-mask'))

    def test_keeps_order_answers_statuses_and_original_objects(self):
        tasks=[TaskDraft(external_id=key,source_number=key,source_path=[],collection_key='',collection_title='',
                         topic_original='',text_latex='Старый вопрос',author_answer_latex=f'${n}$',review_status='approved')
               for n,key in enumerate(self.keys,1)]
        original=deepcopy(tasks)
        bundle=ImportBundle(1,'ostromogilsky',{},tasks,{})
        with TemporaryDirectory() as directory:
            attach_shared_repairs(bundle,[{**self.spec,'image':b'plan'}],directory)
            self.assertEqual([t.external_id for t in bundle.tasks],self.keys)
            self.assertEqual([t.author_answer_latex for t in bundle.tasks],[f'${n}$' for n in range(1,6)])
            self.assertTrue(all(t.review_status=='approved' for t in bundle.tasks))
            self.assertTrue(all(t.text_latex.startswith(self.spec['common_latex']) for t in bundle.tasks))
            self.assertEqual((Path(directory)/'shared-plan.png').read_bytes(),b'plan')
            before=deepcopy(bundle.tasks)
            attach_shared_repairs(bundle,[{**self.spec,'image':b'plan'}],directory)
            self.assertEqual(bundle.tasks,before)
            self.assertEqual(tasks,original)

    def test_incomplete_group_is_not_changed(self):
        task=TaskDraft(external_id=self.keys[0],source_number=self.keys[0],source_path=[],collection_key='',
                       collection_title='',topic_original='',text_latex='Вопрос')
        bundle=ImportBundle(1,'ostromogilsky',{},[task],{})
        with TemporaryDirectory() as directory:
            self.assertEqual(attach_shared_repairs(bundle,[{**self.spec,'image':b'plan'}],directory),[])
            self.assertEqual(bundle.tasks,[task])
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_neighbor_tail_is_removed_only_when_it_matches_restored_common(self):
        spec=deepcopy(self.spec)
        spec['common_latex']='На рисунке изображён новый план.\\taskpic{1}'
        def draft(key,text,images=None):
            return TaskDraft(external_id=key,source_number=key,source_path=[],collection_key='',
                             collection_title='',topic_original='',text_latex=text,images=images or [])
        own='На рисунке изображён прежний план.\\taskpic{1}\n\nСколько стоит доставка?'
        for changed in [False,True]:
            tail=spec['common_latex'].replace('taskpic{1}','taskpic{2}')
            if changed:tail=tail.replace('новый','иной')
            neighbor=draft('5.7.3',own+'\n\n'+tail,['own','next'])
            bundle=ImportBundle(1,'ostromogilsky',{},[neighbor]+[draft(k,'Вопрос') for k in self.keys],{})
            with TemporaryDirectory() as directory:
                attach_shared_repairs(bundle,[{**spec,'image':b'plan'}],directory)
            result=bundle.tasks[0]
            self.assertEqual(result.text_latex,neighbor.text_latex if changed else own)
            self.assertEqual(result.images,['own','next'] if changed else ['own'])
            self.assertEqual(neighbor.images,['own','next'])

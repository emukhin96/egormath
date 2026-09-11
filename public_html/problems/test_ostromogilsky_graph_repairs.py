"""Восстановление рисунков не меняет авторский ключ и не теряет замечания."""
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
from django.test import SimpleTestCase
from .ostromogilsky_graph_repairs import (attach_graph_repairs,
                                          graph_repair_specs)
from .textbook_parser import ImportBundle,TaskDraft


class GraphRepairTests(SimpleTestCase):
    def test_11_9_6_uses_positive_slope_after_source_match(self):
        row = next(
            item for item in graph_repair_specs()
            if item['id'] == '11.9.6')
        self.assertIn('А) $y=\\frac{1}{5} \\cdot x-4$', row['latex'])
        self.assertNotIn('А) $y=-\\frac{1}{5}', row['latex'])
        self.assertIn('А) y= −1 5', row['source'])
        self.assertEqual(row['warnings'], [])

    def test_label_correction_uses_separate_page_copy(self):
        from unittest.mock import MagicMock,patch
        from .ostromogilsky_graph_repairs import extract_graph_repairs
        doc,copy_doc=MagicMock(),MagicMock()
        doc.__enter__.return_value=doc
        doc.resolve_names.return_value={'task::11.3.4':{'page':0}}
        original=doc.__getitem__.return_value
        original.get_text.return_value='Задача 11.3.4.\nУсловие.\nОглавление'
        original.get_textbox.return_value='À'
        copy_doc.__getitem__.return_value.get_pixmap.return_value.tobytes.return_value=b'png'
        spec={'id':'11.3.4','source':'Условие.','clip':[0,0,100,100],
              'label_correction':{'bbox':[1,1,10,10],'origin':[1,8],'size':10,'old':'À','new':'B'}}
        with patch('pymupdf.open',side_effect=[doc,copy_doc]),patch(
                'problems.ostromogilsky_graph_repairs.graph_repair_specs',return_value=[spec]):
            result=extract_graph_repairs('source.pdf')
        self.assertEqual(result[0]['image'],b'png')
        original.add_redact_annot.assert_not_called()
        original.apply_redactions.assert_not_called()
        copy_doc.insert_pdf.assert_called_once_with(doc,from_page=0,to_page=0)
        copy_doc.__getitem__.return_value.add_redact_annot.assert_called_once()
        copy_doc.close.assert_called_once()

    def test_preserves_answer_status_and_source_warning(self):
        task=TaskDraft(external_id='11.9.6',source_number='11.9.6',source_path=[],collection_key='',
                       collection_title='',topic_original='',text_latex='OCR',images=['a','b','c'],
                       author_answer_latex='$321$',review_status='approved',exam_item_codes=['OGE_2026_11'])
        original=deepcopy(task)
        bundle=ImportBundle(1,'ostromogilsky',{},[task],{})
        row={'id':'11.9.6','latex':'Проверенное условие.\\taskpic{1}','image_stem':'labelled',
             'image':b'png','warnings':['Противоречие в источнике: наклон не соответствует рисунку.']}
        with TemporaryDirectory() as directory:
            attach_graph_repairs(bundle,[row],directory)
            result=bundle.tasks[0]
            self.assertEqual(result.author_answer_latex,'$321$')
            self.assertEqual(result.review_status,'approved')
            self.assertEqual(result.exam_item_codes,['OGE_2026_11'])
            self.assertIn(row['warnings'][0],result.warnings)
            self.assertEqual(result.images,['labelled'])
            self.assertEqual((Path(directory)/'labelled.png').read_bytes(),b'png')
            before=deepcopy(bundle.tasks)
            attach_graph_repairs(bundle,[row],directory)
            self.assertEqual(bundle.tasks,before)
            self.assertEqual(task,original)

    def test_unknown_id_is_not_created_from_another_task(self):
        bundle=ImportBundle(1,'ostromogilsky',{},[],{})
        with TemporaryDirectory() as directory:
            self.assertEqual(attach_graph_repairs(bundle,[{'id':'11.1'}],directory),[])
            self.assertEqual(bundle.tasks,[])
            self.assertEqual(list(Path(directory).iterdir()),[])

"""Графические варианты восстанавливаются только для целого совпавшего условия."""
from unittest.mock import MagicMock,patch
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase
from .ostromogilsky_graph_repairs import extract_graph_repairs
from .ostromogilsky_inequality_figures import attach_inequality_figures
from .textbook_parser import ImportBundle,TaskDraft


class InequalityFigureTests(SimpleTestCase):
    def test_answer_blank_limits_source_without_losing_variants(self):
        spec={'id':'13.4','source':'Условие. 1) A 2) B 3) C 4) D',
              'clip':[0,0,100,100],'end_at_answer':True,'scale':3}
        for valid in [True,False]:
            doc=MagicMock();doc.__enter__.return_value=doc
            doc.resolve_names.return_value={'task::13.4':{'page':0}}
            page=doc.__getitem__.return_value
            source='Условие. 1) A 2) B 3) C 4) D' if valid else 'Условие. 1) A 2) B 3) C'
            page.get_text.return_value='Задача 13.4.\n'+source+'\nОтвет:\nНавигация'
            page.get_pixmap.return_value.tobytes.return_value=b'png'
            with patch('pymupdf.open',return_value=doc):
                result=extract_graph_repairs('source.pdf',[spec])
            self.assertEqual(len(result),1 if valid else 0)
            if not valid:page.get_pixmap.assert_not_called()

    def test_preserves_key_and_does_not_overwrite_graph_diagnostics(self):
        task=TaskDraft(external_id='13.4',source_number='13.4',source_path=[],collection_key='',
                       collection_title='',topic_original='',text_latex='OCR',author_answer_latex='$3$',
                       exam_item_codes=['OGE_2026_13'],review_status='approved')
        bundle=ImportBundle(1,'ostromogilsky',{},[task],{'pdf_graph_repairs':['11.3']})
        row={'id':'13.4','latex':'Условие.\\taskpic{1}','image':b'png','image_stem':'choices'}
        with TemporaryDirectory() as directory:
            attach_inequality_figures(bundle,[row],directory)
        self.assertEqual(bundle.tasks[0].author_answer_latex,'$3$')
        self.assertEqual(bundle.tasks[0].exam_item_codes,['OGE_2026_13'])
        self.assertEqual(bundle.tasks[0].review_status,'approved')
        self.assertEqual(bundle.tasks[0].images,['choices'])
        self.assertEqual(bundle.diagnostics['pdf_graph_repairs'],['11.3'])
        self.assertEqual(bundle.diagnostics['pdf_inequality_figures'],['13.4'])

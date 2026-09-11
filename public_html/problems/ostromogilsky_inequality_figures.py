"""Подписанные графические варианты неравенств, сверенные с PDF."""
import json
from pathlib import Path
from .ostromogilsky_graph_repairs import extract_graph_repairs,attach_graph_repairs


def inequality_figure_specs():
    return json.loads((Path(__file__).parent/'data'/'ostromogilsky_inequality_figures.json').read_text())


def extract_inequality_figures(pdf_path):
    """Проверяет условие и извлекает целую полосу вариантов с номерами."""
    return extract_graph_repairs(pdf_path,inequality_figure_specs())


def attach_inequality_figures(bundle,figures,dest):
    """Сохраняет порядок вариантов, исходные ответы и метки задач."""
    return attach_graph_repairs(
        bundle,figures,dest,diagnostic_key='pdf_inequality_figures',
        message='Условие и графические варианты восстановлены по совпавшему тексту PDF; требуется сверка')

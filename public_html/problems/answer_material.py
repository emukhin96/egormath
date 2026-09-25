"""Ответы и решения задачи для веб-рамки: происхождение и второй вариант.

У задачи и подпункта два поля на ответ и два на решение: авторское (из
задачника) и редакторское / AI. В рамке основной — авторский вариант,
редакторский показывается вместо него, когда авторского нет, и под
спойлером, когда они расходятся. Здесь собирается структура для
``problems/_task_answers.html``: строки с меткой происхождения, общая
метка на рамку (если она одинаковая у всех строк) и список расхождений.
"""
import re

from worksheets.latex import subitem_label

SOURCE_AUTHOR = 'author'
SOURCE_AI = 'ai'
SOURCE_MIXED = 'mixed'

_HINT_RE = re.compile(r'^\s*Указание[.:]?\s*', re.IGNORECASE)


def _clean(value):
    return (value or '').strip()


def _same(left, right):
    """Одинаковые по сути ответы: «$0$» и «$0$.» — одно и то же.

    Регистр сохраняется: «$A$» и «$a$» — разные ответы, как и команды
    LaTeX с заглавной буквой.
    """
    def key(value):
        value = re.sub(r'\s+', ' ', _clean(value))
        return value.rstrip('.').strip()
    return key(left) == key(right)


def _row(owner, label, author_field, ai_field):
    author = _clean(getattr(owner, author_field))
    ai = _clean(getattr(owner, ai_field))
    if not author and not ai:
        return None
    return {
        'label': label,
        'text': author or ai,
        'source': SOURCE_AUTHOR if author else SOURCE_AI,
        'alt': ai if author and ai and not _same(author, ai) else '',
    }


def _block(task, subitems, author_field, ai_field):
    rows = [_row(task, '', author_field, ai_field)]
    rows += [_row(sub, subitem_label(index), author_field, ai_field)
             for index, sub in enumerate(subitems)]
    rows = [row for row in rows if row]
    if not rows:
        return None
    sources = {row['source'] for row in rows}
    return {
        'rows': rows,
        'source': sources.pop() if len(sources) == 1 else SOURCE_MIXED,
        'alts': [row for row in rows if row['alt']],
    }


def answer_material(task, subitems=None):
    """Структура рамки «Ответ / Решение» или ``None``, если показывать нечего.

    ``subitems`` — подпункты, выбранные в листке (по умолчанию все).
    """
    if subitems is None:
        subitems = list(task.subitems.all())
    else:
        subitems = list(subitems)
    answer = _block(task, subitems, 'author_answer_latex', 'answer_latex')
    solution = _block(task, subitems, 'author_solution_latex',
                      'solution_latex')
    if solution:
        # Авторское «Указание. …» из задачника — заголовок рамки, а не
        # часть текста; полное AI-решение при этом остаётся под спойлером.
        hint = (solution['source'] == SOURCE_AUTHOR
                and all(_HINT_RE.match(row['text']) for row in solution['rows']))
        solution['heading'] = 'Указание' if hint else 'Решение'
        if hint:
            for row in solution['rows']:
                stripped = _HINT_RE.sub('', row['text'], count=1)
                row['text'] = stripped or row['text']
        solution['alt_title'] = ('Полное решение от AI' if hint
                                 else 'Редакторский / AI-вариант решения')
    if not answer and not solution:
        return None
    return {'answer': answer, 'solution': solution}

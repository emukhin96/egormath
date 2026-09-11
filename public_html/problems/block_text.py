"""Разделение общего условия и вопросов без потери исходного текста."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CommonCondition:
    prefixes: tuple[str, ...]
    questions: tuple[str, ...]
    image_positions: tuple[int, ...]

    @property
    def text(self):
        return self.prefixes[0]


def _tokens(text):
    # Пробелы, переносы и границы математического режима не меняют содержание.
    # Замена сохраняет длину строки, поэтому позиции остаются исходными.
    return list(re.finditer(r'\\taskpic\{\d+\}|\\[A-Za-z]+|[^\s$]',
                            text.replace('\\\\', '  ')))


def _complete_fragment(text):
    if not text.endswith(('.', ':', '!', '?')):
        return False
    if len(re.findall(r'(?<!\\)\$', text)) % 2:
        return False
    stack = []
    for match in re.finditer(r'\\(begin|end)\{([^}]+)\}', text):
        kind, name = match.groups()
        if kind == 'begin':
            stack.append(name)
        elif not stack or stack.pop() != name:
            return False
    return not stack


def split_common_condition(texts, image_keys):
    """Возвращает общий текст пяти вопросов либо None при неоднозначности.

    image_keys содержит идентификаторы изображений в порядке taskpic каждой
    карточки. Разные изображения при одинаковых номерах не объединяются.
    Исходные префиксы и остатки сохраняются посимвольно, включая пробелы.
    """
    if len(texts) != 5 or len(image_keys) != 5:
        return None
    token_lists = [_tokens(text) for text in texts]
    count = 0
    for group in zip(*token_lists):
        if len({token.group(0) for token in group}) != 1:
            break
        count += 1
    if count < 100:
        return None
    ends = [tokens[count - 1].end() for tokens in token_lists]
    prefixes = tuple(text[:end] for text, end in zip(texts, ends))
    questions = tuple(text[end:] for text, end in zip(texts, ends))
    if not all(_complete_fragment(prefix) for prefix in prefixes):
        return None
    if not all(question.strip() and question[0].isspace() for question in questions):
        return None
    positions = tuple(int(n) for n in re.findall(r'\\taskpic\{(\d+)\}', prefixes[0]))
    resolved = []
    for keys in image_keys:
        if any(position < 1 or position > len(keys) for position in positions):
            return None
        resolved.append(tuple(keys[position - 1] for position in positions))
    if any(keys != resolved[0] for keys in resolved[1:]):
        return None
    return CommonCondition(prefixes, questions, positions)

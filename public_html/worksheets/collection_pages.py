"""Страницы подборки по параграфам.

Каталожная подборка из задачника — это глава: сотни задач и рубрики «§ N».
Резать её по 25 элементов подряд нельзя: страница начинается посреди
параграфа без заголовка. Здесь элементы группируются по рубрикам, и
единицей пагинации становится параграф (длинный делится на части, каждая
часть повторяет заголовок с пометкой «продолжение»). Подборка без рубрик
листается, как раньше, по ``PLAIN_PAGE_SIZE`` элементов.
"""
import re
from dataclasses import dataclass, field

PLAIN_PAGE_SIZE = 25
SECTION_PAGE_SIZE = 60
SECTION_PART_SIZE = 30

_SECTION_NUMBER_RE = re.compile(r'^\s*§\s*(\d+)')


@dataclass
class Section:
    """Рубрика подборки и элементы за ней (сама рубрика — ``heading``)."""
    index: int
    heading: object = None
    items: list = field(default_factory=list)

    @property
    def title(self):
        return self.heading.rubric if self.heading is not None else ''

    @property
    def number(self):
        """Номер параграфа из «§ 3. …» или None."""
        match = _SECTION_NUMBER_RE.match(self.title)
        return int(match.group(1)) if match else None

    @property
    def tasks_total(self):
        return sum(1 for item in self.items if item.task_id)


@dataclass
class Block:
    """Параграф (или его часть) на странице."""
    section: Section
    part: int
    parts: int
    items: list

    @property
    def continued(self):
        return self.part > 1

    @property
    def tasks_total(self):
        return sum(1 for item in self.items if item.task_id)


@dataclass
class Chunk:
    """Одна страница: несколько коротких параграфов подряд или часть длинного."""
    blocks: list
    first_task_number: int = 0

    @property
    def section_indexes(self):
        return {block.section.index for block in self.blocks}

    @property
    def title(self):
        """Заголовок страницы: единственный параграф или «§ 1–§ 3»."""
        titles = [block.section.title for block in self.blocks
                  if block.section.title]
        if len(titles) == 1:
            return titles[0]
        return ''


def split_sections(items):
    """Элементы подборки → список параграфов в порядке следования.

    Элементы до первой рубрики образуют параграф без заголовка.
    """
    sections = []
    current = None
    for item in items:
        if item.is_rubric:
            current = Section(index=len(sections), heading=item)
            sections.append(current)
            continue
        if current is None:
            current = Section(index=0)
            sections.append(current)
        current.items.append(item)
    return sections


def build_chunks(items):
    """Страницы подборки. Возвращает ``(sections, chunks)``.

    Без рубрик — куски по ``PLAIN_PAGE_SIZE``. С рубриками страница
    набирается целыми параграфами подряд, пока их суммарная длина не
    превысит ``SECTION_PAGE_SIZE``; параграф длиннее лимита делится на
    части по ``SECTION_PART_SIZE``, и заголовок повторяется на каждой.
    """
    sections = split_sections(items)
    sectioned = any(section.heading is not None for section in sections)
    if not sectioned:
        rows = [item for section in sections for item in section.items]
        section = sections[0] if sections else Section(index=0)
        pieces = [rows[i:i + PLAIN_PAGE_SIZE]
                  for i in range(0, len(rows), PLAIN_PAGE_SIZE)] or [[]]
        chunks, number = [], 0
        for part, piece in enumerate(pieces, start=1):
            block = Block(section=section, part=1, parts=1, items=piece)
            chunks.append(Chunk(blocks=[block], first_task_number=number))
            number += block.tasks_total
        return sections, chunks

    pages = []          # списки блоков
    current, current_len = [], 0
    for section in sections:
        rows = section.items
        if len(rows) > SECTION_PAGE_SIZE:
            if current:
                pages.append(current)
                current, current_len = [], 0
            pieces = [rows[i:i + SECTION_PART_SIZE]
                      for i in range(0, len(rows), SECTION_PART_SIZE)]
            for part, piece in enumerate(pieces, start=1):
                pages.append([Block(section, part, len(pieces), piece)])
            continue
        if current and current_len + len(rows) > SECTION_PAGE_SIZE:
            pages.append(current)
            current, current_len = [], 0
        current.append(Block(section, 1, 1, rows))
        current_len += len(rows)
    if current:
        pages.append(current)
    chunks, number = [], 0
    for blocks in pages:
        chunk = Chunk(blocks=blocks, first_task_number=number)
        chunks.append(chunk)
        number += sum(block.tasks_total for block in blocks)
    return sections, chunks


def section_pages(chunks):
    """Номер страницы, с которой начинается каждый параграф: {index: page}."""
    pages = {}
    for page, chunk in enumerate(chunks, start=1):
        for block in chunk.blocks:
            pages.setdefault(block.section.index, page)
    return pages


def sections_out_of_order(sections):
    """Параграфы с номерами, идущие не по возрастанию (для проверки данных)."""
    numbered = [section for section in sections if section.number is not None]
    return [section for previous, section in zip(numbered, numbered[1:])
            if section.number < previous.number]

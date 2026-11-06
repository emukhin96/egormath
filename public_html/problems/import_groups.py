"""Список партий импорта задачников по книгам (ревизия интерфейса 03.11, T4).

Явного признака «пробная партия» у TextbookImportBatch нет, поэтому правило
такое. Партии группируются по книге — короткому имени источника
(Source.short_name): у одной книги бывает несколько записей Source с тем же
коротким именем (Шестаков). В каждой книге выбирается текущая партия:
самая новая из загруженных в каталог (статус «Загружена» или хотя бы один
черновик со статусом «Импортировано»), а если такой нет — самая новая из
полных партий (с наибольшим числом черновиков). Партии новее загруженной
остаются в работе (повторная сверка после загрузки). Всё остальное — партии
старше текущей и партии без черновиков — уходит в свёрнутый «Архив».
"""
from dataclasses import dataclass, field


@dataclass
class BookGroup:
    title: str
    short: str
    batches: list = field(default_factory=list)


def _is_loaded(batch):
    return (batch.status == batch.STATUS_IMPORTED
            or getattr(batch, 'imported_total', 0) > 0)


def _current(batches):
    """Текущая партия книги; batches — от новых к старым."""
    loaded = [batch for batch in batches if _is_loaded(batch)]
    if loaded:
        return loaded[0], True
    with_drafts = [batch for batch in batches if batch.total]
    if not with_drafts:
        return None, False
    most = max(batch.total for batch in with_drafts)
    return next(batch for batch in with_drafts if batch.total == most), False


def group_import_batches(batches):
    """(активные книги, архивные книги): списки BookGroup в порядке самой
    новой партии книги; партии внутри книги — от новых к старым. У партий
    ожидаются аннотации total и imported_total."""
    books = {}
    for batch in sorted(batches, key=lambda b: (b.created_at, b.pk), reverse=True):
        # Одна книга — записи Source с общим коротким именем (у Шестакова
        # их четыре); без короткого имени — сам источник: одноимённые
        # «Алгебра 8» разных авторов не сливаются в одну книгу.
        source = batch.source
        key = ('short', source.short_title) if source.short_title else ('pk', source.pk)
        if key not in books:
            books[key] = (source, [])
        books[key][1].append(batch)
    active, archive = [], []
    for (source, items) in books.values():
        short = source.short_name
        current, loaded = _current(items)
        keep, old = [], []
        for batch in items:
            newer = current is not None and (batch.created_at, batch.pk) > (current.created_at, current.pk)
            if batch is current or (loaded and newer and batch.total):
                keep.append(batch)
            else:
                old.append(batch)
        # Подпись к короткому имени: полное «Авторы. Название», а если
        # короткого имени нет — только авторы, без повтора названия
        title = str(source) if source.title != short else (source.author or '')
        if keep:
            active.append(BookGroup(title, short, keep))
        if old:
            archive.append(BookGroup(title, short, old))
    return active, archive

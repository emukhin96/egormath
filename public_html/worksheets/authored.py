"""Авторские листки в «Подборках»: перенос туда и обратно.

Листок из корпуса (или любой свой) — законченное произведение, из которого
обычно берут задачи, а не выдают «как есть». Поэтому его место — в каталоге
подборок, а не среди рабочих листков. Перенос — это только строка
``Collection`` поверх того же ``Worksheet``: содержимое, владелец, выданные
задания и ссылки не меняются; «Мои листки» и корзина уже исключают листки
с ``collection``.

Разделы источника «Авторские листки»: по классам, «ОГЭ» и «ЕГЭ» — если
большинство задач листка помечено заданиями соответствующего экзамена,
«Разное» — без класса. Раздел — подборка с пустым листком-контейнером,
создаётся при первом переносе. Новая подборка видна только автору
(``is_published=False``); публикация переключается отдельно.
"""
from django.db import transaction

from problems.models import ExamModel

from .corpus import SOURCE_TITLE, corpus_key_from_comment, ensure_source
from .models import Collection, Worksheet

SECTION_PREFIX = 'section:'
EXAM_SECTIONS = {
    ExamModel.TYPE_OGE: ('exam:OGE', 'ОГЭ', 200),
    ExamModel.TYPE_EGE_BASE: ('exam:EGE', 'ЕГЭ', 210),
    ExamModel.TYPE_EGE_PROFILE: ('exam:EGE', 'ЕГЭ', 210),
}
MISC_SECTION = ('misc', 'Разное', 300)


class AuthoredError(ValueError):
    pass


def is_section(collection):
    return collection.locator.startswith(SECTION_PREFIX)


def exam_type_for(worksheet):
    """Экзамен, которым помечено большинство задач листка, или None."""
    items = list(worksheet.items.filter(
        deleted_at__isnull=True, task__isnull=False)
        .values_list('task_id', 'task__exam_items__exam_model__exam_type'))
    if not items:
        return None
    total = len({task_id for task_id, _ in items})
    counts = {}
    for task_id, exam_type in items:
        if exam_type:
            counts.setdefault(exam_type, set()).add(task_id)
    for exam_type, tasks in sorted(counts.items(), key=lambda kv: -len(kv[1])):
        if len(tasks) * 2 > total:
            return exam_type
    return None


def section_for(worksheet):
    """(locator без префикса, название, порядок) раздела для листка."""
    exam_type = exam_type_for(worksheet)
    if exam_type in EXAM_SECTIONS:
        return EXAM_SECTIONS[exam_type]
    if worksheet.grade:
        grade = min(worksheet.grade, 10)
        title = '10–11 класс' if grade == 10 else f'{grade} класс'
        return (f'grade:{grade}', title, grade * 10)
    return MISC_SECTION


SECTIONS_USERNAME = 'authored-sections'


def sections_owner():
    """Системный владелец листков-контейнеров разделов.

    Раздел общий для всех учителей, поэтому его листок не должен
    принадлежать тому, кто перенёс первую подборку: иначе он мог бы
    удалить или отредактировать контейнер через обычные view листка
    (Worksheet.visible_to по владельцу) — с каскадом на чужие подборки.
    Неактивный пользователь без профиля: войти им нельзя, в списках
    учеников/учителей он не появляется.
    """
    from django.contrib.auth import get_user_model
    user, _ = get_user_model().objects.get_or_create(
        username=SECTIONS_USERNAME,
        defaults={'is_active': False, 'first_name': 'Авторские',
                  'last_name': 'листки'})
    return user


def ensure_section(source, key, title, order, owner=None):
    """Раздел-контейнер (пустой листок) — общий для всех учителей.

    ``owner`` не используется: контейнер всегда у системного владельца.
    """
    locator = SECTION_PREFIX + key
    section = Collection.objects.filter(source=source, locator=locator).first()
    if section is not None:
        return section
    container = Worksheet.objects.create(
        title=title, owner=sections_owner(), comment='authored-section')
    return Collection.objects.create(
        worksheet=container, source=source, parent=None, locator=locator,
        source_path=[SOURCE_TITLE, title], order=order, is_published=True)


def collection_locator(worksheet):
    key = corpus_key_from_comment(worksheet.comment)
    return f'corpus:{key}' if key else f'ws:{worksheet.pk}'


@transaction.atomic
def move_to_collections(worksheet, owner):
    """Листок → подборка в разделе по классу/экзамену. Возвращает Collection."""
    if Collection.objects.filter(worksheet=worksheet).exists():
        raise AuthoredError('Листок уже в подборках.')
    if not worksheet.items.filter(deleted_at__isnull=True).exists():
        raise AuthoredError('Пустой листок в подборки не переносится.')
    source = ensure_source()
    key, title, order = section_for(worksheet)
    section = ensure_section(source, key, title, order, owner)
    locator = collection_locator(worksheet)
    if Collection.objects.filter(source=source, locator=locator).exists():
        locator = f'ws:{worksheet.pk}'
    return Collection.objects.create(
        worksheet=worksheet, source=source, parent=section, locator=locator,
        source_path=[SOURCE_TITLE, title], order=0, is_published=False)


@transaction.atomic
def move_to_worksheets(collection):
    """Подборка → обратно в «Мои листки». Возвращает Worksheet."""
    if is_section(collection):
        raise AuthoredError('Раздел нельзя вернуть в листки.')
    if collection.source.title != SOURCE_TITLE:
        raise AuthoredError('В листки возвращаются только авторские подборки.')
    worksheet = collection.worksheet
    collection.delete()
    return worksheet


def set_published(collection, published):
    collection.is_published = bool(published)
    collection.save(update_fields=['is_published'])
    return collection


def authored_candidates():
    """Загруженные из корпуса листки, которые ещё не в подборках."""
    from .corpus import CORPUS_MARK
    return (Worksheet.objects.filter(comment__startswith=CORPUS_MARK,
                                     collection__isnull=True)
            .select_related('owner').order_by('grade', 'title', 'pk'))

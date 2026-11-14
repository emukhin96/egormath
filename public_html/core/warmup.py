"""Прогрев процесса и воркера до первого запроса (deploy/vps/gunicorn.conf.py).

Без прогрева первый запрос к свежему воркеру на проде занимал 1,2–2,2 с:
импорт sympy, грамматика Earley вычислителя масок, холодные файловые
кэши справочников (контроль прода 11.11.2026, docs/PERF_AUDIT_2026-11.md,
раздел 10). ``warm_process`` не трогает базу и годится для мастера
gunicorn до fork; ``warm_worker`` ходит в базу и закрывает за собой
соединение (его же вызывает ``manage.py warm_caches`` после сброса кэша
в deploy.sh).
"""
import logging

logger = logging.getLogger(__name__)

# Маска со всеми тяжёлыми путями разбора: число с корнем (sympy через
# raw_tree), промежуток (parse_range), формула (FormulaSpec без вычислителя).
WARMUP_MASK = r'{{number: \sqrt{2}+1}} {{range: x>1, x\ne 3}} {{expression: x^2-1}}'


# Шаблоны разделов, которые открывают первыми: компиляция — в мастере.
WARMUP_TEMPLATES = (
    'base.html', 'accounts/dashboard_teacher.html', 'accounts/dashboard_student.html',
    'problems/task_list.html', 'problems/task_detail.html',
    'worksheets/worksheet_list.html', 'worksheets/worksheet_detail.html',
    'worksheets/collection_list.html', 'worksheets/collection_detail.html',
    'assignments/assignment_list.html', 'assignments/assignment_detail.html',
    'independentworks/attempt.html',
)


def warm_process():
    """Импорт и грамматика — только память процесса, без базы."""
    import sympy  # noqa: F401 — 0,2–0,3 с на Mac, ×2,5 на VPS
    from django.template import TemplateDoesNotExist
    from django.template.loader import get_template
    from django.urls import get_resolver

    from assignments.checks import expressions
    from assignments.checks.mask import parse_mask

    # URLconf тянет за собой все модули представлений (~0,4 с импорта на
    # первом запросе), шаблоны компилируются в кэш загрузчика
    get_resolver().url_patterns
    for name in WARMUP_TEMPLATES:
        try:
            get_template(name)
        except TemplateDoesNotExist:
            logger.warning('warmup: шаблона %s нет', name)
    expressions._lark()
    spec = parse_mask(WARMUP_MASK)
    if not spec.is_valid:
        logger.warning('warmup: маска прогрева не разобралась: %s', spec.errors)
    return spec


# Сколько масок открытых проведений разобрать заранее: кабинет и каталог
# самостоятельных парсят их все при каждом показе
WARMUP_POINTS = 400


def warm_worker():
    """Справочники из базы — в файловые кэши, маски открытых
    самостоятельных — в кэш вычислителя; соединение закрыть."""
    from django.db import connections

    from problems.rubricator import taxonomy_catalog
    from worksheets.collection_catalog import catalog_nodes

    try:
        taxonomy_catalog()
        catalog_nodes()
        return warm_open_masks()
    finally:
        connections.close_all()


def warm_open_masks(limit=WARMUP_POINTS):
    """Маски пунктов проведений с незакрытыми попытками (их парсит кабинет
    учителя при каждом показе — teacher_home.review_runs)."""
    from assignments.checks.mask import parse_mask
    from independentworks.models import Point

    # DISTINCT по JSON в MySQL ненадёжен — дубли убираем в Python
    snapshots = (Point.objects.filter(variant__run__issued_at__isnull=False,
                                      variant__run__attempts__submitted_at__isnull=True)
                 .order_by('-pk').values_list('snapshot', flat=True)[:limit * 4])
    masks = []
    for snapshot in snapshots:
        mask = (snapshot or {}).get('mask')
        if mask and mask not in masks:
            masks.append(mask)
            if len(masks) >= limit:
                break
    for mask in masks:
        parse_mask(mask)
    return len(masks)

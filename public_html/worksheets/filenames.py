"""Имена PDF листка: «предмет + класс — название латиницей».

math8-kvadratnye-uravneniya.pdf, geom9-podobie-treugolnikov-otvety.pdf.
Предмет — по корневой теме рубрикатора (ALG → alg, GEO → geom, STA →
stat или teorver); если тем несколько или их нет — math. В 5–6 классах
предмет один — математика, поэтому там всегда math.
"""
import re
from collections import Counter

_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}

# Корневые коды рубрикатора → предмет. ARI и COM — общая «математика».
_SUBJECT_BY_ROOT = {'ALG': 'alg', 'GEO': 'geom', 'STA': 'stat'}
# Вероятностные разделы STA (STA.03 и дальше) — теорвер, а не статистика
_STAT_ONLY = ('STA.01', 'STA.02')
DEFAULT_SUBJECT = 'math'

# Служебные слова в имени файла не нужны: «Отрезки в треугольнике» →
# otrezki-treugolnike
_STOP_WORDS = {'и', 'в', 'во', 'на', 'с', 'со', 'к', 'ко', 'о', 'об', 'по',
               'для', 'от', 'до', 'из', 'а', 'у', 'за', 'при'}
SLUG_LIMIT = 40

VARIANT_SUFFIX = {'answers': '-otvety', 'teacher': '-resheniya'}


def translit(text):
    """Кириллица → латиница, без пробелов и спецсимволов."""
    out = ''.join(_TRANSLIT.get(ch, ch) for ch in text.lower())
    return re.sub(r'[^a-z0-9]+', '', out)


def title_slug(title, limit=SLUG_LIMIT):
    """Первые значимые слова названия целиком, через дефис, до limit символов."""
    words = [translit(w) for w in re.findall(r'[а-яёa-z0-9]+', title.lower())
             if w not in _STOP_WORDS]
    slug = ''
    for word in filter(None, words):
        candidate = f'{slug}-{word}' if slug else word
        if slug and len(candidate) > limit:
            break
        slug = candidate[:limit]
    return slug


def _majority(values):
    """Значение, которого больше половины; иначе None."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    value, count = Counter(values).most_common(1)[0]
    return value if count * 2 > len(values) else None


def _topic_subject(topic, topics_by_id):
    """Предмет темы по её корню (и второму уровню для STA)."""
    chain = [topic]
    while chain[-1].parent_id and chain[-1].parent_id in topics_by_id:
        chain.append(topics_by_id[chain[-1].parent_id])
    root = chain[-1]
    subject = _SUBJECT_BY_ROOT.get(root.code or '', DEFAULT_SUBJECT)
    if subject == 'stat':
        section = chain[-2] if len(chain) > 1 else None
        if section is not None and (section.code or '') not in _STAT_ONLY:
            return 'teorver'
    return subject


def worksheet_subject(worksheet, grade):
    """Предмет листка: явные темы листка, иначе большинство тем задач."""
    from problems.models import TaskTopic, Topic

    if grade is not None and grade <= 6:
        return DEFAULT_SUBJECT
    topics_by_id = {t.pk: t for t in Topic.objects.all()}
    explicit = [topics_by_id[pk] for pk in
                worksheet.topics.values_list('pk', flat=True)
                if pk in topics_by_id]
    if explicit:
        subjects = {_topic_subject(t, topics_by_id) for t in explicit}
        return subjects.pop() if len(subjects) == 1 else DEFAULT_SUBJECT

    # Каждая задача голосует основной темой (или первой попавшейся)
    task_ids = worksheet.items.filter(
        deleted_at__isnull=True, task__isnull=False
    ).values_list('task_id', flat=True)
    topic_by_task = {}
    links = (TaskTopic.objects.filter(task_id__in=task_ids)
             .order_by('task_id', '-role')
             .values_list('task_id', 'topic_id', 'role'))
    for task_id, topic_id, role in links:
        if task_id not in topic_by_task or role == TaskTopic.ROLE_PRIMARY:
            topic_by_task[task_id] = topic_id
    votes = [_topic_subject(topics_by_id[pk], topics_by_id)
             for pk in topic_by_task.values() if pk in topics_by_id]
    return _majority(votes) or DEFAULT_SUBJECT


def worksheet_grade(worksheet):
    """Класс листка: поле «Класс», единственная метка класса или класс задач."""
    from problems.models import normalize_grade_level

    if worksheet.grade:
        return normalize_grade_level(worksheet.grade)
    bands = list(worksheet.grade_bands.values_list('code', flat=True))
    if len(bands) == 1:
        match = re.match(r'GRADE_(\d+)', bands[0])
        if match:
            return int(match.group(1))
    grades = worksheet.items.filter(
        deleted_at__isnull=True, task__isnull=False
    ).values_list('task__grade_level', flat=True)
    return normalize_grade_level(_majority(list(grades)))


def auto_basename(worksheet):
    """math8-kvadratnye-uravneniya: предмет, класс, название латиницей."""
    grade = worksheet_grade(worksheet)
    prefix = f'{worksheet_subject(worksheet, grade)}{grade or ""}'
    slug = title_slug(worksheet.title)
    return f'{prefix}-{slug}' if slug else prefix

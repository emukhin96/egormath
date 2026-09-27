#!/usr/bin/env python3
"""Сводка по логу доступа gunicorn (egormath-web) для решения о масштабировании.

Читает stdin — вывод `docker logs --timestamps egormath-egormath-web-1`
(обычно через log-report.sh) — и печатает:
  * число запросов, долю ошибок, p50/p95/p99 времени ответа;
  * то же отдельно для учебных часов (будни 8–18 МСК);
  * самый нагруженный час и минуту (запросов в секунду);
  * 20 адресов, на которые ушло больше всего серверного времени;
  * 10 самых долгих отдельных запросов.
Цифры в адресах заменяются на N, query string отбрасывается.
Только стандартная библиотека: запускается python3 на хосте.
"""
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))
LINE = re.compile(
    r'^(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\S*\s+.*?'
    r'"(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[\d.]+" (?P<status>\d{3}) \S+ (?P<ms>\d+)ms\s*$')
LESSON_HOURS = range(8, 18)


def normalize(path):
    path = path.split('?', 1)[0]
    path = re.sub(r'/live/[0-9a-f]{32}\.txt$', '/live/<token>.txt', path)
    return re.sub(r'\d+', 'N', path)


def pct(values, q):
    if not values:
        return 0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q / 100 * (len(values) - 1))))]


def summary(title, rows):
    times = [r['ms'] for r in rows]
    errors = sum(1 for r in rows if r['status'] >= 500)
    print(f'{title}: {len(rows)} запросов, 5xx: {errors}'
          f' · p50 {pct(times, 50)} мс · p95 {pct(times, 95)} мс · p99 {pct(times, 99)} мс')


def main():
    rows = []
    for line in sys.stdin:
        m = LINE.match(line.strip())
        if not m:
            continue
        ts = datetime.fromisoformat(m['ts']).replace(tzinfo=timezone.utc).astimezone(MSK)
        rows.append({'ts': ts, 'method': m['method'], 'path': normalize(m['path']),
                     'raw': m['path'], 'status': int(m['status']), 'ms': int(m['ms'])})
    if not rows:
        print('Нет строк лога доступа — проверьте формат (нужен %(M)sms в конце).')
        return
    print(f'Период: {rows[0]["ts"]:%d.%m %H:%M} — {rows[-1]["ts"]:%d.%m %H:%M} МСК')
    summary('Всего', rows)
    lesson = [r for r in rows if r['ts'].weekday() < 5 and r['ts'].hour in LESSON_HOURS]
    summary('Учебные часы (будни 8–18)', lesson)
    app = [r for r in rows if r['path'] != '/healthz']
    per_hour = Counter(r['ts'].strftime('%d.%m %H:00') for r in app)
    per_min = Counter(r['ts'].strftime('%d.%m %H:%M') for r in app)
    if per_hour:
        hour, n = per_hour.most_common(1)[0]
        print(f'Пиковый час: {hour} — {n} запросов')
        minute, n = per_min.most_common(1)[0]
        print(f'Пиковая минута: {minute} — {n} запросов ({n / 60:.1f} в секунду)')
    cpu = sum(r['ms'] for r in app) / 1000
    span = max((rows[-1]['ts'] - rows[0]['ts']).total_seconds(), 1)
    print(f'Серверное время: {cpu:.0f} с за {span / 3600:.1f} ч'
          f' (в среднем {cpu / span:.3f} потока занято)')

    by_path = defaultdict(list)
    for r in app:
        by_path[(r['method'], r['path'])].append(r['ms'])
    print('\nАдреса по суммарному серверному времени:')
    print(f'{"сумм., с":>9} {"запросов":>9} {"p50":>6} {"p95":>6} {"max":>6}  адрес')
    for (method, path), times in sorted(by_path.items(), key=lambda kv: -sum(kv[1]))[:20]:
        print(f'{sum(times) / 1000:9.1f} {len(times):9} {pct(times, 50):6} '
              f'{pct(times, 95):6} {max(times):6}  {method} {path}')
    print('\nСамые долгие запросы:')
    for r in sorted(app, key=lambda r: -r['ms'])[:10]:
        print(f'{r["ms"]:7} мс  {r["ts"]:%d.%m %H:%M}  {r["status"]}  {r["method"]} {r["raw"][:90]}')


if __name__ == '__main__':
    main()

"""Замер каталога на отдельной тестовой базе из 10 000 задач.

Из корня: ./venv/bin/python tools/benchmark_catalog.py --seed
Повторный замер: та же команда без --seed.
MySQL: добавьте --mysql; база egormath_perf_stage1 должна существовать,
подключение — локальный root через /tmp/mysql.sock. Прод не используется.
"""
import os, sys, json, time, statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'public_html'))
os.environ['DJANGO_SETTINGS_MODULE']='core.settings'
from django.conf import settings
mysql = '--mysql' in sys.argv
if mysql:
    import pymysql
    pymysql.install_as_MySQLdb()
    pymysql.version_info=(2, 0, 0)
    settings.DATABASES={'default':{'ENGINE':'django.db.backends.mysql','NAME':'egormath_perf_stage1','USER':'root','HOST':'/tmp/mysql.sock','OPTIONS':{'charset':'utf8mb4'}}}
else:
    settings.DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':'/tmp/egormath_perf_stage1.sqlite3'}}
settings.ALLOWED_HOSTS=['testserver','127.0.0.1','localhost']
import django
django.setup()
from django.core.management import call_command
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.contrib.auth import get_user_model
from problems.models import Task, Topic, GradeBand, Source, TaskSource, TaskSubitem, TaskTopic
from problems.views import task_list
from django.db import transaction
if '--seed' in sys.argv:
    if 'problems_task' in connection.introspection.table_names() and Task.objects.exists():
        raise SystemExit('Тестовая база уже заполнена; запустите без --seed.')
    call_command('migrate',verbosity=0)
    call_command('seed_rubricator',verbosity=0)
    user=get_user_model().objects.create_superuser(username='perf',password=None)
    topics=list(Topic.objects.filter(code__isnull=False)[:30])
    bands=list(GradeBand.objects.all())
    with transaction.atomic():
        tasks=Task.objects.bulk_create([Task(text_latex=f'Задача {i}. Решите уравнение $x^2-5x+6=0$.',text_plain=f'Задача {i}. Решите уравнение x^2-5x+6=0.',author_answer_latex='$2;3$',author_solution_latex='Разложим на множители: $(x-2)(x-3)=0$. '*10,created_by=user) for i in range(10000)],batch_size=500)
        if not tasks[0].pk: tasks=list(Task.objects.all())
        TaskTopic.objects.bulk_create([TaskTopic(task=t,topic=topics[i%len(topics)],role=TaskTopic.ROLE_PRIMARY) for i,t in enumerate(tasks)],batch_size=500)
        through=Task.grade_bands.through
        through.objects.bulk_create([through(task_id=t.pk,gradeband_id=bands[i%len(bands)].pk) for i,t in enumerate(tasks)],batch_size=500)
        source=Source.objects.create(title='Нагрузочный задачник')
        TaskSource.objects.bulk_create([TaskSource(task=t,source=source,number=str(i),locator=str(i)) for i,t in enumerate(tasks)],batch_size=500)
        TaskSubitem.objects.bulk_create([TaskSubitem(task=t,order=n,text_latex='$x+1=2$',author_answer_latex='$1$') for t in tasks for n in (10,20)],batch_size=500)
user=get_user_model().objects.filter(is_superuser=True).first()
topic=Task.objects.filter(grade_bands__code='GRADE_10_11').first().topics.first().pk
for params in ({},{'page':400},{'q':'уравнение'},{'topic':topic,'grade':'GRADE_10_11'}):
    runs=[]
    for i in range(6):
        request=RequestFactory().get('/problems/',params); request.user=user; request.session={}
        start=time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            response=task_list(request)
        runs.append({'ms':round((time.perf_counter()-start)*1000,2),'sql_ms':round(sum(float(q['time']) for q in queries)*1000,2),'queries':len(queries),'html_bytes':len(response.content)})
    print(json.dumps({'engine':connection.vendor,'params':params,'median_ms':statistics.median(r['ms'] for r in runs[1:]),'runs':runs},ensure_ascii=False))

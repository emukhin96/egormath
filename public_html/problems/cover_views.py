"""Файл обложки задачника (``Source.cover``) для полок «Подборок».

``/media/`` сайт наружу не раздаёт — файлы идут через view, как картинки
задач (``task_image_file``). Обложка — не тайна, но полки видят только
учителя, поэтому и файл — им. Браузер держит её сутки: команда
``source_covers --force`` пишет новый файл под тем же именем, а ссылка в
шаблоне несёт ``?v=<время изменения>``, чтобы новая обложка показалась
сразу.
"""
import mimetypes

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control

from accounts.decorators import teacher_required

from .models import Source


@teacher_required
@cache_control(private=True, max_age=86400)
def source_cover(request, pk):
    source = get_object_or_404(Source, pk=pk)
    if not source.cover or not source.cover.storage.exists(source.cover.name):
        raise Http404
    # Команда пишет JPEG, но в админке можно загрузить PNG/WebP — тип по
    # имени файла (с nosniff и суточным кэшем неверный тип прилипнет)
    content_type = mimetypes.guess_type(source.cover.name)[0] or 'image/jpeg'
    return FileResponse(source.cover.open('rb'), content_type=content_type)

"""Файловый кэш с редкой чисткой — для больших долгоживущих кэшей (``numeric``).

``FileBasedCache`` при каждом ``set()`` вызывает ``_cull()``, а тот
перечисляет все файлы каталога (glob). При десятках тысяч записей каждый
промах вычислителя масок платил бы за обход каталога примерно столько,
сколько кэш экономит на разборе (ревью PR #345). Здесь каталог
пересчитывается раз в ``CULL_EVERY`` записей процесса; переполнение сверх
``MAX_ENTRIES`` — не больше ``CULL_EVERY`` файлов, что для кэша значений
безразлично.
"""
from django.core.cache.backends.filebased import FileBasedCache


class SparseCullFileBasedCache(FileBasedCache):
    def __init__(self, dir, params):
        super().__init__(dir, params)
        options = params.get('OPTIONS', {})
        try:
            self._cull_every = max(1, int(options.get('CULL_EVERY', 500)))
        except (ValueError, TypeError):
            self._cull_every = 500
        # Первая запись процесса каталог проверяет: вдруг он уже переполнен
        self._sets_since_cull = self._cull_every

    def _cull(self):
        self._sets_since_cull += 1
        if self._sets_since_cull <= self._cull_every:
            return
        self._sets_since_cull = 1
        super()._cull()

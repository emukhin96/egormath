"""Статика с хэшем содержимого в имени (прод)."""
from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class HashedStaticFilesStorage(ManifestStaticFilesStorage):
    """Как ManifestStaticFilesStorage, но мягче: файл, которого нет ни в
    манифесте, ни на диске, отдаётся по обычному пути, а не роняет страницу;
    исходник Tailwind не обрабатывается — его `@import "tailwindcss"` не файл."""

    manifest_strict = False
    skip_post_process = ('css/input.css',)

    def post_process(self, paths, dry_run=False, **options):
        paths = {name: value for name, value in paths.items()
                 if not name.replace('\\', '/').endswith(self.skip_post_process)}
        return super().post_process(paths, dry_run, **options)

    def stored_name(self, name):
        try:
            return super().stored_name(name)
        except ValueError:
            return name

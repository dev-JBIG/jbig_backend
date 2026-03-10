from django.apps import AppConfig


class RecruitmentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'recruitments'
    verbose_name = '모집 관리'

    def ready(self):
        import recruitments.signals  # noqa: F401

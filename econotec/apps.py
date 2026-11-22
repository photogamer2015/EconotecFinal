from django.apps import AppConfig


class EconotecConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'econotec'
    verbose_name = 'Econotec'

    def ready(self):
        from . import signals  # noqa: F401  (avisos push de las campanitas)

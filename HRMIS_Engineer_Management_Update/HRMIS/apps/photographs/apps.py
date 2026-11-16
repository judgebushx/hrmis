from django.apps import AppConfig
class PhotographsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.photographs"
    def ready(self):
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass

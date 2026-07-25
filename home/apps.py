from django.apps import AppConfig


def sync_site_domain(**kwargs):
    from django.conf import settings

    site_id = getattr(settings, 'SITE_ID', None)
    if not site_id:
        return

    from django.contrib.sites.models import Site

    Site.objects.update_or_create(
        pk=site_id,
        defaults={
            'domain': settings.SITE_DOMAIN,
            'name': settings.SITE_NAME,
        },
    )


class HomeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'home'

    def ready(self):
        from django.db.models.signals import post_migrate

        post_migrate.connect(sync_site_domain, dispatch_uid='home.sync_site_domain')

from django.conf import settings


def site_info(request):
    return {"site_author": settings.SITE_AUTHOR}

from django.conf import settings


def normalize_media_relative_path(raw_path):
    path = str(raw_path or "").strip().replace("\\", "/")
    if not path:
        return ""

    media_url = str(settings.MEDIA_URL or "/media/").strip()
    media_prefix = media_url.strip("/")
    media_root = str(settings.MEDIA_ROOT or "").strip().replace("\\", "/").strip("/")

    if media_url and path.startswith(media_url):
        path = path[len(media_url):]
    elif media_prefix and path.startswith(f"{media_prefix}/"):
        path = path[len(media_prefix) + 1:]
    elif media_root and path.startswith(f"{media_root}/"):
        path = path[len(media_root) + 1:]

    return path.lstrip("/")


def build_media_file_url(request, raw_path):
    normalized_path = normalize_media_relative_path(raw_path)
    return request.build_absolute_uri(f"{settings.MEDIA_URL}{normalized_path}")

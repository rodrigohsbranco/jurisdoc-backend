from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),          # login/refresh
    path("api/accounts/", include("accounts.api_urls")),  # << CRUD de usuários
    path("api/templates/", include("templates_app.urls")),
    path("api/petitions/", include("petitions.urls")),
    path("api/cadastro/", include("cadastro.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

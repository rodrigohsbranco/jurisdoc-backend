from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve
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
    path("api/reports/", include("reports.urls")),
    path("api/kits/", include("kits.urls")),
    path("api/bancos-kit/", include(("kits.urls_bancos", "bancos-kit"))),
    path("api/tarifas-kit/", include(("kits.urls_tarifas", "tarifas-kit"))),
    path("api/associacoes-kit/", include(("kits.urls_associacoes", "associacoes-kit"))),
    path("api/advogados/", include("advogados.urls")),
    path("api/permissoes/", include("permissoes.urls")),
    path("api/catalogo/", include("kits.urls_publico")),
    path("api/app/", include("cadastro.urls_app")),
    path("api/app/", include("advogados.urls_app")),
    path("api/app/", include("kits.urls_app")),
    path("api/zapsign/", include("kits.urls_zapsign")),
    path("api/maps/", include("kits.urls_maps")),
    path("api/", include("contracts.urls")),
    # Portal público de assinatura (link único entregue ao cliente)
    path("", include("kits.urls_portal")),
    # Serve media files via Django (funciona em produção e desenvolvimento)
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]

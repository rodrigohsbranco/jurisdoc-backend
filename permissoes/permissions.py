"""
Permission classes baseadas no sistema de Capacidade/Permissao.

Uso típico em viewsets:

    class ClientesViewSet(viewsets.ModelViewSet):
        def get_permissions(self):
            return [HasCapability.for_action(self.action, {
                "list": "clientes.visualizar",
                "retrieve": "clientes.visualizar",
                "create": "clientes.criar",
                "update": "clientes.editar",
                "partial_update": "clientes.editar",
                "destroy": "clientes.deletar",
            })]

Admin (`user.is_admin=True`) sempre passa, independente de Permissao.
"""
from __future__ import annotations

from rest_framework import permissions


_CACHE_ATTR = "_jurisdoc_caps_cache"


def user_capacidades(user) -> set[str]:
    """Conjunto plano de códigos de capacidade do usuário (via permissao FK).

    Cacheia o resultado no próprio objeto user (request-scoped) para evitar
    queries repetidas quando várias permissions classes checam o mesmo user
    no mesmo request.
    """
    if not user or not user.is_authenticated:
        return set()
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None:
        return cached
    codigos: set[str] = set()
    permissao = getattr(user, "permissao", None)
    if permissao:
        codigos |= set(permissao.capacidades.values_list("codigo", flat=True))
    # Capacidades concedidas diretamente ao usuário (fora do perfil).
    if hasattr(user, "capacidades_diretas"):
        codigos |= set(user.capacidades_diretas.values_list("codigo", flat=True))
    setattr(user, _CACHE_ATTR, codigos)
    return codigos


def user_has_capability(user, codigo: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_admin", False):
        return True
    return codigo in user_capacidades(user)


# ---------------------------------------------------------------------------
# Capacidades sensíveis — NÃO herdadas por admin.
# Diferente do padrão do sistema (onde is_admin=True passa em tudo), estas
# precisam ser concedidas explicitamente via Permissao, mesmo para admins.
# ---------------------------------------------------------------------------
CAP_HONORARIOS_INICIAIS = "kits.honorarios_iniciais"
CAPACIDADES_SEM_BYPASS_ADMIN = {CAP_HONORARIOS_INICIAIS}


def user_has_capability_estrita(user, codigo: str) -> bool:
    """Checa a capacidade SEM o atalho de admin.

    Para capacidades sensíveis, admin também só passa se a capacidade estiver
    de fato atribuída à sua Permissao.
    """
    if not user or not user.is_authenticated:
        return False
    return codigo in user_capacidades(user)


class HasCapability(permissions.BasePermission):
    """
    Use como factory: `HasCapability("clientes.criar")` ou via `for_action`.
    """
    codigo: str | None = None

    def __init__(self, codigo: str | None = None):
        if codigo is not None:
            self.codigo = codigo

    def __call__(self, *args, **kwargs):
        return self

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_admin", False):
            return True
        if not self.codigo:
            return False
        return user_has_capability(user, self.codigo)

    @classmethod
    def for_action(cls, action: str, mapping: dict[str, str]):
        """Helper para `get_permissions` em viewsets — devolve instância
        configurada com o código mapeado ou, na ausência, exige só auth."""
        codigo = mapping.get(action)
        if codigo is None:
            return permissions.IsAuthenticated()
        return cls(codigo)

from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q

from accounts.permissions import IsAdmin  # noqa: F401 (mantido por compat)
from permissoes.permissions import HasCapability
from .models import Advogado, OabUf
from .serializers import (
    AdvogadoDetailSerializer,
    AdvogadoListSerializer,
    OabUfSerializer,
)


class AdvogadoViewSet(viewsets.ModelViewSet):
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["is_socio", "ativo"]
    search_fields = ["nome_completo"]
    ordering_fields = ["nome_completo", "criado_em"]
    ordering = ["-is_socio", "nome_completo"]

    def get_queryset(self):
        return Advogado.objects.prefetch_related("oabs").all()

    def get_serializer_class(self):
        if self.action == "list":
            return AdvogadoListSerializer
        return AdvogadoDetailSerializer

    def get_permissions(self):
        return [HasCapability.for_action(self.action, {
            "list": "advogados.visualizar",
            "retrieve": "advogados.visualizar",
            "por_uf": "advogados.visualizar",
            "create": "advogados.criar",
            "update": "advogados.editar",
            "partial_update": "advogados.editar",
            "destroy": "advogados.deletar",
        })]

    @action(detail=False, methods=["get"], url_path="por-uf")
    def por_uf(self, request):
        """Retorna advogados ativos que atuam em uma UF específica, com suas OABs."""
        uf = request.query_params.get("uf", "").upper()
        if not uf or len(uf) != 2:
            return Response({"detail": "Informe o parâmetro 'uf' (2 caracteres)."}, status=400)

        advogados = Advogado.objects.filter(
            ativo=True,
        ).filter(
            Q(is_socio=True) | Q(oabs__uf=uf),
        ).prefetch_related("oabs").distinct()

        result = []
        for adv in advogados:
            oab = adv.oabs.filter(uf=uf).first()
            # oab_fonte alinhado ao snapshot: "uf_cliente" quando a OAB bate
            # com a UF do cliente; "fallback_sc" quando o sócio cai na OAB/SC.
            # Consumido pelo front para só usar a unidade de apoio da UF certa.
            oab_fonte = "uf_cliente" if oab else ""
            if not oab and adv.is_socio:
                oab = adv.oabs.filter(uf="SC").first()
                oab_fonte = "fallback_sc" if oab else ""
            result.append({
                "id": adv.id,
                "nome_completo": adv.nome_completo,
                "nacionalidade": adv.nacionalidade,
                "estado_civil": adv.estado_civil,
                "genero": adv.genero,
                "is_socio": adv.is_socio,
                "escritorio_nome": adv.escritorio_nome,
                "escritorio_cnpj": adv.escritorio_cnpj,
                "tipos_acao": (oab.tipos_acao if oab else None) or [],
                "numero_oab": oab.numero_oab if oab else "",
                "oab_fonte": oab_fonte,
                "unidade_apoio_nome": oab.unidade_apoio_nome if oab else "",
                "unidade_apoio_endereco": oab.unidade_apoio_endereco if oab else "",
            })

        return Response(result)


class OabUfViewSet(viewsets.ModelViewSet):
    serializer_class = OabUfSerializer

    def get_permissions(self):
        # OAB é sub-recurso de Advogado — escreve = editar advogado, ler = visualizar
        return [HasCapability.for_action(self.action, {
            "list": "advogados.visualizar",
            "retrieve": "advogados.visualizar",
            "create": "advogados.editar",
            "update": "advogados.editar",
            "partial_update": "advogados.editar",
            "destroy": "advogados.editar",
        })]

    def get_queryset(self):
        return OabUf.objects.filter(advogado_id=self.kwargs["advogado_pk"])

    def perform_create(self, serializer):
        advogado = Advogado.objects.get(pk=self.kwargs["advogado_pk"])
        serializer.save(advogado=advogado)

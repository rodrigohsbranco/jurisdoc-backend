from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q

from accounts.permissions import IsAdmin
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
        if self.action == "por_uf":
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsAdmin()]

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
            if not oab and adv.is_socio:
                oab = adv.oabs.filter(uf="SC").first()
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
                "unidade_apoio_nome": oab.unidade_apoio_nome if oab else "",
                "unidade_apoio_endereco": oab.unidade_apoio_endereco if oab else "",
            })

        return Response(result)


class OabUfViewSet(viewsets.ModelViewSet):
    serializer_class = OabUfSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get_queryset(self):
        return OabUf.objects.filter(advogado_id=self.kwargs["advogado_pk"])

    def perform_create(self, serializer):
        advogado = Advogado.objects.get(pk=self.kwargs["advogado_pk"])
        serializer.save(advogado=advogado)

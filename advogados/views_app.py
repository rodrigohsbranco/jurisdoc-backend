from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q

from accounts.service_auth import IsServiceClient, ServiceClientAuthentication
from .models import Advogado
from .serializers import AdvogadoListSerializer


class AdvogadoAppViewSet(viewsets.ReadOnlyModelViewSet):
    authentication_classes = [ServiceClientAuthentication]
    permission_classes = [IsServiceClient]
    serializer_class = AdvogadoListSerializer
    pagination_class = None
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["is_socio"]
    search_fields = ["nome_completo"]
    ordering_fields = ["nome_completo", "is_socio"]
    ordering = ["-is_socio", "nome_completo"]

    def get_queryset(self):
        return Advogado.objects.filter(ativo=True).prefetch_related("oabs").all()

    @action(detail=False, methods=["get"], url_path="por-uf")
    def por_uf(self, request):
        """
        Retorna advogados ativos que atuam em uma UF específica, com dados da OAB relevante.
        Sócios aparecem mesmo sem OAB cadastrada na UF (usam a OAB de SC como base).
        Parâmetro obrigatório: ?uf=SC
        """
        uf = request.query_params.get("uf", "").upper().strip()
        if not uf or len(uf) != 2:
            return Response({"detail": "Informe o parâmetro 'uf' com a sigla do estado (2 caracteres)."}, status=400)

        advogados = (
            Advogado.objects.filter(ativo=True)
            .filter(Q(is_socio=True) | Q(oabs__uf=uf))
            .prefetch_related("oabs")
            .distinct()
            .order_by("-is_socio", "nome_completo")
        )

        result = []
        for adv in advogados:
            adv_oabs = list(adv.oabs.all())  # usa o prefetch, sem query extra
            oab = next((o for o in adv_oabs if o.uf == uf), None)
            if not oab and adv.is_socio:
                oab = next((o for o in adv_oabs if o.uf == "SC"), None)
            result.append({
                "id": adv.id,
                "nome_completo": adv.nome_completo,
                "nacionalidade": adv.nacionalidade,
                "estado_civil": adv.estado_civil,
                "genero": adv.genero,
                "is_socio": adv.is_socio,
                "escritorio_nome": adv.escritorio_nome,
                "escritorio_cnpj": adv.escritorio_cnpj,
                "escritorio_endereco": adv.escritorio_endereco,
                "numero_oab": oab.numero_oab if oab else "",
                "uf_oab": oab.uf if oab else "",
                "unidade_apoio_nome": oab.unidade_apoio_nome if oab else "",
                "unidade_apoio_endereco": oab.unidade_apoio_endereco if oab else "",
                "tipos_acao": (oab.tipos_acao if oab else None) or [],
            })

        return Response(result)

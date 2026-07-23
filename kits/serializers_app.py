from rest_framework import serializers

from cadastro.serializers import ClienteSerializer
from cadastro.media_paths import build_media_file_url

from .models import DocumentoKit, Kit
from .serializers import AcaoKitSerializer
from .services_documentos import KIT_TEMPLATE_DEFS

# Tipos que exigem numero_contrato (idêntico à constante do frontend TIPOS_COM_CONTRATO)
_TIPOS_COM_CONTRATO = {
    "cartao_credito_consignado",
    "rmc",
    "rcc",
    "emprestimo_nao_autorizado",
}


class AcaoKitAppSerializer(AcaoKitSerializer):
    """Estende AcaoKitSerializer com validações server-side para a API do app.

    O JurisDoc interno delega essas validações ao frontend; no app precisamos
    garantir consistência independentemente do cliente que faz a requisição.
    Não altera nada do fluxo do JurisDoc interno.
    """

    def validate(self, attrs):
        attrs = super().validate(attrs)  # roda validações do serializer base

        tipo_acao = attrs.get("tipo_acao") or (
            getattr(self.instance, "tipo_acao", "") if self.instance else ""
        )

        # numero_contrato obrigatório para RMC, RCC, Empréstimo não autorizado, Cartão Crédito
        if tipo_acao in _TIPOS_COM_CONTRATO:
            val = str(
                attrs.get("numero_contrato")
                or (getattr(self.instance, "numero_contrato", None) if self.instance else None)
                or ""
            ).strip()
            if not val:
                raise serializers.ValidationError(
                    {"numero_contrato": "Campo obrigatório para este tipo de ação."}
                )

        # tarifa_questionada obrigatória para Tarifa Bancária
        if tipo_acao == "tarifa_bancaria":
            val = str(
                attrs.get("tarifa_questionada")
                or (getattr(self.instance, "tarifa_questionada", None) if self.instance else None)
                or ""
            ).strip()
            if not val:
                raise serializers.ValidationError(
                    {"tarifa_questionada": "Campo obrigatório para Tarifa Bancária."}
                )

        # tipo_seguro obrigatório para Seguro Não Autorizado
        if tipo_acao == "seguro_nao_autorizado":
            val = str(
                attrs.get("tipo_seguro")
                or (getattr(self.instance, "tipo_seguro", None) if self.instance else None)
                or ""
            ).strip()
            if not val:
                raise serializers.ValidationError(
                    {"tipo_seguro": "Campo obrigatório para Seguro Não Autorizado."}
                )

        # tipo_contribuicao obrigatório apenas para Contribuição Sindical em kit de marketing
        if tipo_acao == "contribuicao_sindical_nao_autorizada":
            view = self.context.get("view")
            kit_pk = view.kwargs.get("kit_pk") if view else None
            if kit_pk:
                from .models import Kit as KitModel
                kit_tipo = KitModel.objects.filter(pk=kit_pk).values_list("tipo", flat=True).first()
                if kit_tipo == "marketing":
                    val = str(
                        attrs.get("tipo_contribuicao")
                        or (getattr(self.instance, "tipo_contribuicao", None) if self.instance else None)
                        or ""
                    ).strip()
                    if not val:
                        raise serializers.ValidationError(
                            {"tipo_contribuicao": "Campo obrigatório para Contribuição Sindical em kit de marketing."}
                        )

        return attrs


class AppDocumentoKitSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    nome_arquivo = serializers.SerializerMethodField()
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = DocumentoKit
        fields = ["id", "tipo", "tipo_display", "nome_arquivo", "url", "gerado_em", "zapsign_status"]

    def get_url(self, obj):
        request = self.context.get("request")
        if obj.arquivo and obj.arquivo.name:
            return build_media_file_url(request, obj.arquivo.name)
        return None

    def get_nome_arquivo(self, obj):
        if obj.arquivo and obj.arquivo.name:
            return obj.arquivo.name.split("/")[-1]
        return None


class KitAppListSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source="cliente.nome_completo", read_only=True)
    cliente_cpf = serializers.CharField(source="cliente.cpf", read_only=True)
    total_acoes = serializers.IntegerField(source="acoes.count", read_only=True)
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    requer_acoes = serializers.SerializerMethodField()

    class Meta:
        model = Kit
        fields = [
            "id",
            "tipo",
            "tipo_display",
            "cliente",
            "cliente_nome",
            "cliente_cpf",
            "status",
            "status_display",
            "requer_acoes",
            "total_acoes",
            "origem",
            "app_criado_por_nome",
            "criado_em",
            "atualizado_em",
        ]

    def get_requer_acoes(self, obj):
        return obj.tipo != "previdenciario"


class KitAppDetailSerializer(serializers.ModelSerializer):
    cliente_detail = ClienteSerializer(source="cliente", read_only=True)
    acoes = AcaoKitSerializer(many=True, read_only=True)
    documentos = AppDocumentoKitSerializer(many=True, read_only=True)
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    requer_acoes = serializers.SerializerMethodField()
    documentos_esperados = serializers.SerializerMethodField()

    class Meta:
        model = Kit
        fields = [
            "id",
            "tipo",
            "tipo_display",
            "cliente",
            "cliente_detail",
            "status",
            "status_display",
            "requer_acoes",
            "documentos_esperados",
            "acoes",
            "documentos",
            "advogados_snapshot",
            "clausula_porcentagem_snapshot",
            "zapsign_sign_url",
            "zapsign_status",
            "origem",
            "app_criado_por_nome",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = [
            "id",
            "criado_em",
            "atualizado_em",
            "origem",
            "app_criado_por_nome",
            "advogados_snapshot",
            "clausula_porcentagem_snapshot",
            "zapsign_sign_url",
            "zapsign_status",
        ]

    def get_requer_acoes(self, obj):
        return obj.tipo != "previdenciario"

    def get_documentos_esperados(self, obj):
        defs = KIT_TEMPLATE_DEFS.get(obj.tipo, KIT_TEMPLATE_DEFS["bancario"])
        return [d["key"] for d in defs]


class KitAppCreateSerializer(serializers.ModelSerializer):
    app_criado_por_nome = serializers.CharField(required=True, max_length=200)

    class Meta:
        model = Kit
        fields = [
            "id",
            "tipo",
            "cliente",
            "app_criado_por_nome",
            "status",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "status", "criado_em", "atualizado_em"]

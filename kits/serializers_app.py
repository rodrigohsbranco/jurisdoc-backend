from rest_framework import serializers

from cadastro.serializers import ClienteSerializer
from cadastro.media_paths import build_media_file_url

from .models import DocumentoKit, Kit
from .serializers import AcaoKitSerializer
from .services_documentos import KIT_TEMPLATE_DEFS


class AppDocumentoKitSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    nome_arquivo = serializers.SerializerMethodField()

    class Meta:
        model = DocumentoKit
        fields = ["id", "tipo", "nome_arquivo", "url", "gerado_em"]

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

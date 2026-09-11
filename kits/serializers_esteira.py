"""Contrato da esteira com a aplicação externa.

Serializers próprios, e não os do JurisDoc: o que a aplicação externa consome é
uma interface pública que precisa ser estável, e reaproveitar `KitDetailSerializer`
faria qualquer campo novo do sistema vazar para fora sem ninguém decidir isso.

Fica de fora, deliberadamente, `honorarios_iniciais` — é campo sensível gateado
pela capacidade `kits.honorarios_iniciais`, que nem admin herda; não faz sentido
entregá-lo a um token de serviço.
"""
from rest_framework import serializers

from cadastro.media_paths import build_media_file_url

from .models import AcaoKit, DocumentoKit, Kit


class EsteiraDocumentoSerializer(serializers.ModelSerializer):
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    nome_arquivo = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = DocumentoKit
        fields = ["id", "tipo", "tipo_display", "nome_arquivo", "url", "gerado_em", "zapsign_status"]

    def get_nome_arquivo(self, obj):
        if obj.arquivo and obj.arquivo.name:
            return obj.arquivo.name.split("/")[-1]
        return None

    def get_url(self, obj):
        if obj.arquivo and obj.arquivo.name:
            return build_media_file_url(self.context.get("request"), obj.arquivo.name)
        return None


class EsteiraAcaoSerializer(serializers.ModelSerializer):
    tipo_acao_display = serializers.CharField(source="get_tipo_acao_display", read_only=True)
    banco = serializers.SerializerMethodField()

    class Meta:
        model = AcaoKit
        fields = [
            "id",
            "tipo_acao",
            "tipo_acao_display",
            "banco",
            "numero_contrato",
            "tarifa_questionada",
            "tarifa_questionada_outro",
            "tipo_seguro",
            "tipo_contribuicao",
        ]

    def get_banco(self, obj):
        """Nome do banco já resolvido — 'Outro' sozinho não diz nada a quem consome."""
        return obj.banco_outro if obj.nome_banco == "Outro" else obj.nome_banco


class EsteiraKitListSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source="cliente.nome_completo", read_only=True)
    cliente_cpf = serializers.CharField(source="cliente.cpf", read_only=True)
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    status_esteira_display = serializers.CharField(source="get_status_esteira_display", read_only=True)
    total_acoes = serializers.IntegerField(source="acoes.count", read_only=True)

    class Meta:
        model = Kit
        fields = [
            "id",
            "tipo",
            "tipo_display",
            "cliente_nome",
            "cliente_cpf",
            "total_acoes",
            "via_assinatura",
            "status_esteira",
            "status_esteira_display",
            "entrou_esteira_em",
            "assumido_em",
            "baixado_em",
        ]


class EsteiraKitDetailSerializer(EsteiraKitListSerializer):
    cliente = serializers.SerializerMethodField()
    acoes = EsteiraAcaoSerializer(many=True, read_only=True)
    documentos = EsteiraDocumentoSerializer(many=True, read_only=True)
    advogados = serializers.JSONField(source="advogados_snapshot", read_only=True)

    class Meta(EsteiraKitListSerializer.Meta):
        fields = [
            *EsteiraKitListSerializer.Meta.fields,
            "cliente",
            "acoes",
            "documentos",
            "advogados",
            "criado_em",
        ]

    def get_cliente(self, obj):
        c = obj.cliente
        return {
            "id": c.id,
            "nome_completo": c.nome_completo,
            "cpf": c.cpf,
            "rg": c.rg,
            "orgao_expedidor": c.orgao_expedidor,
            "data_nascimento": c.data_nascimento,
            "nacionalidade": c.nacionalidade,
            "estado_civil": c.estado_civil,
            "profissao": c.profissao,
            "telefone": c.telefone,
            "condicao_cliente": c.condicao_cliente,
            "endereco": {
                "logradouro": c.logradouro,
                "numero": c.numero,
                "complemento": c.complemento,
                "bairro": c.bairro,
                "cidade": c.cidade,
                "cep": c.cep,
                "uf": c.uf,
            },
        }

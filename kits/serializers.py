from django.core.files.storage import default_storage
from rest_framework import serializers

from cadastro.media_paths import build_media_file_url
from cadastro.serializers import ClienteSerializer
from cadastro.validators import validate_uf

from .models import (
    AcaoKit,
    AssociacaoKit,
    BancoKit,
    ClausulaPorcentagemPadrao,
    ClausulaPorcentagemUF,
    DocumentoKit,
    Kit,
    TarifaKit,
)


class AcaoKitSerializer(serializers.ModelSerializer):
    historico_emprestimo_arquivos = serializers.SerializerMethodField()
    historico_credito_arquivos = serializers.SerializerMethodField()
    extrato_bancario_arquivos = serializers.SerializerMethodField()

    historico_emprestimo_files = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False,
    )
    historico_credito_files = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False,
    )
    extrato_bancario_files = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False,
    )

    historico_emprestimo_keep_paths = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
    )
    historico_credito_keep_paths = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
    )
    extrato_bancario_keep_paths = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
    )

    def validate(self, attrs):
        tipo_acao = attrs.get("tipo_acao", getattr(self.instance, "tipo_acao", ""))
        tarifa_questionada = attrs.get("tarifa_questionada", getattr(self.instance, "tarifa_questionada", ""))
        tarifa_questionada_outro = attrs.get("tarifa_questionada_outro", getattr(self.instance, "tarifa_questionada_outro", ""))

        if tipo_acao == "tarifa_bancaria" and tarifa_questionada == "OUTROS" and not str(tarifa_questionada_outro).strip():
            raise serializers.ValidationError({"tarifa_questionada_outro": "Informe a outra tarifa."})

        if tarifa_questionada != "OUTROS":
            attrs["tarifa_questionada_outro"] = ""

        return attrs

    def get_historico_emprestimo_arquivos(self, obj):
        return self._docs_with_urls(self._combined_docs(obj, "historico_emprestimo", "historico_emprestimo_arquivos"))

    def get_historico_credito_arquivos(self, obj):
        return self._docs_with_urls(self._combined_docs(obj, "historico_credito", "historico_credito_arquivos"))

    def get_extrato_bancario_arquivos(self, obj):
        return self._docs_with_urls(self._combined_docs(obj, "extrato_bancario", "extrato_bancario_arquivos"))

    def _docs_with_urls(self, docs):
        request = self.context.get("request")
        if not request:
            return docs
        return [{**doc, "url": build_media_file_url(request, doc.get("path"))} for doc in docs]

    def _legacy_doc(self, instance, file_field_name):
        file_field = getattr(instance, file_field_name)
        if not file_field:
            return None
        path = getattr(file_field, "name", "") or ""
        if not path:
            return None
        return {"path": path, "name": path.split("/")[-1]}

    def _combined_docs(self, instance, file_field_name, json_field_name):
        docs = list(getattr(instance, json_field_name) or [])
        legacy = self._legacy_doc(instance, file_field_name)
        if legacy and not any(doc.get("path") == legacy["path"] for doc in docs):
            docs.insert(0, legacy)
        return docs

    def _save_files(self, instance, files, folder):
        docs = []
        for file in files:
            path = default_storage.save(f"kits/acoes/{instance.pk}/{folder}/{file.name}", file)
            docs.append({"path": path, "name": file.name})
        return docs

    def _sync_file_group(self, instance, *, file_field_name, json_field_name, keep_paths_key, files_key, sync_flag_key, folder, validated_data):
        keep_paths = validated_data.pop(keep_paths_key, None)
        files = validated_data.pop(files_key, [])

        current_docs = self._combined_docs(instance, file_field_name, json_field_name)
        if keep_paths is None:
            if self.initial_data.get(sync_flag_key):
                keep_paths = []
            else:
                keep_paths = [doc.get("path") for doc in current_docs]

        retained_docs = []
        for doc in current_docs:
            path = doc.get("path")
            if path in keep_paths:
                retained_docs.append(doc)
                continue

            legacy_field = getattr(instance, file_field_name)
            if legacy_field and getattr(legacy_field, "name", "") == path:
                legacy_field.delete(save=False)
                setattr(instance, file_field_name, "")
            elif default_storage.exists(path):
                default_storage.delete(path)

        retained_json_docs = []
        legacy_path = getattr(getattr(instance, file_field_name), "name", "") if getattr(instance, file_field_name) else ""
        for doc in retained_docs:
            if doc.get("path") != legacy_path:
                retained_json_docs.append(doc)

        retained_json_docs.extend(self._save_files(instance, files, folder))
        setattr(instance, json_field_name, retained_json_docs)

    def create(self, validated_data):
        historico_emprestimo_files = validated_data.pop("historico_emprestimo_files", [])
        historico_credito_files = validated_data.pop("historico_credito_files", [])
        extrato_bancario_files = validated_data.pop("extrato_bancario_files", [])
        validated_data.pop("historico_emprestimo_keep_paths", None)
        validated_data.pop("historico_credito_keep_paths", None)
        validated_data.pop("extrato_bancario_keep_paths", None)

        instance = super().create(validated_data)
        if historico_emprestimo_files:
            instance.historico_emprestimo_arquivos = self._save_files(instance, historico_emprestimo_files, "historico_emprestimo")
        if historico_credito_files:
            instance.historico_credito_arquivos = self._save_files(instance, historico_credito_files, "historico_credito")
        if extrato_bancario_files:
            instance.extrato_bancario_arquivos = self._save_files(instance, extrato_bancario_files, "extrato_bancario")
        if historico_emprestimo_files or historico_credito_files or extrato_bancario_files:
            instance.save(update_fields=[
                "historico_emprestimo_arquivos",
                "historico_credito_arquivos",
                "extrato_bancario_arquivos",
            ])
        return instance

    def update(self, instance, validated_data):
        self._sync_file_group(
            instance,
            file_field_name="historico_emprestimo",
            json_field_name="historico_emprestimo_arquivos",
            keep_paths_key="historico_emprestimo_keep_paths",
            files_key="historico_emprestimo_files",
            sync_flag_key="historico_emprestimo_sync",
            folder="historico_emprestimo",
            validated_data=validated_data,
        )
        self._sync_file_group(
            instance,
            file_field_name="historico_credito",
            json_field_name="historico_credito_arquivos",
            keep_paths_key="historico_credito_keep_paths",
            files_key="historico_credito_files",
            sync_flag_key="historico_credito_sync",
            folder="historico_credito",
            validated_data=validated_data,
        )
        self._sync_file_group(
            instance,
            file_field_name="extrato_bancario",
            json_field_name="extrato_bancario_arquivos",
            keep_paths_key="extrato_bancario_keep_paths",
            files_key="extrato_bancario_files",
            sync_flag_key="extrato_bancario_sync",
            folder="extrato_bancario",
            validated_data=validated_data,
        )
        return super().update(instance, validated_data)

    class Meta:
        model = AcaoKit
        fields = [
            "id",
            "kit",
            "tipo_acao",
            "nome_banco",
            "banco_outro",
            "numero_contrato",
            "tarifa_questionada",
            "tarifa_questionada_outro",
            "tipo_seguro",
            "tipo_contribuicao",
            "associacao",
            "historico_emprestimo",
            "historico_credito",
            "extrato_bancario",
            "historico_emprestimo_arquivos",
            "historico_credito_arquivos",
            "extrato_bancario_arquivos",
            "historico_emprestimo_files",
            "historico_credito_files",
            "extrato_bancario_files",
            "historico_emprestimo_keep_paths",
            "historico_credito_keep_paths",
            "extrato_bancario_keep_paths",
        ]
        read_only_fields = ["id", "historico_emprestimo", "historico_credito", "extrato_bancario"]
        extra_kwargs = {
            "kit": {"required": False},
        }


class DocumentoKitSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentoKit
        fields = [
            "id",
            "kit",
            "tipo",
            "arquivo",
            "gerado_em",
        ]
        read_only_fields = ["id", "gerado_em"]


class KitListSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source="cliente.nome_completo", read_only=True)
    cliente_cpf = serializers.CharField(source="cliente.cpf", read_only=True)
    criado_por_nome = serializers.CharField(source="criado_por.username", read_only=True)
    total_acoes = serializers.IntegerField(source="acoes.count", read_only=True)

    class Meta:
        model = Kit
        fields = [
            "id",
            "tipo",
            "cliente",
            "cliente_nome",
            "cliente_cpf",
            "criado_por",
            "criado_por_nome",
            "status",
            "total_acoes",
            "criado_em",
            "atualizado_em",
        ]


class KitDetailSerializer(serializers.ModelSerializer):
    cliente_detail = ClienteSerializer(source="cliente", read_only=True)
    acoes = AcaoKitSerializer(many=True, read_only=True)
    documentos = DocumentoKitSerializer(many=True, read_only=True)
    criado_por_nome = serializers.CharField(source="criado_por.username", read_only=True)

    class Meta:
        model = Kit
        fields = [
            "id",
            "tipo",
            "cliente",
            "cliente_detail",
            "criado_por",
            "criado_por_nome",
            "status",
            "acoes",
            "documentos",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_por", "criado_em", "atualizado_em"]


class KitCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Kit
        fields = [
            "id",
            "tipo",
            "cliente",
            "status",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "status", "criado_em", "atualizado_em"]


class BancoKitSerializer(serializers.ModelSerializer):
    class Meta:
        model = BancoKit
        fields = ["id", "nome", "ativo", "ordem"]
        read_only_fields = ["id"]


class TarifaKitSerializer(serializers.ModelSerializer):
    class Meta:
        model = TarifaKit
        fields = ["id", "nome", "ativo", "ordem"]
        read_only_fields = ["id"]


class AssociacaoKitSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssociacaoKit
        fields = ["id", "nome", "abreviacao", "ativo", "ordem"]
        read_only_fields = ["id"]


def _user_nome(user):
    if not user:
        return None
    return getattr(user, "nome_completo", None) or getattr(user, "username", None)


class ClausulaPorcentagemPadraoSerializer(serializers.ModelSerializer):
    atualizado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = ClausulaPorcentagemPadrao
        fields = ["texto", "atualizado_em", "atualizado_por_nome"]
        read_only_fields = ["atualizado_em", "atualizado_por_nome"]

    def get_atualizado_por_nome(self, obj):
        return _user_nome(obj.atualizado_por)


_TIPOS_ACAO_VALIDOS = {v for v, _ in AcaoKit.TIPO_ACAO_CHOICES}


class ClausulaPorcentagemUFSerializer(serializers.ModelSerializer):
    atualizado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = ClausulaPorcentagemUF
        fields = ["id", "uf", "tipo_acao", "texto", "atualizado_em", "atualizado_por_nome"]
        read_only_fields = ["id", "atualizado_em", "atualizado_por_nome"]

    def get_atualizado_por_nome(self, obj):
        return _user_nome(obj.atualizado_por)

    def validate_uf(self, value):
        value = (value or "").strip().upper()
        validate_uf(value)
        return value

    def validate_tipo_acao(self, value):
        value = (value or "").strip()
        if value and value not in _TIPOS_ACAO_VALIDOS:
            raise serializers.ValidationError("Tipo de ação inválido.")
        return value

    def validate_texto(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Informe o texto da cláusula.")
        return value

    def validate(self, attrs):
        # Verifica unicidade (uf, tipo_acao) considerando registros existentes.
        uf = attrs.get("uf") or (self.instance.uf if self.instance else "")
        tipo = attrs.get("tipo_acao", self.instance.tipo_acao if self.instance else "")
        if uf:
            qs = ClausulaPorcentagemUF.objects.filter(uf=uf, tipo_acao=tipo)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                rotulo = "Genérica" if not tipo else tipo
                raise serializers.ValidationError(
                    f"Já existe uma cláusula para {uf} ({rotulo})."
                )
        return attrs

from rest_framework import serializers

from .models import Capacidade, Permissao


class CapacidadeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Capacidade
        fields = ["id", "codigo", "recurso", "acao", "descricao", "categoria"]
        read_only_fields = fields


class PermissaoLeveSerializer(serializers.ModelSerializer):
    """Versão enxuta para embutir em outros serializers (ex.: User.permissao)."""
    class Meta:
        model = Permissao
        fields = ["id", "nome", "descricao"]
        read_only_fields = fields


class PermissaoSerializer(serializers.ModelSerializer):
    capacidades = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Capacidade.objects.all(), required=False
    )
    capacidades_detalhe = CapacidadeSerializer(
        source="capacidades", many=True, read_only=True
    )
    usuarios_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Permissao
        fields = [
            "id", "nome", "descricao",
            "capacidades", "capacidades_detalhe",
            "usuarios_count",
            "criado_em", "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em", "usuarios_count"]

    def create(self, validated_data):
        request = self.context.get("request")
        capacidades = validated_data.pop("capacidades", [])
        permissao = Permissao.objects.create(
            criado_por=getattr(request, "user", None) if request else None,
            **validated_data,
        )
        if capacidades:
            permissao.capacidades.set(capacidades)
        return permissao

    def update(self, instance, validated_data):
        capacidades = validated_data.pop("capacidades", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if capacidades is not None:
            instance.capacidades.set(capacidades)
        return instance

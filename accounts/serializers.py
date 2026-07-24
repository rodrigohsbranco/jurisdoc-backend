from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from permissoes.models import Permissao
from permissoes.serializers import PermissaoLeveSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    # senha nunca sai na resposta; opcional no update, obrigatória no create
    password = serializers.CharField(write_only=True, required=False, min_length=6)

    # permissao: aceita ID na escrita; expande objeto na leitura via permissao_detalhe
    permissao = serializers.PrimaryKeyRelatedField(
        queryset=Permissao.objects.all(),
        allow_null=True,
        required=False,
    )
    permissao_detalhe = PermissaoLeveSerializer(source="permissao", read_only=True)

    # lista flat de códigos de capacidade do usuário (via permissao)
    capacidades = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username",
            "first_name", "last_name",  # legados (mantidos pra compat)
            "nome_completo", "email", "telefone", "endereco", "avatar",
            "is_admin", "is_active",
            "permissao", "permissao_detalhe", "capacidades",
            "password",
        ]
        read_only_fields = ["id", "permissao_detalhe", "capacidades"]

    def get_capacidades(self, obj) -> list[str]:
        codigos = set()
        if obj.permissao_id:
            codigos |= set(obj.permissao.capacidades.values_list("codigo", flat=True))
        # capacidades concedidas diretamente ao usuário (fora do perfil)
        codigos |= set(obj.capacidades_diretas.values_list("codigo", flat=True))
        return sorted(codigos)

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        is_admin = bool(validated_data.pop("is_admin", False))  # default seguro

        if not password:
            raise serializers.ValidationError(
                {"password": "Obrigatório ao criar usuário."}
            )

        user = User(**validated_data)
        user.is_admin = is_admin
        user.is_staff = is_admin  # staff para acessar /admin se for admin
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        request = self.context.get("request")
        new_password = validated_data.pop("password", None)
        new_is_admin = validated_data.pop("is_admin", None)

        # atualiza campos "normais" (inclui permissao por FK)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # proteção: não permitir que o próprio usuário remova seu admin
        if (
            new_is_admin is not None
            and request
            and request.user.pk == instance.pk
            and not new_is_admin
        ):
            raise serializers.ValidationError(
                {"is_admin": "Você não pode remover seu próprio acesso de administrador."}
            )

        if new_is_admin is not None:
            instance.is_admin = bool(new_is_admin)
            instance.is_staff = bool(new_is_admin)

        if new_password:
            instance.set_password(new_password)

        instance.save()
        return instance


class TokenObtainPairWithUserSerializer(TokenObtainPairSerializer):
    """
    Serializer customizado que retorna {accessToken, refreshToken, user}
    em vez do padrão {access, refresh, user}.
    """
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # claims leves (opcional)
        token["username"] = user.username
        token["is_admin"] = getattr(user, "is_admin", False)
        return token

    def validate(self, attrs):
        try:
            data = super().validate(attrs)
        except AuthenticationFailed:
            # O SimpleJWT usa a mesma mensagem genérica em inglês ("No active
            # account found...") para senha errada, usuário inexistente E conta
            # inativa. Aqui traduzimos e distinguimos conta inativa de
            # credenciais inválidas, sem vazar se o usuário existe (só damos a
            # dica de "inativa" quando a conta realmente existe e está inativa).
            username = attrs.get(self.username_field, "")
            user = User.objects.filter(username__iexact=username).first()
            if user is not None and not user.is_active:
                raise AuthenticationFailed(
                    "Sua conta está inativa. Contate o administrador.",
                    "inactive_account",
                )
            raise AuthenticationFailed(
                "Usuário ou senha inválidos.",
                "invalid_credentials",
            )
        return {
            "accessToken": data["access"],
            "refreshToken": data["refresh"],
            "user": UserSerializer(self.user).data,
        }


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)

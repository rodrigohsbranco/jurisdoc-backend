from django.contrib.auth import get_user_model
from django.utils import timezone
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
            "acesso_app", "acesso_app_liberado_em",
            "permissao", "permissao_detalhe", "capacidades",
            "password",
        ]
        read_only_fields = [
            "id", "permissao_detalhe", "capacidades", "acesso_app_liberado_em",
        ]

    def get_capacidades(self, obj) -> list[str]:
        codigos = set()
        if obj.permissao_id:
            codigos |= set(obj.permissao.capacidades.values_list("codigo", flat=True))
        # capacidades concedidas diretamente ao usuário (fora do perfil)
        codigos |= set(obj.capacidades_diretas.values_list("codigo", flat=True))
        return sorted(codigos)

    def _quem_solicitou(self):
        request = self.context.get("request")
        usuario = getattr(request, "user", None)
        return usuario if getattr(usuario, "pk", None) else None

    def validate(self, attrs):
        """Acesso ao app é privilégio de administrador — nunca liberar sem isso.

        Só barra quando a requisição está LIGANDO o marcador para alguém que não
        será admin. Quando o marcador não vem na requisição, `update` cuida de
        revogá-lo caso o usuário perca o admin.
        """
        if attrs.get("acesso_app"):
            is_admin = attrs.get(
                "is_admin", getattr(self.instance, "is_admin", False)
            )
            if not is_admin:
                raise serializers.ValidationError(
                    {"acesso_app": "Só usuários administradores podem ter acesso ao app FlowALR."}
                )
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        is_admin = bool(validated_data.pop("is_admin", False))  # default seguro
        acesso_app = bool(validated_data.pop("acesso_app", False))

        if not password:
            raise serializers.ValidationError(
                {"password": "Obrigatório ao criar usuário."}
            )

        user = User(**validated_data)
        user.is_admin = is_admin
        user.is_staff = is_admin  # staff para acessar /admin se for admin
        user.acesso_app = acesso_app
        if acesso_app:
            user.acesso_app_liberado_em = timezone.now()
            user.acesso_app_liberado_por = self._quem_solicitou()
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        request = self.context.get("request")
        new_password = validated_data.pop("password", None)
        new_is_admin = validated_data.pop("is_admin", None)
        novo_acesso_app = validated_data.pop("acesso_app", None)

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

        # Acesso ao app: audita quem liberou e quando; revoga junto com o admin
        if novo_acesso_app is not None:
            novo_acesso_app = bool(novo_acesso_app)
            if novo_acesso_app and not instance.acesso_app:
                instance.acesso_app_liberado_em = timezone.now()
                instance.acesso_app_liberado_por = self._quem_solicitou()
            elif not novo_acesso_app:
                instance.acesso_app_liberado_em = None
                instance.acesso_app_liberado_por = None
            instance.acesso_app = novo_acesso_app

        if instance.acesso_app and not instance.is_admin:
            # Perdeu o admin (nesta ou em outra requisição): o acesso ao app cai junto
            instance.acesso_app = False
            instance.acesso_app_liberado_em = None
            instance.acesso_app_liberado_por = None

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

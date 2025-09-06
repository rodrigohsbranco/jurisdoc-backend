from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    # senha nunca sai na resposta; opcional no update, obrigatória no create
    password = serializers.CharField(write_only=True, required=False, min_length=6)

    class Meta:
        model = User
        fields = [
            "id", "username", "first_name", "last_name", "email",
            "is_admin", "is_active", "password",
        ]
        read_only_fields = ["id"]

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

        # atualiza campos “normais”
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
    Opcional: use este serializer no login para retornar {access, refresh, user}.
    Lembre de apontar a rota de login para uma view que use este serializer.
    """
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # claims leves (opcional)
        token["username"] = user.username
        token["is_admin"] = getattr(user, "is_admin", False)
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)

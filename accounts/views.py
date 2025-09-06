# Views de usuário podem ser adicionadas aqui (perfil, troca de senha, etc.)
from rest_framework.views import APIView
from rest_framework import viewsets, filters, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .serializers import UserSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import TokenObtainPairWithUserSerializer
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from .models import User
from .serializers import UserSerializer
from .permissions import IsAdmin

class MeView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        return Response(UserSerializer(request.user).data)

class LoginView(TokenObtainPairView):
    serializer_class = TokenObtainPairWithUserSerializer

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .serializers import ChangePasswordSerializer
        ser = ChangePasswordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        user = request.user
        if not user.check_password(ser.validated_data["old_password"]):
            return Response({"detail": "Senha atual incorreta."}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(ser.validated_data["new_password"])
        user.save()
        return Response({"detail": "Senha alterada com sucesso."})

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("username")
    serializer_class = UserSerializer
    permission_classes = [IsAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["username", "email", "first_name", "last_name"]
    ordering_fields = ["username", "date_joined", "is_admin", "is_active"]

    def perform_destroy(self, instance):
        if self.request.user.pk == instance.pk:
            raise ValidationError({"detail": "Você não pode excluir a si mesmo."})
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"], url_path="set-password")
    def set_password(self, request, pk=None):
        user = self.get_object()
        new_password = (request.data or {}).get("new_password", "")
        if len(new_password) < 6:
            return Response({"new_password": "Mínimo de 6 caracteres."},
                            status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save()
        return Response({"detail": "Senha alterada com sucesso."})

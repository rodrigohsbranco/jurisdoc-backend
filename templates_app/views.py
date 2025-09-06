from rest_framework import viewsets, permissions
from .models import Template
from .serializers import TemplateSerializer

class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and getattr(request.user, "is_admin", False))

class TemplateViewSet(viewsets.ModelViewSet):
    queryset = Template.objects.all().order_by("name")
    serializer_class = TemplateSerializer
    permission_classes = [IsAdmin]

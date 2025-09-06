from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.http import Http404
from django.core.files.base import ContentFile
from docxtpl import DocxTemplate
from io import BytesIO
import uuid

from templates_app.models import Template
from .models import Petition
from .serializers import GenerateSerializer

class GeneratePetition(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = GenerateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        tpl = Template.objects.filter(id=s.validated_data["template_id"], active=True).first()
        if not tpl:
            raise Http404("Template não encontrado")

        context = s.validated_data["data"]
        doc = DocxTemplate(tpl.file.path)
        doc.render(context)

        buf = BytesIO()
        doc.save(buf); buf.seek(0)
        name = f"peticao_{uuid.uuid4().hex}.docx"

        pet = Petition.objects.create(template=tpl, context=context, user=request.user)
        pet.output.save(name, ContentFile(buf.read()))
        return Response({"id": pet.id, "file_url": pet.output.url})

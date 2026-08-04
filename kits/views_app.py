from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from accounts.service_auth import IsServiceAdmin, ServiceClientAuthentication
from .models import AcaoKit, Kit, resolver_clausula_porcentagem
from .serializers_app import (
    AcaoKitAppSerializer,
    KitAppCreateSerializer,
    KitAppDetailSerializer,
    KitAppListSerializer,
)
from .services_documentos import KIT_TEMPLATE_DEFS, TIPOS_COM_CONTRATO, slug_nome_cliente


TRANSICOES_VALIDAS = {
    "rascunho": ["acoes", "finalizado"],
    "acoes": ["finalizado"],
    "finalizado": ["assinado"],
    "assinado": [],
}

_APP_SYSTEM_USERNAME = "app_flowalr"


def _auto_snapshot_previdenciario(kit) -> None:
    """Salva o snapshot de advogados fixos do kit previdenciário.

    Chamado na criação do kit e antes de gerar os documentos, garantindo que
    mudanças no campo fixo_previdenciario reflitam sem precisar recriar o kit.
    """
    from .services_advogados import ids_fixos_previdenciario, montar_snapshot
    ids = ids_fixos_previdenciario()
    if not ids:
        return
    uf = (getattr(kit.cliente, "uf", "") or "").upper()
    snapshot, _ = montar_snapshot(ids, uf)
    kit.advogados_snapshot = snapshot
    kit.save(update_fields=["advogados_snapshot"])


def _get_app_user():
    User = get_user_model()
    try:
        return User.objects.get(username=_APP_SYSTEM_USERNAME)
    except User.DoesNotExist:
        raise ValidationError(
            {"detail": f"Usuário de sistema '{_APP_SYSTEM_USERNAME}' não encontrado. Crie-o no JurisDoc antes de usar a API de kits pelo app."}
        )


class KitAppViewSet(viewsets.ModelViewSet):
    authentication_classes = [ServiceClientAuthentication]
    permission_classes = [IsServiceAdmin]
    pagination_class = None
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["tipo", "status", "cliente", "origem", "app_criado_por_nome"]
    search_fields = ["cliente__nome_completo", "cliente__cpf", "app_criado_por_nome"]
    ordering_fields = ["criado_em", "atualizado_em", "status"]
    ordering = ["-criado_em"]

    def get_queryset(self):
        return (
            Kit.objects
            .select_related("cliente", "criado_por")
            .prefetch_related("acoes", "documentos")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return KitAppListSerializer
        if self.action == "create":
            return KitAppCreateSerializer
        return KitAppDetailSerializer

    def perform_create(self, serializer):
        app_user = _get_app_user()
        kit = serializer.save(criado_por=app_user, origem="app")
        if kit.tipo == "previdenciario":
            _auto_snapshot_previdenciario(kit)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status != "rascunho":
            return Response(
                {"detail": "Só é possível excluir kits em rascunho."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Ações de status ──

    @action(detail=True, methods=["post"])
    def finalizar(self, request, pk=None):
        kit = self.get_object()
        if "finalizado" not in TRANSICOES_VALIDAS.get(kit.status, []):
            return Response(
                {"detail": f"Não é possível finalizar um kit com status '{kit.get_status_display()}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if kit.tipo != "previdenciario" and kit.acoes.count() == 0:
            return Response(
                {"detail": "O kit precisa ter pelo menos uma ação para ser finalizado."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        kit.status = "finalizado"
        kit.save(update_fields=["status", "atualizado_em"])
        return Response(KitAppDetailSerializer(kit, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def assinar(self, request, pk=None):
        kit = self.get_object()
        if kit.status != "finalizado":
            return Response(
                {"detail": "Só é possível assinar um kit finalizado."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        kit.status = "assinado"
        kit.save(update_fields=["status", "atualizado_em"])
        return Response(KitAppDetailSerializer(kit, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="mudar-status")
    def mudar_status(self, request, pk=None):
        kit = self.get_object()
        novo_status = request.data.get("status")
        if not novo_status:
            return Response({"detail": "Informe o novo status."}, status=status.HTTP_400_BAD_REQUEST)

        if kit.status == novo_status:
            return Response(KitAppDetailSerializer(kit, context={"request": request}).data)

        validos = TRANSICOES_VALIDAS.get(kit.status, [])
        if novo_status not in validos:
            return Response(
                {"detail": f"Transição de '{kit.status}' para '{novo_status}' não é permitida."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if novo_status == "finalizado" and kit.tipo != "previdenciario" and kit.acoes.count() == 0:
            return Response(
                {"detail": "O kit precisa ter pelo menos uma ação para ser finalizado."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        kit.status = novo_status
        kit.save(update_fields=["status", "atualizado_em"])
        return Response(KitAppDetailSerializer(kit, context={"request": request}).data)

    # ── Advogados ──

    @action(detail=True, methods=["get"], url_path="advogados/sugeridos")
    def advogados_sugeridos(self, request, pk=None):
        from .services_advogados import sugerir_advogados
        kit = self.get_object()
        uf = (getattr(kit.cliente, "uf", "") or "").upper()
        tipos = set(kit.acoes.values_list("tipo_acao", flat=True))
        ids = sugerir_advogados(uf, tipos, tipo_kit=kit.tipo)
        return Response({"advogados_ids": ids, "uf_cliente": uf})

    @action(detail=True, methods=["get", "post"], url_path="advogados")
    def advogados(self, request, pk=None):
        from .services_advogados import montar_snapshot
        kit = self.get_object()

        if request.method == "GET":
            return Response({"advogados_snapshot": list(kit.advogados_snapshot or [])})

        ids = request.data.get("advogados_ids")
        if ids is None or not isinstance(ids, list):
            return Response(
                {"detail": "Informe 'advogados_ids' como lista de IDs inteiros."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uf = (getattr(kit.cliente, "uf", "") or "").upper()
        snapshot, warnings = montar_snapshot(ids, uf)
        kit.advogados_snapshot = snapshot
        kit.save(update_fields=["advogados_snapshot", "atualizado_em"])
        return Response({"advogados_snapshot": snapshot, "warnings": warnings})

    # ── Cláusula de porcentagem ──

    @action(detail=True, methods=["get", "post"], url_path="clausula-snapshot")
    def clausula_snapshot(self, request, pk=None):
        kit = self.get_object()
        uf = (getattr(kit.cliente, "uf", "") or "").upper()

        if kit.clausula_porcentagem_snapshot:
            return Response({
                "uf": uf,
                "texto": kit.clausula_porcentagem_snapshot,
                "fonte": "snapshot",
                "ja_persistido": True,
            })

        tipos = list(kit.acoes.order_by("id").values_list("tipo_acao", flat=True))
        texto, fonte = resolver_clausula_porcentagem(uf, tipos)

        if request.method == "POST":
            kit.clausula_porcentagem_snapshot = texto
            kit.save(update_fields=["clausula_porcentagem_snapshot", "atualizado_em"])
            return Response({"uf": uf, "texto": texto, "fonte": fonte, "ja_persistido": True})

        return Response({"uf": uf, "texto": texto, "fonte": fonte, "ja_persistido": False})

    # ── Choices / metadados ──

    @action(detail=False, methods=["get"])
    def tipos(self, request):
        """Retorna as opções de tipo de kit."""
        return Response([
            {"value": v, "label": l} for v, l in Kit.TIPO_CHOICES
        ])

    @action(detail=False, methods=["get"], url_path="tipos-acao")
    def tipos_acao(self, request):
        """Retorna as opções de tipo de ação com flag de número de contrato."""
        return Response([
            {
                "value": v,
                "label": l,
                "tem_numero_contrato": v in TIPOS_COM_CONTRATO,
            }
            for v, l in AcaoKit.TIPO_ACAO_CHOICES
        ])

    @action(detail=False, methods=["get"])
    def metadados(self, request):
        """
        Retorna todos os metadados de fluxo necessários para o app construir sua UX.

        Inclui: tipos de kit (com regras de fluxo), tipos de ação, status possíveis
        e transições válidas de status. Chame uma vez na inicialização do app.
        """
        _DOCS_CONDICIONAIS = {
            "domicilio": "comprovante_nome_cliente == 'nao'",
        }
        _TIPO_META = {
            "bancario": {
                "requer_acoes": True,
                "requer_data_nascimento": False,
                "requer_hipossuficiencia": True,
                "requer_selecao_advogados": True,
            },
            "previdenciario": {
                "requer_acoes": False,
                "requer_data_nascimento": True,
                "requer_hipossuficiencia": False,
                "requer_selecao_advogados": False,
            },
            "marketing": {
                "requer_acoes": True,
                "requer_data_nascimento": False,
                "requer_hipossuficiencia": True,
                "requer_selecao_advogados": True,
            },
        }

        tipos_kit = []
        for value, label in Kit.TIPO_CHOICES:
            defs = KIT_TEMPLATE_DEFS.get(value, [])
            meta = _TIPO_META.get(value, {})
            all_doc_keys = [d["key"] for d in defs]
            tipos_kit.append({
                "value": value,
                "label": label,
                **meta,
                "documentos_fixos": [k for k in all_doc_keys if k not in _DOCS_CONDICIONAIS],
                "documentos_condicionais": [
                    {"key": k, "condicao": _DOCS_CONDICIONAIS[k]}
                    for k in all_doc_keys if k in _DOCS_CONDICIONAIS
                ],
            })

        # Campos visíveis/obrigatórios por tipo de ação — espelha exatamente o NovoKitView.vue
        # Chave "por_tipo_kit": sobrescreve as regras base para tipos de kit específicos.
        _CAMPOS_TIPOS_ACAO = {
            # RMC / RCC / Empréstimo não autorizado / Cartão de crédito consignado
            # → banco + numero_contrato + anexos historico_emprestimo / historico_credito
            "cartao_credito_consignado": {
                "nome_banco": {"visivel": True, "obrigatorio": True},
                "banco_outro": {"visivel": True, "obrigatorio": False, "condicao": "nome_banco == 'Outro'"},
                "numero_contrato": {"visivel": True, "obrigatorio": True},
                "tarifa_questionada": {"visivel": False},
                "tarifa_questionada_outro": {"visivel": False},
                "tipo_seguro": {"visivel": False},
                "tipo_contribuicao": {"visivel": False},
                "associacao": {"visivel": False},
                "anexos": ["historico_emprestimo", "historico_credito"],
            },
            "rmc": {
                "nome_banco": {"visivel": True, "obrigatorio": True},
                "banco_outro": {"visivel": True, "obrigatorio": False, "condicao": "nome_banco == 'Outro'"},
                "numero_contrato": {"visivel": True, "obrigatorio": True},
                "tarifa_questionada": {"visivel": False},
                "tarifa_questionada_outro": {"visivel": False},
                "tipo_seguro": {"visivel": False},
                "tipo_contribuicao": {"visivel": False},
                "associacao": {"visivel": False},
                "anexos": ["historico_emprestimo", "historico_credito"],
            },
            "rcc": {
                "nome_banco": {"visivel": True, "obrigatorio": True},
                "banco_outro": {"visivel": True, "obrigatorio": False, "condicao": "nome_banco == 'Outro'"},
                "numero_contrato": {"visivel": True, "obrigatorio": True},
                "tarifa_questionada": {"visivel": False},
                "tarifa_questionada_outro": {"visivel": False},
                "tipo_seguro": {"visivel": False},
                "tipo_contribuicao": {"visivel": False},
                "associacao": {"visivel": False},
                "anexos": ["historico_emprestimo", "historico_credito"],
            },
            "emprestimo_nao_autorizado": {
                "nome_banco": {"visivel": True, "obrigatorio": True},
                "banco_outro": {"visivel": True, "obrigatorio": False, "condicao": "nome_banco == 'Outro'"},
                "numero_contrato": {"visivel": True, "obrigatorio": True},
                "tarifa_questionada": {"visivel": False},
                "tarifa_questionada_outro": {"visivel": False},
                "tipo_seguro": {"visivel": False},
                "tipo_contribuicao": {"visivel": False},
                "associacao": {"visivel": False},
                "anexos": ["historico_emprestimo", "historico_credito"],
            },
            # Tarifa Bancária → banco + tarifa_questionada (dropdown) + extrato_bancario
            "tarifa_bancaria": {
                "nome_banco": {"visivel": True, "obrigatorio": True},
                "banco_outro": {"visivel": True, "obrigatorio": False, "condicao": "nome_banco == 'Outro'"},
                "numero_contrato": {"visivel": False},
                "tarifa_questionada": {"visivel": True, "obrigatorio": True},
                "tarifa_questionada_outro": {
                    "visivel": True,
                    "obrigatorio": True,
                    "condicao": "tarifa_questionada == 'OUTROS'",
                },
                "tipo_seguro": {"visivel": False},
                "tipo_contribuicao": {"visivel": False},
                "associacao": {"visivel": False},
                "anexos": ["extrato_bancario"],
            },
            # Seguro Não Autorizado → banco + tipo_seguro (texto livre obrigatório)
            "seguro_nao_autorizado": {
                "nome_banco": {"visivel": True, "obrigatorio": True},
                "banco_outro": {"visivel": True, "obrigatorio": False, "condicao": "nome_banco == 'Outro'"},
                "numero_contrato": {"visivel": False},
                "tarifa_questionada": {"visivel": False},
                "tarifa_questionada_outro": {"visivel": False},
                "tipo_seguro": {"visivel": True, "obrigatorio": True},
                "tipo_contribuicao": {"visivel": False},
                "associacao": {"visivel": False},
                "anexos": [],
            },
            # Contribuição Sindical → difere por tipo de kit (ver por_tipo_kit)
            "contribuicao_sindical_nao_autorizada": {
                "nome_banco": {"visivel": False},
                "banco_outro": {"visivel": False},
                "numero_contrato": {"visivel": False},
                "tarifa_questionada": {"visivel": False},
                "tarifa_questionada_outro": {"visivel": False},
                "tipo_seguro": {"visivel": False},
                "tipo_contribuicao": {"visivel": False},
                "associacao": {"visivel": False},
                "anexos": [],
                # Sobrescritas por tipo de kit:
                "por_tipo_kit": {
                    "bancario": {
                        "associacao": {"visivel": True, "obrigatorio": False},
                    },
                    "marketing": {
                        "tipo_contribuicao": {"visivel": True, "obrigatorio": True},
                    },
                },
            },
        }

        return Response({
            "tipos_kit": tipos_kit,
            "tipos_acao": [
                {
                    "value": v,
                    "label": l,
                    "tem_numero_contrato": v in TIPOS_COM_CONTRATO,
                }
                for v, l in AcaoKit.TIPO_ACAO_CHOICES
            ],
            "campos_por_tipo_acao": _CAMPOS_TIPOS_ACAO,
            "status_choices": [
                {"value": v, "label": l} for v, l in Kit.STATUS_CHOICES
            ],
            "transicoes_validas": TRANSICOES_VALIDAS,
        })

    # ── Documentos do kit (PDF) ──

    @action(detail=True, methods=["get"])
    def documentos(self, request, pk=None):
        """Retorna os documentos gerados do kit com URL absoluta."""
        from .serializers_app import AppDocumentoKitSerializer
        kit = self.get_object()
        docs = kit.documentos.all()
        serializer = AppDocumentoKitSerializer(docs, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="documentos/unificado")
    def documentos_unificado(self, request, pk=None):
        """
        Mescla todos os PDFs do kit em um único arquivo e retorna para download.

        GET /api/app/kits/{id}/documentos/unificado/
        Response: application/pdf — Content-Disposition: attachment; filename="kit_completo_NOME_CLIENTE.pdf"
        """
        from io import BytesIO
        from django.http import HttpResponse
        from pypdf import PdfWriter

        kit = self.get_object()
        docs = list(kit.documentos.all())

        if not docs:
            return Response(
                {"detail": "Nenhum documento gerado para este kit."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        writer = PdfWriter()
        try:
            for doc in docs:
                if not doc.arquivo or not doc.arquivo.name:
                    continue
                with doc.arquivo.open("rb") as f:
                    writer.append(f)
        except FileNotFoundError as e:
            return Response(
                {"detail": f"Arquivo não encontrado no servidor: {e}. Gere os documentos novamente via gerar-documentos/."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as e:
            return Response(
                {"detail": f"Falha ao mesclar os documentos: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        buf = BytesIO()
        writer.write(buf)
        buf.seek(0)

        cliente_slug = slug_nome_cliente(kit.cliente.nome_completo or "")
        pdf_response = HttpResponse(buf.read(), content_type="application/pdf")
        pdf_response["Content-Disposition"] = f'attachment; filename="kit_completo_{cliente_slug}.pdf"'
        return pdf_response

    @action(detail=True, methods=["post"], url_path="gerar-documentos")
    def gerar_documentos(self, request, pk=None):
        """Gera os PDFs do kit server-side (docxtpl + LibreOffice) e armazena como DocumentoKit."""
        from .services_documentos import gerar_documentos_kit
        from .serializers_app import AppDocumentoKitSerializer
        kit = self.get_object()
        # Para previdenciário sempre refresha o snapshot com os advogados fixos atuais,
        # garantindo que mudanças no cadastro reflitam nos documentos sem re-criar o kit.
        if kit.tipo == "previdenciario":
            _auto_snapshot_previdenciario(kit)
        try:
            docs, warnings = gerar_documentos_kit(kit)
        except RuntimeError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except FileNotFoundError:
            return Response(
                {"detail": "LibreOffice não encontrado no servidor."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        serializer = AppDocumentoKitSerializer(docs, many=True, context={"request": request})
        return Response({
            "documentos": serializer.data,
            "warnings": warnings,
            "total": len(docs),
        })

    # ── Assinatura ZapSign ──

    @action(detail=True, methods=["post"], url_path="enviar-para-assinatura")
    def enviar_para_assinatura(self, request, pk=None):
        """Envia cada documento do kit ao ZapSign como documento separado.

        Cada documento é assinado individualmente pelo cliente; `sign_url` é o
        link único do portal do JurisDoc, que conduz de um documento ao próximo.

        Body (opcional):
          nivel: "basico" | "medio" | "avancado"  (padrão: "basico")
          medio_tipo: "email" | "sms"              (padrão: "email", usado quando nivel=="medio")
          assinatura_paginas: bool                 (padrão: false)

        Retorna:
          {
            "status": str,
            "sign_url": str,
            "documentos": [{"tipo": str, "tipo_display": str}],
            "reutilizado": bool
          }
        """
        from .services_zapsign import base_url_from_request as _base_url
        from .services_zapsign import enviar_para_assinatura as _enviar

        kit = self.get_object()
        config = {
            "nivel": request.data.get("nivel", "basico"),
            "medio_tipo": request.data.get("medio_tipo", "email"),
            "assinatura_paginas": bool(request.data.get("assinatura_paginas", False)),
        }

        if kit.status == "assinado":
            return Response(
                {"detail": "Este kit já foi assinado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Auto-finaliza se necessário
        if kit.status not in ("finalizado", "assinado"):
            if kit.tipo != "previdenciario" and kit.acoes.count() == 0:
                return Response(
                    {"detail": "O kit precisa ter pelo menos uma ação antes de ser enviado para assinatura."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            kit.status = "finalizado"
            kit.save(update_fields=["status", "atualizado_em"])

        # Reutiliza link existente se já enviado e ainda pendente
        if kit.zapsign_status == "pending" and kit.zapsign_sign_url:
            docs_info = [
                {"tipo": d.tipo, "tipo_display": d.get_tipo_display()}
                for d in kit.documentos.exclude(tipo="assinado_zapsign").order_by("tipo")
            ]
            return Response({
                "status": kit.status,
                "sign_url": kit.zapsign_sign_url,
                "documentos": docs_info,
                "reutilizado": True,
            })

        # Gera documentos server-side se ainda não existirem
        if not kit.documentos.exclude(tipo="assinado_zapsign").exists():
            from .services_documentos import gerar_documentos_kit
            if kit.tipo == "previdenciario":
                _auto_snapshot_previdenciario(kit)
            try:
                documentos_gerados, _ = gerar_documentos_kit(kit)
                if not documentos_gerados:
                    return Response(
                        {"detail": "Não foi possível gerar os documentos. Verifique se os templates estão cadastrados."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            except Exception as exc:
                return Response(
                    {"detail": f"Erro ao gerar documentos para assinatura: {exc}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            result = _enviar(kit, config, base_url=_base_url(request))
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "status": kit.status,
            "sign_url": result["sign_url"],
            "documentos": result["documentos"],
            "reutilizado": False,
        })

    # ── Stats ──

    @action(detail=False, methods=["get"])
    def stats(self, request):
        qs = self.get_queryset().filter(origem="app")
        counts = qs.aggregate(
            total=Count("id"),
            rascunho=Count("id", filter=Q(status="rascunho")),
            em_andamento=Count("id", filter=Q(status="acoes")),
            pendentes=Count("id", filter=Q(status="finalizado")),
            assinados=Count("id", filter=Q(status="assinado")),
        )
        return Response(counts)


class AcaoKitAppViewSet(viewsets.ModelViewSet):
    authentication_classes = [ServiceClientAuthentication]
    permission_classes = [IsServiceAdmin]
    serializer_class = AcaoKitAppSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    DOCS_FIELD_MAP = {
        "historico_emprestimo": "historico_emprestimo_arquivos",
        "historico_credito": "historico_credito_arquivos",
        "extrato_bancario": "extrato_bancario_arquivos",
    }

    def _get_kit(self):
        return get_object_or_404(Kit, pk=self.kwargs["kit_pk"])

    def get_queryset(self):
        return AcaoKit.objects.filter(kit_id=self.kwargs["kit_pk"])

    def get_serializer(self, *args, **kwargs):
        data = kwargs.get("data")
        request = getattr(self, "request", None)
        if data is not None and request is not None and hasattr(data, "setlist"):
            mutable = data.copy()
            for key in [
                "historico_emprestimo_keep_paths",
                "historico_credito_keep_paths",
                "extrato_bancario_keep_paths",
            ]:
                values = request.data.getlist(key)
                if values:
                    mutable.setlist(key, values)
            for key in [
                "historico_emprestimo_files",
                "historico_credito_files",
                "extrato_bancario_files",
            ]:
                files = request.FILES.getlist(key)
                if files:
                    mutable.setlist(key, files)
            kwargs["data"] = mutable
        return super().get_serializer(*args, **kwargs)

    def perform_create(self, serializer):
        kit = self._get_kit()
        serializer.save(kit=kit)

    @action(detail=True, methods=["post"], url_path="anexos/upload")
    def upload_attachments(self, request, kit_pk=None, pk=None):
        instance = self.get_object()
        owner = request.data.get("owner")
        field_name = self.DOCS_FIELD_MAP.get(owner)
        if not field_name:
            return Response(
                {"detail": "Owner inválido. Use: historico_emprestimo, historico_credito ou extrato_bancario."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        files = request.FILES.getlist("files")
        if not files:
            return Response({"detail": "Nenhum arquivo enviado."}, status=status.HTTP_400_BAD_REQUEST)

        docs = list(getattr(instance, field_name) or [])
        for file in files:
            path = default_storage.save(f"kits/acoes/{instance.pk}/{owner}/{file.name}", file)
            docs.append({"path": path, "name": file.name})

        setattr(instance, field_name, docs)
        instance.save(update_fields=[field_name])
        serializer = self.get_serializer(instance)
        return Response({"documentos": serializer.data[field_name]}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="anexos/remove")
    def remove_attachment(self, request, kit_pk=None, pk=None):
        instance = self.get_object()
        owner = request.data.get("owner")
        field_name = self.DOCS_FIELD_MAP.get(owner)
        if not field_name:
            return Response({"detail": "Owner inválido."}, status=status.HTTP_400_BAD_REQUEST)

        path_to_remove = request.data.get("path")
        if not path_to_remove:
            return Response({"detail": "Informe o campo 'path'."}, status=status.HTTP_400_BAD_REQUEST)

        docs = list(getattr(instance, field_name) or [])
        new_docs = [doc for doc in docs if doc.get("path") != path_to_remove]
        if len(new_docs) == len(docs):
            return Response({"detail": "Documento não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if default_storage.exists(path_to_remove):
            default_storage.delete(path_to_remove)

        setattr(instance, field_name, new_docs)
        instance.save(update_fields=[field_name])
        serializer = self.get_serializer(instance)
        return Response({"documentos": serializer.data[field_name]}, status=status.HTTP_200_OK)

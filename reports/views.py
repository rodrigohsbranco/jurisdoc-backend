from __future__ import annotations
from datetime import datetime, time, timedelta
from typing import List

from django.db.models import Count, Q
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth
from django.http import HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    TimeSeriesQuerySerializer,
    TemplatesUsageQuerySerializer,
    ExportPetitionsQuerySerializer,
)

# ---- Ajuste os imports conforme seus apps ----
from cadastro.models import Cliente, ContaBancaria
from petitions.models import Petition


# -------- helpers --------
def to_window(d_from, d_to):
    """
    Converte Date -> DateTime (início/fim do dia), com timezone-aware
    usando zoneinfo (Django timezone).
    """
    start_naive = datetime.combine(d_from, time.min)
    end_naive = datetime.combine(d_to, time.max)

    if timezone.is_naive(start_naive):
        start = timezone.make_aware(start_naive, timezone.get_current_timezone())
    else:
        start = start_naive
    if timezone.is_naive(end_naive):
        end = timezone.make_aware(end_naive, timezone.get_current_timezone())
    else:
        end = end_naive

    return start, end


def trunc_for(bucket: str):
    if bucket == "day":
        return TruncDay
    if bucket == "week":
        return TruncWeek
    return TruncMonth


def norm_key(bucket: str, dt: datetime) -> str:
    """Transforma um datetime em chave 'normalizada' por bucket."""
    if bucket == "month":
        return f"{dt.year:04d}-{dt.month:02d}"
    return dt.date().isoformat()


def month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_month(dt: datetime) -> datetime:
    y, m = dt.year, dt.month
    if m == 12:
        return dt.replace(year=y + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return dt.replace(month=m + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


def periods_range(start: datetime, end: datetime, bucket: str) -> List[datetime]:
    """Gera a lista de bordas de período entre [start, end] incluídas."""
    items: List[datetime] = []
    cur = start

    if bucket == "day":
        while cur <= end:
            items.append(cur.replace(hour=0, minute=0, second=0, microsecond=0))
            cur = cur + timedelta(days=1)
        return items

    if bucket == "week":
        # alinhar para segunda-feira da semana do start
        cur = (cur - timedelta(days=cur.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        while cur <= end:
            items.append(cur)
            cur = cur + timedelta(weeks=1)
        return items

    # month
    cur = month_start(cur)
    while cur <= end:
        items.append(cur)
        cur = add_month(cur)
    return items


# -------- Views --------

@method_decorator(cache_page(300), name="dispatch")  # 5 min de cache
class TimeSeriesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = TimeSeriesQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        bucket = q.validated_data["bucket"]
        d_from = q.validated_data["date_from"]
        d_to = q.validated_data["date_to"]
        start, end = to_window(d_from, d_to)

        Trunc = trunc_for(bucket)
        tzinfo = timezone.get_current_timezone()

        # Clientes criados
        cli_qs = (
            Cliente.objects.filter(criado_em__range=(start, end))
            .annotate(period=Trunc("criado_em", tzinfo=tzinfo))
            .values("period")
            .annotate(total=Count("id"))
        )

        # Petições criadas
        pc_qs = (
            Petition.objects.filter(created_at__range=(start, end))
            .annotate(period=Trunc("created_at", tzinfo=tzinfo))
            .values("period")
            .annotate(total=Count("id"))
        )

        # Petições atualizadas
        pu_qs = (
            Petition.objects.filter(updated_at__range=(start, end))
            .annotate(period=Trunc("updated_at", tzinfo=tzinfo))
            .values("period")
            .annotate(total=Count("id"))
        )

        # Mapear por chave string do período
        map_cli = {norm_key(bucket, r["period"]): r["total"] for r in cli_qs}
        map_pc = {norm_key(bucket, r["period"]): r["total"] for r in pc_qs}
        map_pu = {norm_key(bucket, r["period"]): r["total"] for r in pu_qs}

        series = []
        for dt in periods_range(start, end, bucket):
            key = norm_key(bucket, dt)
            series.append({
                "period": key,
                "clientes": int(map_cli.get(key, 0)),
                "peticoes_criadas": int(map_pc.get(key, 0)),
                "peticoes_atualizadas": int(map_pu.get(key, 0)),
            })

        return Response({
            "bucket": bucket,
            "date_from": d_from.isoformat(),
            "date_to": d_to.isoformat(),
            "series": series,
        })


@method_decorator(cache_page(300), name="dispatch")
class TemplatesUsageView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = TemplatesUsageQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        top = q.validated_data["top"]
        d_from = q.validated_data.get("date_from")
        d_to = q.validated_data.get("date_to")

        qs = Petition.objects.all()
        if d_from and d_to:
            start, end = to_window(d_from, d_to)
            qs = qs.filter(created_at__range=(start, end))

        data = (
            qs.values("template_id", "template__name")
            .annotate(count=Count("id"))
            .order_by("-count")[:top]
        )

        results = [
            {"template_id": r["template_id"], "template": r["template__name"], "count": r["count"]}
            for r in data
        ]
        return Response(results)


@method_decorator(cache_page(300), name="dispatch")
class DataQualityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        total = Cliente.objects.count()

        sem_cpf = Cliente.objects.filter(
            Q(cpf__isnull=True) | Q(cpf="") | Q(cpf__iexact="null")
        ).count()

        def not_blank(field):
            return ~Q(**{f"{field}__isnull": True}) & ~Q(**{f"{field}": ""})

        com_endereco = Cliente.objects.filter(
            not_blank("logradouro")
            & not_blank("numero")
            & not_blank("bairro")
            & not_blank("cidade")
            & not_blank("uf")
            & not_blank("cep")
        ).count()

        sem_endereco = max(0, total - com_endereco)

        clientes_com_conta_principal = (
            ContaBancaria.objects.filter(is_principal=True)
            .values("cliente").distinct().count()
        )

        return Response({
            "total_clientes": total,
            "sem_cpf": sem_cpf,
            "sem_endereco": sem_endereco,
            "com_conta_principal": clientes_com_conta_principal,
        })


class ExportPetitionsCSVView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = ExportPetitionsQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)

        d_from = q.validated_data.get("date_from")
        d_to = q.validated_data.get("date_to")
        template_id = q.validated_data.get("template")
        cliente_id = q.validated_data.get("cliente")

        qs = Petition.objects.select_related("cliente", "template").all()

        if d_from and d_to:
            start, end = to_window(d_from, d_to)
            qs = qs.filter(created_at__range=(start, end))
        if template_id:
            qs = qs.filter(template_id=template_id)
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)

        # ---------- CSV amigável p/ Excel (pt-BR) ----------
        import csv
        import io

        # Buffer com \n coerente; escrevemos BOM manualmente
        buffer = io.StringIO(newline='')
        # Instrução p/ Excel: use ';' como separador
        buffer.write('sep=;\n')

        writer = csv.writer(
            buffer,
            delimiter=';',           # Excel PT-BR ama ';'
            quoting=csv.QUOTE_MINIMAL,
            lineterminator='\n',
        )

        # Cabeçalho legível
        writer.writerow([
            'ID', 'Cliente ID', 'Cliente',
            'Template ID', 'Template',
            'Criada em', 'Atualizada em',
        ])

        def fmt_dt(dt):
            if not dt:
                return ''
            # Converte para timezone atual e formata
            local = timezone.localtime(dt, timezone.get_current_timezone())
            return local.strftime('%d/%m/%Y %H:%M:%S')

        for p in qs.order_by('-created_at'):
            writer.writerow([
                p.id,
                p.cliente_id or '',
                getattr(p.cliente, 'nome_completo', '') if p.cliente_id else '',
                p.template_id or '',
                getattr(p.template, 'name', '') if p.template_id else '',
                fmt_dt(p.created_at),
                fmt_dt(p.updated_at),
            ])

        # Monta resposta com BOM + CSV
        csv_text = buffer.getvalue()
        content = '\ufeff' + csv_text  # BOM UTF-8
        filename = "peticoes.csv"
        if d_from and d_to:
            filename = f"peticoes_{d_from.strftime('%Y%m%d')}-{d_to.strftime('%Y%m%d')}.csv"

        resp = HttpResponse(content, content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = f'attachment; filename="{filename}"'
        return resp


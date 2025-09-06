# cadastro/filters.py
import django_filters as df
from django.db.models import Q
from .models import Cliente, ContaBancaria
from .validators import only_digits

class ClienteFilter(df.FilterSet):
    # Busca por nome com "contains" (case-insensitive)
    nome_icontains = df.CharFilter(field_name="nome_completo", lookup_expr="icontains")
    # CPF com normalização (aceita com/sem máscara)
    cpf = df.CharFilter(method="filter_cpf")
    # Cidade parcial
    cidade_icontains = df.CharFilter(field_name="cidade", lookup_expr="icontains")
    # UF exata (2 letras)
    uf = df.CharFilter(field_name="uf", lookup_expr="iexact")
    # Intervalo de criação
    criado_em_de = df.DateTimeFilter(field_name="criado_em", lookup_expr="gte")
    criado_em_ate = df.DateTimeFilter(field_name="criado_em", lookup_expr="lte")
    # Booleano direto
    se_idoso = df.BooleanFilter(field_name="se_idoso")

    class Meta:
        model = Cliente
        fields = ["uf", "se_idoso"]

    def filter_cpf(self, queryset, name, value):
        return queryset.filter(cpf=only_digits(value or ""))

class ContaBancariaFilter(df.FilterSet):
    cliente = df.NumberFilter(field_name="cliente_id")
    banco_nome_icontains = df.CharFilter(field_name="banco_nome", lookup_expr="icontains")
    tipo = df.CharFilter(field_name="tipo")
    is_principal = df.BooleanFilter(field_name="is_principal")
    agencia_icontains = df.CharFilter(field_name="agencia", lookup_expr="icontains")
    conta_icontains = df.CharFilter(field_name="conta", lookup_expr="icontains")
    criado_em_de = df.DateTimeFilter(field_name="criado_em", lookup_expr="gte")
    criado_em_ate = df.DateTimeFilter(field_name="criado_em", lookup_expr="lte")

    class Meta:
        model = ContaBancaria
        fields = ["cliente", "tipo", "is_principal"]

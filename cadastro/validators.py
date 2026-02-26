import re
from typing import Optional

from django.core.exceptions import ValidationError
from stdnum.br import cpf as cpfmod
from stdnum.br import cnpj as cnpjmod

# Conjunto de UFs válidas
UF_LIST = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG",
    "PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
}


# =========================
# Normalizações básicas
# =========================
def only_digits(value: Optional[str]) -> str:
    """Remove tudo que não for dígito. Aceita None e retorna ''."""
    return re.sub(r"\D+", "", value or "")


# =========================
# Validadores BR
# =========================
def validate_cpf(value: str) -> None:
    """
    Valida CPF (com ou sem máscara). Lança ValidationError se inválido.
    Normalização (remover máscara) fica a cargo de serializers/models.
    """
    digits = only_digits(value)
    if not cpfmod.is_valid(digits):
        raise ValidationError("CPF inválido.")


def validate_cnpj(value: str) -> None:
    """
    Valida CNPJ (com ou sem máscara). Lança ValidationError se inválido.
    Normalização (remover máscara) fica a cargo de serializers/models.
    """
    digits = only_digits(value)
    if not cnpjmod.is_valid(digits):
        raise ValidationError("CNPJ inválido.")


def validate_cep(value: str) -> None:
    """
    Valida CEP: exatamente 8 dígitos (sem máscara).
    """
    digits = only_digits(value)
    if len(digits) != 8:
        raise ValidationError("CEP deve ter 8 dígitos (somente números).")


def validate_uf(value: str) -> None:
    """
    Valida UF: precisa estar presente e ser uma das siglas conhecidas.
    Observação: se o campo for opcional, cheque 'if value:' antes de chamar.
    """
    if not value:
        raise ValidationError("UF é obrigatório.")
    if value.upper() not in UF_LIST:
        raise ValidationError("UF inválida.")


# =========================
# Banco: IDs e códigos
# =========================
# Aceita:
# - COMPE (3 dígitos), ex.: "001"
# - ISPB (8 dígitos), ex.: "60746948"
# - Slug alfanumérico 3–32 com A–Z, 0–9, _ ou -, ex.: "CARD-DEP"
_BANK_ID_RE = re.compile(r"^(?:\d{3}|\d{8}|[A-Z0-9][A-Z0-9_-]{1,30}[A-Z0-9])$")


def validate_banco_id(value: str) -> str:
    """
    Valida e normaliza 'banco_id' para maiúsculas.
    Retorna a string normalizada.
    """
    v = (value or "").strip().upper()
    if v and not _BANK_ID_RE.match(v):
        raise ValidationError(
            "banco_id deve ser COMPE (3 dígitos), ISPB (8 dígitos) ou slug A–Z/0–9/_/- (3–32)."
        )
    return v


def validate_compe(value: str) -> str:
    """
    Valida código COMPE (3 dígitos). Retorna a versão normalizada (apenas dígitos).
    """
    v = only_digits(value)
    if v and len(v) != 3:
        raise ValidationError("Código COMPE deve ter 3 dígitos.")
    return v


def normalize_bank_id(value: str) -> str:
    """
    Normaliza IDs não-numéricos para um slug seguro (A–Z/0–9/_/-), máx. 32 chars.
    Útil quando o sistema recebe um nome de banco e precisa gerar um 'banco_id' estável.
    """
    v = (value or "").upper().strip()
    # troca espaços/pontos por hífen e remove o resto que não seja A–Z/0–9/_/-
    v = re.sub(r"[\s\.]+", "-", v)
    v = re.sub(r"[^A-Z0-9_-]", "", v)
    # limita a 32 caracteres e remove hífens/underscores nas pontas
    v = v[:32].strip("-_")
    return v

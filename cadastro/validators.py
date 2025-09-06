import re
from django.core.exceptions import ValidationError
from stdnum.br import cpf as cpfmod

UF_LIST = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG",
    "PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
}

def only_digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")

def validate_cpf(value: str):
    digits = only_digits(value)
    if not cpfmod.is_valid(digits):
        raise ValidationError("CPF inválido.")
    # validators só validam; normalizamos no model.clean()

def validate_cep(value: str):
    digits = only_digits(value)
    if len(digits) != 8:
        raise ValidationError("CEP deve ter 8 dígitos (somente números).")

def validate_uf(value: str):
    if not value:
        raise ValidationError("UF é obrigatório.")
    if value.upper() not in UF_LIST:
        raise ValidationError("UF inválida.")

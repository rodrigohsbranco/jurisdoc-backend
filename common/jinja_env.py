# common/jinja_env.py  (crie um pequeno módulo numa app comum sua)
from jinja2 import Environment, StrictUndefined

def _digits(v): return "".join(ch for ch in str(v) if ch.isdigit())

def cpf_format(v):
    s = _digits(v); return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:11]}" if len(s)==11 else v

def cep_format(v):
    s = _digits(v); return f"{s[:5]}-{s[5:8]}" if len(s)==8 else v

def build_env() -> Environment:
    env = Environment(undefined=StrictUndefined, autoescape=False)
    env.filters.update({
        "cpf_format": cpf_format,
        "cep_format": cep_format,
    })
    return env

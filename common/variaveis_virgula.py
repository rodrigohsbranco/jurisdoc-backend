# common/variaveis_virgula.py
# Variáveis "irmãs" com sufixo `_v` para qualificação de partes nos templates.
#
# `X_v` vale "valor, " quando X tem conteúdo e "" quando está vazio/ausente.
# Assim o template escreve `{{ nome_cliente_v }}{{ nacionalidade_v }}...`
# sem vírgula fixa, e campos vazios não deixam ", ," no documento.
# As variáveis originais (X) não são alteradas.

# Bases que ganham a irmã `_v`. Para estender, basta acrescentar o nome aqui.
CAMPOS_COM_VIRGULA: tuple[str, ...] = (
    "nome_cliente",
    "nome_completo",
    "nacionalidade",
    "estado_civil",
    "profissao",
    "cpf_cliente",
    "cpf",
    "rg",
    "rogado_nome",
    "rogado_cpf",
    "responsavel_legal_nome",
    "responsavel_legal_cpf",
    "responsavel_imovel_nome",
    "responsavel_imovel_cpf",
)

SUFIXO_VIRGULA = "_v"

# Nomes gerados automaticamente (não devem ser pedidos ao usuário).
VARIAVEIS_VIRGULA: frozenset[str] = frozenset(f"{b}{SUFIXO_VIRGULA}" for b in CAMPOS_COM_VIRGULA)


def _com_virgula(valor) -> str:
    if valor is None:
        return ""
    texto = str(valor).strip()
    return f"{texto}, " if texto else ""


def adicionar_variaveis_virgula(context: dict) -> dict:
    """Acrescenta as variáveis `X_v` ao contexto (in-place) e o devolve.

    - Chave base ausente → `X_v = ""` (o Jinja usa StrictUndefined).
    - `X_v` já presente no contexto → mantido como veio.
    """
    for base in CAMPOS_COM_VIRGULA:
        chave = f"{base}{SUFIXO_VIRGULA}"
        if chave in context:
            continue
        context[chave] = _com_virgula(context.get(base))
    return context

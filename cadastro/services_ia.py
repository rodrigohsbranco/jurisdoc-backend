"""Extração de dados de documentos do cliente via IA (OpenAI Vision).

Recebe os arquivos já enviados pelo operador (documentos pessoais ou comprovantes
de residência) e devolve os campos lidos em JSON estruturado, para pré-preencher
o formulário do kit. O preenchimento manual continua sendo o caminho padrão —
a IA é um atalho, e o operador sempre revisa antes de salvar.

Dois modelos, por custo/precisão:
  - identidade (RG, CNH): `gpt-4o` — layout denso, fundo de segurança, texto miúdo.
    O `mini` erra sistematicamente nesses documentos.
  - comprovante de residência: `gpt-4o-mini` — texto corrido, resolve bem e é ~10x
    mais barato.

PDFs são convertidos página a página em JPEG (PyMuPDF, zoom 3×) porque a API de
visão da OpenAI não aceita PDF nativo. Zoom 2× já degrada a leitura de CNH.
"""
from __future__ import annotations

import base64
import json
import logging
import re

from django.conf import settings

logger = logging.getLogger(__name__)

TIPO_IDENTIDADE = "identidade"
TIPO_COMPROVANTE = "comprovante_residencia"
TIPOS_VALIDOS = (TIPO_IDENTIDADE, TIPO_COMPROVANTE)

# Limites — protegem custo e tempo de resposta
MAX_ARQUIVOS = 4
MAX_PAGINAS_PDF = 3
MAX_BYTES_ARQUIVO = 10 * 1024 * 1024  # 10 MB
PDF_ZOOM = 3  # essencial: com 2× o modelo erra campos pequenos da CNH

MIMES_IMAGEM = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

CAMPOS_IDENTIDADE = (
    "nome_completo", "cpf", "rg", "orgao_expedidor",
    "data_nascimento", "genero", "nacionalidade",
)
CAMPOS_COMPROVANTE = (
    "logradouro", "numero", "complemento", "bairro", "cidade", "uf", "cep",
)


class ExtracaoIAError(Exception):
    """Erro tratável da extração — carrega o status HTTP que a view deve devolver."""

    def __init__(self, mensagem: str, status_code: int = 502):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PROMPT_IDENTIDADE = """Você é um especialista em leitura de documentos de identificação brasileiros (RG, CNH, CPF, passaporte).

Analise CUIDADOSAMENTE o documento e extraia cada campo localizando EXATAMENTE o rótulo correspondente.

Mapeamento de rótulos → campos:
- Rótulo "NOME" → nome_completo (copie EXATAMENTE, incluindo nome do meio)
- Rótulo "DATA NASC", "NASCIMENTO", "DT. NASC.", "DATA DE NASCIMENTO" → data_nascimento (converta DD/MM/AAAA para YYYY-MM-DD)
- Rótulo "CPF" → cpf (somente os 11 dígitos, sem pontos ou traços)
- Rótulo "RG", "REG. IDENTIDADE", "IDENTIDADE", "REGISTRO GERAL" → rg (número sem traços ou pontos)
- Rótulo "ÓRGÃO EMISSOR", "ORG. EMISSOR", "ÓRGÃO EXPEDIDOR" → orgao_expedidor (ex: SSP/SC)
- Rótulo "SEXO" ou "GÊNERO" → genero: "M" ou "MASCULINO" → "masculino"; "F" ou "FEMININO" → "feminino"
- Rótulo "NACIONALIDADE" → nacionalidade em minúsculas (ex: "brasileiro" ou "brasileira")

REGRAS OBRIGATÓRIAS:
1. Copie o NOME exatamente como está — nunca omita o nome do meio
2. Para DATA NASC: leia os números com atenção — não inverta dia/mês
3. Se um campo não estiver claramente visível, use null — nunca adivinhe
4. Retorne APENAS o JSON abaixo, sem texto adicional, sem markdown

{
  "nome_completo": null,
  "cpf": null,
  "rg": null,
  "orgao_expedidor": null,
  "data_nascimento": null,
  "genero": null,
  "nacionalidade": null
}"""

PROMPT_COMPROVANTE = """Analise o(s) comprovante(s) de residência fornecido(s) (conta de água, energia, telefone, extrato bancário ou similar) e extraia o endereço.

Retorne APENAS um JSON válido com os campos abaixo. Use null para campos não encontrados. Não inclua texto fora do JSON.

{
  "logradouro": "nome da rua, avenida, etc (sem número)",
  "numero": "número do imóvel",
  "complemento": "apto, bloco, sala, etc",
  "bairro": "nome do bairro",
  "cidade": "nome da cidade",
  "uf": "sigla do estado com 2 letras maiúsculas, ex: SC",
  "cep": "somente números, 8 dígitos, sem traço"
}"""

_CONFIG_POR_TIPO = {
    TIPO_IDENTIDADE: {
        "prompt": PROMPT_IDENTIDADE,
        "campos": CAMPOS_IDENTIDADE,
        "setting_modelo": "OPENAI_MODEL_IDENTIDADE",
        "modelo_padrao": "gpt-4o",
    },
    TIPO_COMPROVANTE: {
        "prompt": PROMPT_COMPROVANTE,
        "campos": CAMPOS_COMPROVANTE,
        "setting_modelo": "OPENAI_MODEL",
        "modelo_padrao": "gpt-4o-mini",
    },
}


# ---------------------------------------------------------------------------
# Preparo dos arquivos
# ---------------------------------------------------------------------------

def _pdf_para_imagens(pdf_bytes: bytes, nome: str) -> list[bytes]:
    """Converte as primeiras páginas do PDF em JPEG (a Vision não aceita PDF)."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover — dependência declarada em requirements
        raise ExtracaoIAError(
            "PyMuPDF não instalado no servidor — não é possível ler PDFs. "
            "Envie o documento como imagem ou instale a dependência.",
            status_code=503,
        ) from exc

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            paginas = min(len(doc), MAX_PAGINAS_PDF)
            matriz = fitz.Matrix(PDF_ZOOM, PDF_ZOOM)
            return [doc[i].get_pixmap(matrix=matriz).tobytes("jpeg") for i in range(paginas)]
    except ExtracaoIAError:
        raise
    except Exception as exc:
        raise ExtracaoIAError(
            f"Não foi possível ler o PDF '{nome}'. O arquivo pode estar corrompido.",
            status_code=422,
        ) from exc


def _preparar_imagens(arquivos: list[tuple[str, bytes]]) -> list[tuple[bytes, str]]:
    """Normaliza os arquivos recebidos em uma lista de (bytes, mime) de imagens.

    `arquivos` é uma lista de (nome_do_arquivo, conteudo). PDFs viram uma imagem
    por página; imagens passam direto. Formatos não suportados são rejeitados.
    """
    if not arquivos:
        raise ExtracaoIAError("Nenhum documento disponível para leitura.", status_code=422)

    imagens: list[tuple[bytes, str]] = []
    for nome, conteudo in arquivos[:MAX_ARQUIVOS]:
        if len(conteudo) > MAX_BYTES_ARQUIVO:
            raise ExtracaoIAError(
                f"O arquivo '{nome}' passa de 10 MB — reduza o tamanho antes de usar a leitura por IA.",
                status_code=422,
            )

        ext = ("." + nome.rsplit(".", 1)[-1].lower()) if "." in nome else ""
        if ext == ".pdf":
            imagens.extend((img, "image/jpeg") for img in _pdf_para_imagens(conteudo, nome))
        elif ext in MIMES_IMAGEM:
            imagens.append((conteudo, MIMES_IMAGEM[ext]))
        else:
            raise ExtracaoIAError(
                f"Formato não suportado em '{nome}'. Use JPG, PNG, WEBP, GIF ou PDF.",
                status_code=422,
            )

    if not imagens:
        raise ExtracaoIAError("Nenhuma página legível encontrada nos documentos.", status_code=422)
    return imagens


def _conteudo_imagem(img_bytes: bytes, mime: str) -> dict:
    b64 = base64.b64encode(img_bytes).decode()
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime};base64,{b64}",
            "detail": "high",  # obrigatório para leitura de documento
        },
    }


# ---------------------------------------------------------------------------
# Parse e normalização da resposta
# ---------------------------------------------------------------------------

def _parse_json_resposta(raw_text: str) -> dict:
    """Extrai o JSON da resposta, tolerando cerca markdown (```json ... ```)."""
    texto = (raw_text or "").strip()
    if texto.startswith("```"):
        partes = texto.split("```")
        if len(partes) > 1:
            texto = partes[1]
            if texto.lstrip().lower().startswith("json"):
                texto = texto.lstrip()[4:]
    try:
        dados = json.loads(texto.strip())
    except json.JSONDecodeError:
        logger.warning(f"IA: resposta não é JSON válido — {raw_text[:200]!r}")
        return {}
    return dados if isinstance(dados, dict) else {}


def _so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


def _normalizar(dados: dict, campos: tuple[str, ...]) -> dict:
    """Limpa e valida os campos lidos. Valor inválido vira None, nunca chute."""
    limpo: dict = {campo: None for campo in campos}

    for campo in campos:
        valor = dados.get(campo)
        if valor is None:
            continue
        valor = str(valor).strip()
        # O modelo às vezes devolve a própria descrição do campo quando não acha
        if not valor or valor.lower() in {"null", "none", "n/a", "não informado", "nao informado"}:
            continue
        limpo[campo] = valor

    if "cpf" in limpo and limpo["cpf"]:
        digitos = _so_digitos(limpo["cpf"])
        limpo["cpf"] = digitos if len(digitos) == 11 else None

    if "cep" in limpo and limpo["cep"]:
        digitos = _so_digitos(limpo["cep"])
        limpo["cep"] = digitos if len(digitos) == 8 else None

    if "uf" in limpo and limpo["uf"]:
        uf = limpo["uf"].upper()
        limpo["uf"] = uf if uf in UFS_VALIDAS else None

    if "genero" in limpo and limpo["genero"]:
        genero = limpo["genero"].lower()
        limpo["genero"] = genero if genero in {"masculino", "feminino"} else None

    if "nacionalidade" in limpo and limpo["nacionalidade"]:
        limpo["nacionalidade"] = limpo["nacionalidade"].lower()

    if "data_nascimento" in limpo and limpo["data_nascimento"]:
        limpo["data_nascimento"] = _normalizar_data(limpo["data_nascimento"])

    if "rg" in limpo and limpo["rg"]:
        # mantém letras (alguns RGs têm dígito verificador X), tira pontuação
        limpo["rg"] = re.sub(r"[^0-9A-Za-z]", "", limpo["rg"]) or None

    return limpo


def _normalizar_data(valor: str) -> str | None:
    """Aceita YYYY-MM-DD (esperado) ou DD/MM/AAAA (fallback). Inválido → None."""
    valor = valor.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        ano, mes, dia = (int(p) for p in valor.split("-"))
    elif re.fullmatch(r"\d{2}/\d{2}/\d{4}", valor):
        dia, mes, ano = (int(p) for p in valor.split("/"))
    else:
        return None

    if not (1 <= mes <= 12 and 1 <= dia <= 31 and 1900 <= ano <= 2100):
        return None
    return f"{ano:04d}-{mes:02d}-{dia:02d}"


# ---------------------------------------------------------------------------
# Chamada à OpenAI
# ---------------------------------------------------------------------------

def _cliente_openai():
    api_key = (getattr(settings, "OPENAI_API_KEY", "") or "").strip()
    if not api_key:
        raise ExtracaoIAError(
            "Leitura por IA indisponível: OPENAI_API_KEY não configurada no servidor.",
            status_code=503,
        )
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover — dependência declarada em requirements
        raise ExtracaoIAError(
            "SDK da OpenAI não instalado no servidor.",
            status_code=503,
        ) from exc
    return OpenAI(api_key=api_key, timeout=90.0)


def extrair_dados(arquivos: list[tuple[str, bytes]], tipo: str) -> dict:
    """Lê os documentos e devolve os campos extraídos.

    Parâmetros:
        arquivos: lista de (nome_do_arquivo, conteudo_em_bytes)
        tipo: "identidade" ou "comprovante_residencia"

    Retorna:
        {"dados_extraidos": {...}, "uso_tokens": {...}, "modelo": str}

    Lança ExtracaoIAError com `status_code` apropriado em qualquer falha tratável.
    """
    config = _CONFIG_POR_TIPO.get(tipo)
    if config is None:
        raise ExtracaoIAError(
            f"Tipo inválido: '{tipo}'. Use 'identidade' ou 'comprovante_residencia'.",
            status_code=422,
        )

    imagens = _preparar_imagens(arquivos)
    modelo = (
        getattr(settings, config["setting_modelo"], "") or config["modelo_padrao"]
    ).strip()
    client = _cliente_openai()

    conteudo = [{"type": "text", "text": config["prompt"]}]
    conteudo.extend(_conteudo_imagem(img, mime) for img, mime in imagens)

    try:
        resposta = client.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": conteudo}],
            max_tokens=600,
            temperature=0,  # determinístico — essencial para extração de dados
        )
    except Exception as exc:
        raise ExtracaoIAError(_mensagem_erro_openai(exc), status_code=502) from exc

    bruto = resposta.choices[0].message.content if resposta.choices else ""
    dados = _normalizar(_parse_json_resposta(bruto), config["campos"])

    uso = getattr(resposta, "usage", None)
    uso_tokens = {
        "input": getattr(uso, "prompt_tokens", 0) or 0,
        "output": getattr(uso, "completion_tokens", 0) or 0,
        "total": getattr(uso, "total_tokens", 0) or 0,
    }

    preenchidos = [k for k, v in dados.items() if v]
    logger.info(
        f"IA ({tipo}): modelo={modelo} paginas={len(imagens)} "
        f"tokens={uso_tokens['total']} campos_lidos={preenchidos}"
    )

    return {"dados_extraidos": dados, "uso_tokens": uso_tokens, "modelo": modelo}


def _mensagem_erro_openai(exc: Exception) -> str:
    """Traduz erros do SDK em mensagens úteis para o operador."""
    nome = type(exc).__name__
    if nome == "AuthenticationError":
        logger.error("IA: chave da OpenAI inválida ou expirada")
        return "Chave da OpenAI inválida ou expirada. Verifique a configuração do servidor."
    if nome == "RateLimitError":
        logger.warning("IA: rate limit / cota da OpenAI atingida")
        return "Limite de uso da OpenAI atingido. Tente novamente em instantes."
    if nome in {"APITimeoutError", "APIConnectionError"}:
        logger.warning(f"IA: falha de conexão com a OpenAI — {exc}")
        return "Não foi possível falar com a OpenAI agora. Tente novamente."
    logger.error(f"IA: erro da OpenAI ({nome}) — {exc}")
    return "Falha ao processar os documentos na OpenAI. Tente novamente."

"""Aviso ao escritório, por WhatsApp, quando um cliente conclui o autocadastro.

Exclusivo da área "Sou cliente" do app FlowALR. Reaproveita a mesma instância do
uazapi usada para enviar o código de acesso.

Regra de ouro: **falha aqui nunca derruba o cadastro do cliente**. Ele preencheu
tudo e clicou em salvar; perder isso porque o WhatsApp do escritório está fora do
ar seria inaceitável. Todo erro é registrado em log e a conclusão segue.
"""
from __future__ import annotations

import logging

from django.conf import settings

from . import services_uazapi as uazapi

logger = logging.getLogger(__name__)

GENEROS = {"masculino": "Masculino", "feminino": "Feminino"}
CONDICOES = {
    "alfabetizado": "Alfabetizado",
    "analfabeto": "Analfabeto (assina a rogo)",
    "incapaz": "Incapaz (com responsável legal)",
    "crianca_adolescente": "Criança/Adolescente (com responsável legal)",
}


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------

def _cpf(valor: str) -> str:
    d = "".join(c for c in str(valor or "") if c.isdigit())
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else (valor or "—")


def _telefone(valor: str) -> str:
    d = "".join(c for c in str(valor or "") if c.isdigit())
    if len(d) >= 12 and d.startswith("55"):
        d = d[2:]
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return valor or "—"


def _cep(valor: str) -> str:
    d = "".join(c for c in str(valor or "") if c.isdigit())
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else (valor or "")


def _data(valor) -> str:
    try:
        return valor.strftime("%d/%m/%Y")
    except AttributeError:
        return str(valor) if valor else "—"


def _linha(rotulo: str, valor) -> str | None:
    """Devolve a linha só quando há valor — evita mensagem cheia de traços."""
    texto = str(valor).strip() if valor not in (None, "") else ""
    return f"• {rotulo}: {texto}" if texto else None


# ---------------------------------------------------------------------------
# Montagem da mensagem
# ---------------------------------------------------------------------------

def montar_mensagem(cliente, telefone_acesso: str = "", indicado_por=None,
                    kit_id: int | None = None) -> str:
    blocos: list[str] = ["🆕 *NOVO PRÉ-CADASTRO PELO APP*"]

    pessoais = [
        _linha("Nome", cliente.nome_completo),
        _linha("CPF", _cpf(cliente.cpf)),
        _linha("Nascimento", _data(cliente.data_nascimento)),
        _linha("Gênero", GENEROS.get(cliente.genero, cliente.genero)),
        _linha("Nacionalidade", cliente.nacionalidade),
        _linha("Estado civil", cliente.estado_civil),
        _linha("Profissão", cliente.profissao),
        _linha("RG", cliente.rg),
        _linha("Órgão expedidor", cliente.orgao_expedidor),
        _linha("Condição", CONDICOES.get(cliente.condicao_cliente, cliente.condicao_cliente)),
    ]
    blocos.append("👤 *DADOS PESSOAIS*\n" + "\n".join(p for p in pessoais if p))

    contatos = [_linha("WhatsApp do acesso", _telefone(telefone_acesso))]
    if cliente.telefone and _telefone(cliente.telefone) != _telefone(telefone_acesso):
        contatos.append(_linha("Telefone informado", _telefone(cliente.telefone)))
    for extra in (cliente.telefones_extras or [])[:3]:
        contatos.append(_linha("Telefone adicional", _telefone(extra.get("numero", ""))))
    contatos = [c for c in contatos if c]
    if contatos:
        blocos.append("📞 *CONTATO*\n" + "\n".join(contatos))

    rua = ", ".join(x for x in [cliente.logradouro, cliente.numero] if x)
    if cliente.complemento:
        rua = f"{rua} — {cliente.complemento}" if rua else cliente.complemento
    cidade_uf = "/".join(x for x in [cliente.cidade, cliente.uf] if x)
    localidade = ", ".join(x for x in [cliente.bairro, cidade_uf] if x)
    endereco = [_linha("Endereço", rua), _linha("Bairro/Cidade", localidade),
                _linha("CEP", _cep(cliente.cep))]
    endereco = [e for e in endereco if e]
    if endereco:
        blocos.append("🏠 *ENDEREÇO*\n" + "\n".join(endereco))

    # Pessoas vinculadas — só aparecem quando a condição do cliente exige
    vinculadas = [
        _linha("Rogado", cliente.rogado_nome),
        _linha("Testemunha 1", cliente.testemunha1_nome),
        _linha("Testemunha 2", cliente.testemunha2_nome),
        _linha("Responsável legal", cliente.responsavel_legal_nome),
        _linha("Responsável pelo imóvel", cliente.responsavel_imovel_nome),
    ]
    vinculadas = [v for v in vinculadas if v]
    if vinculadas:
        blocos.append("👥 *PESSOAS VINCULADAS*\n" + "\n".join(vinculadas))

    arquivos = [
        _linha("Documentos pessoais", len(cliente.documentos_pessoais or []) or None),
        _linha("Comprovantes de residência", len(cliente.comprovantes_residencia or []) or None),
        _linha("Fotos da residência", len(cliente.fotos_residencia or []) or None),
        _linha("Foto do cliente", "sim" if cliente.foto_cliente else None),
    ]
    arquivos = [a for a in arquivos if a]
    blocos.append(
        "📎 *DOCUMENTOS ENVIADOS*\n" + ("\n".join(arquivos) if arquivos
                                        else "• Nenhum documento anexado")
    )

    if indicado_por is not None:
        nome = indicado_por.nome_completo or indicado_por.username
        blocos.append(f"🤝 *ATENDIMENTO*\n• Colaborador responsável: {nome}")
    else:
        blocos.append(
            "🤝 *ATENDIMENTO*\n"
            "• ⚠️ Nenhum colaborador vinculado\n"
            "• Este cliente ainda não está sendo atendido por ninguém"
        )

    jurisdoc = [f"• Pré-cadastro criado — cliente #{cliente.id}"]
    if kit_id:
        jurisdoc.append(f"• Pré-kit bancário criado em rascunho — kit #{kit_id}")
    else:
        jurisdoc.append("• Cliente já possuía kit — nenhum novo rascunho criado")
    blocos.append("✅ *NO JURISDOC*\n" + "\n".join(jurisdoc))

    return "\n\n".join(blocos)


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------

def notificar_escritorio(cliente, telefone_acesso: str = "", indicado_por=None,
                         kit_id: int | None = None) -> bool:
    """Envia o aviso ao WhatsApp do escritório. Nunca levanta exceção."""
    destino = uazapi.normalizar_telefone(
        getattr(settings, "ESCRITORIO_WHATSAPP", "") or ""
    )
    if not destino:
        logger.warning(
            "Pré-cadastro concluído sem aviso ao escritório: ESCRITORIO_WHATSAPP "
            "não configurado."
        )
        return False

    try:
        mensagem = montar_mensagem(cliente, telefone_acesso, indicado_por, kit_id)
        uazapi.enviar_texto(destino, mensagem)
        logger.info(f"Escritório avisado do pré-cadastro do cliente #{cliente.id}")
        return True
    except uazapi.UazapiError as exc:
        logger.error(f"Falha ao avisar o escritório (cliente #{cliente.id}): {exc}")
    except Exception as exc:  # noqa: BLE001 — o cadastro do cliente não pode cair por isso
        logger.error(f"Erro inesperado ao avisar o escritório (cliente #{cliente.id}): {exc}")
    return False

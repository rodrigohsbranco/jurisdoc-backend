from django.conf import settings
from django.db import models
from django.db.models import Q

from .validators import validate_cpf, validate_cnpj, validate_cep, validate_uf, only_digits


# (Opcional) choices simples para estado civil — pode ajustar no futuro no front/back
ESTADO_CIVIL_CHOICES = [
    ("solteiro", "Solteiro(a)"),
    ("casado", "Casado(a)"),
    ("divorciado", "Divorciado(a)"),
    ("viuvo", "Viúvo(a)"),
    ("uniao_estavel", "União estável"),
]


class Cliente(models.Model):
    # Identificação
    nome_completo = models.CharField(max_length=200, db_index=True)
    cpf = models.CharField(max_length=11, unique=True, validators=[validate_cpf])
    rg = models.CharField(max_length=20, blank=True)
    orgao_expedidor = models.CharField(max_length=20, blank=True)

    # ⚠️ Campo legado: mantido no schema, mas não usar no front (deixar oculto na UI)
    qualificacao = models.TextField(blank=True)  # [DEPRECADO] manter por compatibilidade

    # Sinalizadores de prioridade/condição
    se_idoso = models.BooleanField(default=False)
    se_incapaz = models.BooleanField(default=False)
    se_crianca_adolescente = models.BooleanField(default=False)

    # Data de nascimento (obrigatório para kits previdenciários)
    data_nascimento = models.DateField(null=True, blank=True)

    # Dados civis
    nacionalidade = models.CharField(max_length=60, blank=True)
    estado_civil = models.CharField(max_length=20, blank=True)  # ou choices=ESTADO_CIVIL_CHOICES
    profissao = models.CharField(max_length=120, blank=True)

    # Endereço
    logradouro = models.CharField(max_length=120, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    complemento = models.CharField(max_length=100, blank=True)
    bairro = models.CharField(max_length=120, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    cep = models.CharField(max_length=8, blank=True, validators=[validate_cep])
    uf = models.CharField(max_length=2, blank=True, validators=[validate_uf])

    # Dados para Kit
    CONDICAO_CHOICES = [
        ("alfabetizado", "Alfabetizado"),
        ("analfabeto", "Analfabeto"),
        ("incapaz", "Incapaz"),
        ("crianca_adolescente", "Criança/Adolescente"),
    ]
    condicao_cliente = models.CharField(max_length=25, choices=CONDICAO_CHOICES, default="alfabetizado", blank=True)

    # Assinatura a rogo (analfabeto)
    rogado_nome = models.CharField(max_length=200, blank=True)
    rogado_cpf = models.CharField(max_length=11, blank=True)
    rogado_documentos = models.JSONField(default=list, blank=True)
    testemunha1_nome = models.CharField(max_length=200, blank=True)
    testemunha1_cpf = models.CharField(max_length=11, blank=True)
    testemunha1_documentos = models.JSONField(default=list, blank=True)
    testemunha2_nome = models.CharField(max_length=200, blank=True)
    testemunha2_cpf = models.CharField(max_length=11, blank=True)
    testemunha2_documentos = models.JSONField(default=list, blank=True)

    # Responsável legal (incapaz / criança)
    responsavel_legal_nome = models.CharField(max_length=200, blank=True)
    responsavel_legal_cpf = models.CharField(max_length=11, blank=True)
    responsavel_legal_documentos = models.JSONField(default=list, blank=True)

    # Declaração de hipossuficiência
    possui_imoveis = models.BooleanField(null=True, blank=True, default=None)
    possui_moveis = models.BooleanField(null=True, blank=True, default=None)
    isento_irpf = models.BooleanField(null=True, blank=True, default=None)

    # Comprovante de residência (múltiplos arquivos)
    comprovantes_residencia = models.JSONField(
        default=list,
        blank=True,
        help_text='Array JSON de comprovantes do cliente. Cada item: {path, name}',
    )
    comprovante_nome_cliente = models.CharField(max_length=3, blank=True)  # sim/nao
    responsavel_imovel_nome = models.CharField(max_length=200, blank=True)
    responsavel_imovel_cpf = models.CharField(max_length=11, blank=True)
    responsavel_imovel_docs = models.JSONField(
        default=list,
        blank=True,
        help_text='Array JSON de documentos do responsável pelo imóvel. Cada item: {path, name}',
    )

    # Contato — telefone primário (legacy single fields, mantidos para compat)
    telefone = models.CharField(max_length=20, blank=True)
    titular_contato = models.CharField(max_length=3, blank=True)  # sim/nao
    nome_titular_numero = models.CharField(max_length=200, blank=True)
    relacao_titular_tipo = models.CharField(max_length=20, blank=True)  # pai_mae/filho_a/irmao_a/conjuge/outro
    relacao_titular = models.CharField(max_length=100, blank=True)  # quando tipo='outro'
    # Telefones adicionais — cada item: {numero, titular_contato, nome_titular_numero, relacao_titular_tipo, relacao_titular}
    telefones_extras = models.JSONField(
        default=list,
        blank=True,
        help_text='Telefones adicionais. Cada item: {numero, titular_contato, nome_titular_numero, relacao_titular_tipo, relacao_titular}',
    )
    genero = models.CharField(max_length=15, blank=True)  # masculino/feminino

    # Documentos pessoais (RG, CPF, CNH, etc.) — array de paths relativos ao MEDIA_ROOT
    documentos_pessoais = models.JSONField(
        default=list,
        blank=True,
        help_text='Array JSON de caminhos dos arquivos. Ex: ["clientes/docs/123_rg.jpg", ...]'
    )

    # Benefícios (INSS, etc.)
    beneficios = models.JSONField(
        default=list,
        blank=True,
        help_text="Array JSON de benefícios. Cada item: {numero: string, tipo: string}"
    )

    # Geolocalização da residência
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    # Fotos da residência (rua + casa, galeria única) — array de {path, name}
    fotos_residencia = models.JSONField(
        default=list,
        blank=True,
        help_text='Array JSON de fotos da residência. Cada item: {path, name}',
    )

    # Foto 3x4 do cliente — {path, name} ou None
    foto_cliente = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text='Foto 3x4 do cliente: {path, name} ou None.',
    )

    # Status (soft delete)
    is_active = models.BooleanField(default=True, db_index=True)

    # Origem do cadastro — distingue quem o escritório cadastrou de quem se
    # cadastrou sozinho pelo app (pré-cadastro), para o operador filtrar.
    ORIGEM_CHOICES = [
        ("jurisdoc", "JurisDoc"),
        ("app_cliente", "Pré-cadastro pelo app"),
    ]
    origem = models.CharField(
        max_length=15,
        choices=ORIGEM_CHOICES,
        default="jurisdoc",
        db_index=True,
    )

    # Auditoria
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome_completo"]

    def clean(self):
        # Normalizações simples
        self.cpf = only_digits(self.cpf)
        self.cep = only_digits(self.cep)
        self.uf = (self.uf or "").upper()

    def __str__(self):
        return f"{self.nome_completo} ({self.cpf})"


class ContaClienteApp(models.Model):
    """Credencial do CLIENTE FINAL para o app FlowALR.

    Deliberadamente separada de `accounts.User`: aquele model é a identidade da
    equipe (is_admin, permissões, capacidades) e autentica o SPA do JurisDoc.
    Cliente final nunca deve trafegar por lá.

    O acesso é sempre resolvido a partir desta conta — o cliente só enxerga o
    próprio `cliente`, nunca um id vindo da requisição.
    """

    # Nulo enquanto o cliente ainda não preencheu o cadastro: no login por
    # WhatsApp a conta nasce só com o telefone, e a ficha (que exige CPF único)
    # só é criada quando ele salva os dados.
    cliente = models.OneToOneField(
        Cliente,
        on_delete=models.CASCADE,
        related_name="conta_app",
        null=True,
        blank=True,
    )

    # Identidade principal: número no formato internacional só com dígitos
    # (ex.: 5548999999999), derivado do jid devolvido pelo /chat/check do uazapi
    # — é o que normaliza a variação do nono dígito.
    telefone = models.CharField(
        max_length=20, unique=True, null=True, blank=True, db_index=True
    )
    whatsapp_jid = models.CharField(max_length=60, blank=True, default="")

    # Acesso alternativo (plano B quando o WhatsApp falha). Opcionais: só existem
    # se o cliente cadastrar. Não são mais a porta de entrada padrão.
    email = models.EmailField(unique=True, null=True, blank=True, db_index=True)
    senha_hash = models.CharField(max_length=256, blank=True, default="")

    # Marca que o cliente já disse "não sou eu" para a ficha sugerida pelo
    # telefone — evita perguntar de novo a cada login.
    vinculo_recusado = models.BooleanField(default=False)

    # Usuário do JurisDoc que enviou o link do pré-cadastro para este cliente.
    # Vira o `criado_por` do kit gerado, para que ele enxergue o kit na produção
    # (admins já veem tudo). Nulo quando o app não informa a origem do link.
    indicado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clientes_app_indicados",
    )

    is_active = models.BooleanField(default=True, db_index=True)

    # Auditoria — o vínculo a uma ficha que o escritório já tinha é o evento
    # sensível deste fluxo; fica registrado para auditoria posterior.
    vinculada_a_ficha_existente = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    ultimo_login_em = models.DateTimeField(null=True, blank=True)
    senha_alterada_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Conta de cliente no app"
        verbose_name_plural = "Contas de clientes no app"
        ordering = ["-criado_em"]

    def __str__(self):
        alvo = self.cliente.nome_completo if self.cliente_id else "sem ficha"
        return f"{self.telefone or self.email} → {alvo}"

    def set_senha(self, senha_bruta: str) -> None:
        from django.contrib.auth.hashers import make_password

        self.senha_hash = make_password(senha_bruta)

    def checar_senha(self, senha_bruta: str) -> bool:
        from django.contrib.auth.hashers import check_password

        if not self.senha_hash:
            return False
        return check_password(senha_bruta, self.senha_hash)


class CodigoAcessoCliente(models.Model):
    """Código de acesso de uso único enviado por WhatsApp (login do cliente).

    Uma linha por solicitação. O código nunca é guardado em claro nem escrito em
    log — só o hash. A validação usa sempre a solicitação mais recente do número.
    """

    telefone = models.CharField(max_length=20, db_index=True)
    codigo_hash = models.CharField(max_length=256)
    expira_em = models.DateTimeField(db_index=True)
    tentativas = models.PositiveSmallIntegerField(default=0)
    usado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Código de acesso do cliente"
        verbose_name_plural = "Códigos de acesso do cliente"
        ordering = ["-criado_em"]
        indexes = [models.Index(fields=["telefone", "-criado_em"])]

    def __str__(self):
        return f"{self.telefone} (expira {self.expira_em:%d/%m %H:%M})"

    def set_codigo(self, codigo: str) -> None:
        from django.contrib.auth.hashers import make_password

        self.codigo_hash = make_password(codigo)

    def confere(self, codigo: str) -> bool:
        from django.contrib.auth.hashers import check_password

        return check_password(codigo, self.codigo_hash)


TIPO_CONTA_CHOICES = [
    ("corrente", "Corrente"),
    ("poupanca", "Poupança"),
    ("salario", "Salário"),
]


class ContaBancaria(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="contas")
    banco_nome = models.CharField(max_length=100)               # Ex.: "Banco do Brasil"
    banco_codigo = models.CharField(max_length=5, blank=True)   # Ex.: "001" (COMPE/ISPB curta)
    agencia = models.CharField(max_length=10)
    conta = models.CharField(max_length=20)
    digito = models.CharField(max_length=5, blank=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CONTA_CHOICES, default="corrente")
    is_principal = models.BooleanField(default=False)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("cliente", "banco_nome", "agencia", "conta", "digito")]
        ordering = ["cliente", "banco_nome", "agencia", "conta"]
        constraints = [
            models.UniqueConstraint(
                fields=["cliente"],
                condition=Q(is_principal=True),
                name="unique_principal_per_cliente",
            )
        ]

    def __str__(self):
        dd = f"-{self.digito}" if self.digito else ""
        return f"{self.cliente.nome_completo} | {self.banco_nome} ag {self.agencia} conta {self.conta}{dd}"


# cadastro/models.py
from django.db import models
from django.conf import settings

class DescricaoBanco(models.Model):
    banco_id = models.CharField(max_length=50)
    banco_nome = models.CharField(max_length=255)

    # 🔄 Substituímos o campo 'descricao' pelos novos campos estruturados
    nome_banco = models.CharField(max_length=255, null=True, blank=True)
    cnpj = models.CharField(max_length=18, null=True, blank=True)
    endereco = models.CharField(max_length=255, null=True, blank=True)

    is_ativa = models.BooleanField(default=False)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="descricoes_banco_atualizadas",
    )

    class Meta:
        verbose_name = "Descrição de Banco"
        verbose_name_plural = "Descrições de Bancos"
        ordering = ["banco_nome", "-is_ativa", "-atualizado_em"]
        indexes = [
            models.Index(fields=["banco_id", "is_ativa", "-atualizado_em"], name="cad_desc_bid_act_upd_idx"),
            models.Index(fields=["banco_nome", "is_ativa", "-atualizado_em"], name="cad_desc_bname_act_upd_idx"),
        ]

    def __str__(self):
        return f"{self.banco_nome} - {self.nome_banco} ({'ATIVA' if self.is_ativa else 'Inativa'})"


# --------------------------------------------------------------------
# Representantes do Cliente
# --------------------------------------------------------------------
class Representante(models.Model):
    """
    Pessoa que representa o Cliente (pode haver vários).
    - Se 'usa_endereco_do_cliente' for True, o front pode copiar os campos de endereço do Cliente.
      (Manteremos apenas a flag aqui; a cópia efetiva pode ser feita no front/serializer.)
    - Evitamos duplicidade por (cliente, cpf).
    """
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="representantes")

    # Identificação
    nome_completo = models.CharField(max_length=200, db_index=True)
    cpf = models.CharField(max_length=11, validators=[validate_cpf])
    rg = models.CharField(max_length=20, blank=True)
    orgao_expedidor = models.CharField(max_length=20, blank=True)

    # Sinalizadores (mantidos iguais ao Cliente, caso necessários em templates)
    se_idoso = models.BooleanField(default=False)
    se_incapaz = models.BooleanField(default=False)
    se_crianca_adolescente = models.BooleanField(default=False)

    # Dados civis
    nacionalidade = models.CharField(max_length=60, blank=True)
    estado_civil = models.CharField(max_length=20, blank=True)  # ou choices=ESTADO_CIVIL_CHOICES
    profissao = models.CharField(max_length=120, blank=True)

    # Endereço
    usa_endereco_do_cliente = models.BooleanField(default=False)
    logradouro = models.CharField(max_length=120, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    bairro = models.CharField(max_length=120, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    cep = models.CharField(max_length=8, blank=True, validators=[validate_cep])
    uf = models.CharField(max_length=2, blank=True, validators=[validate_uf])

    # Auditoria
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["cliente", "nome_completo"]
        constraints = [
            # Evita duplicar o mesmo CPF para o mesmo cliente (mas permite o mesmo CPF representar clientes diferentes)
            models.UniqueConstraint(
                fields=["cliente", "cpf"],
                name="unique_representante_por_cliente",
            ),
        ]
        indexes = [
            models.Index(fields=["cliente", "nome_completo"]),
        ]

    def clean(self):
        self.cpf = only_digits(self.cpf)
        self.cep = only_digits(self.cep)
        self.uf = (self.uf or "").upper()

    def __str__(self):
        return f"{self.nome_completo} (rep. de {self.cliente.nome_completo})"


# --------------------------------------------------------------------
# Bancos dos Réus (Clientes como Réus)
# --------------------------------------------------------------------
class ContaBancariaReu(models.Model):
    """
    Banco do réu.
    Armazena informações do banco: nome, CNPJ e endereço.
    Não está mais atrelado a um cliente específico.
    """
    banco_nome = models.CharField(max_length=100)               # Ex.: "Banco do Brasil"
    banco_codigo = models.CharField(max_length=5, blank=True)   # Ex.: "001" (COMPE/ISPB curta)
    cnpj = models.CharField(max_length=14, unique=True, validators=[validate_cnpj])  # CNPJ do banco (único)
    descricao = models.TextField(blank=True)                   # Descrição do banco
    
    # Endereço do banco
    logradouro = models.CharField(max_length=120, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    bairro = models.CharField(max_length=120, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    estado = models.CharField(max_length=2, blank=True, validators=[validate_uf])  # UF do estado
    cep = models.CharField(max_length=8, blank=True, validators=[validate_cep])

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Banco do Réu"
        verbose_name_plural = "Bancos dos Réus"
        ordering = ["banco_nome"]

    def clean(self):
        self.cnpj = only_digits(self.cnpj)
        self.cep = only_digits(self.cep)
        self.estado = (self.estado or "").upper()

    def __str__(self):
        return f"{self.banco_nome} - CNPJ: {self.cnpj}"


# --------------------------------------------------------------------
# Contratos
# --------------------------------------------------------------------
class Contrato(models.Model):
    """
    Contrato vinculado a um Cliente e Template.
    - O campo 'contratos' armazena um array JSONB com os dados de cada contrato.
    - Pode haver múltiplos contratos no array.
    - Cada item do array pode conter:
      * numero_do_contrato: string
      * banco_do_contrato: string
      * situacao: string
      * origem_averbacao: string
      * data_inclusao: string (date)
      * data_inicio_desconto: string (date)
      * data_fim_desconto: string (date)
      * quantidade_parcelas: number
      * valor_parcela: number
      * iof: number
      * valor_emprestado: number
      * valor_liberado: number
    """
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,  # Não permite deletar cliente se tiver contratos
        related_name="contratos_cadastro",
    )
    template = models.ForeignKey(
        "templates_app.Template",  # Importação lazy para evitar dependência circular
        on_delete=models.PROTECT,  # Não permite deletar template se tiver contratos
        related_name="contratos"
    )
    contratos = models.JSONField(
        default=list,
        blank=True,
        help_text="Array JSONB com os dados de cada contrato"
    )
    verifica_documento = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="JSONB com todos os dados do formulário de verificação do documento"
    )
    imagem_do_contrato = models.ImageField(
        upload_to="contratos/",
        null=True,
        blank=True,
        help_text="Imagem do contrato"
    )

    # Auditoria
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contrato"
        verbose_name_plural = "Contratos"
        ordering = ["-criado_em"]

    def __str__(self):
        num_contratos = len(self.contratos) if isinstance(self.contratos, list) else 0
        return f"Contrato #{self.id} - {self.cliente.nome_completo} ({num_contratos} contrato(s))"

"""
Catálogo de capacidades do sistema.

Cada item descreve uma operação atômica (recurso x ação) que pode ser concedida
a uma Permissao. O comando `python manage.py sync_capacidades` faz upsert dessa
lista na tabela Capacidade — adicione uma entrada aqui sempre que criar um novo
endpoint que exija enforce.

Convenção do código: "<recurso>.<acao>" em snake_case (ex.: clientes.deletar).
"""

CAPACIDADES: list[dict] = [
    # ===================== Cadastro =====================
    {"codigo": "clientes.visualizar", "recurso": "Clientes", "acao": "Visualizar",
     "descricao": "Listar e ver detalhes de clientes", "categoria": "Cadastro"},
    {"codigo": "clientes.criar", "recurso": "Clientes", "acao": "Criar",
     "descricao": "Cadastrar novos clientes", "categoria": "Cadastro"},
    {"codigo": "clientes.editar", "recurso": "Clientes", "acao": "Editar",
     "descricao": "Alterar dados de clientes existentes", "categoria": "Cadastro"},
    {"codigo": "clientes.deletar", "recurso": "Clientes", "acao": "Deletar",
     "descricao": "Inativar (soft delete) clientes", "categoria": "Cadastro"},
    {"codigo": "clientes.restaurar", "recurso": "Clientes", "acao": "Restaurar",
     "descricao": "Reativar clientes inativados", "categoria": "Cadastro"},

    {"codigo": "contas.visualizar", "recurso": "Contas Bancárias", "acao": "Visualizar",
     "descricao": "Listar contas bancárias dos clientes", "categoria": "Cadastro"},
    {"codigo": "contas.criar", "recurso": "Contas Bancárias", "acao": "Criar",
     "descricao": "Adicionar contas bancárias a clientes", "categoria": "Cadastro"},
    {"codigo": "contas.editar", "recurso": "Contas Bancárias", "acao": "Editar",
     "descricao": "Alterar contas bancárias", "categoria": "Cadastro"},
    {"codigo": "contas.deletar", "recurso": "Contas Bancárias", "acao": "Deletar",
     "descricao": "Remover contas bancárias", "categoria": "Cadastro"},

    {"codigo": "representantes.visualizar", "recurso": "Representantes", "acao": "Visualizar",
     "descricao": "Listar representantes legais", "categoria": "Cadastro"},
    {"codigo": "representantes.criar", "recurso": "Representantes", "acao": "Criar",
     "descricao": "Cadastrar representantes", "categoria": "Cadastro"},
    {"codigo": "representantes.editar", "recurso": "Representantes", "acao": "Editar",
     "descricao": "Alterar dados de representantes", "categoria": "Cadastro"},
    {"codigo": "representantes.deletar", "recurso": "Representantes", "acao": "Deletar",
     "descricao": "Remover representantes", "categoria": "Cadastro"},

    {"codigo": "conta_reu.visualizar", "recurso": "Bancos Réus", "acao": "Visualizar",
     "descricao": "Listar contas de réus", "categoria": "Cadastro"},
    {"codigo": "conta_reu.criar", "recurso": "Bancos Réus", "acao": "Criar",
     "descricao": "Cadastrar contas de réus", "categoria": "Cadastro"},
    {"codigo": "conta_reu.editar", "recurso": "Bancos Réus", "acao": "Editar",
     "descricao": "Alterar contas de réus", "categoria": "Cadastro"},
    {"codigo": "conta_reu.deletar", "recurso": "Bancos Réus", "acao": "Deletar",
     "descricao": "Remover contas de réus", "categoria": "Cadastro"},

    # ===================== Documentos =====================
    {"codigo": "templates.visualizar", "recurso": "Templates", "acao": "Visualizar",
     "descricao": "Listar templates de documentos", "categoria": "Documentos"},
    {"codigo": "templates.criar", "recurso": "Templates", "acao": "Criar",
     "descricao": "Subir novos templates .docx", "categoria": "Documentos"},
    {"codigo": "templates.editar", "recurso": "Templates", "acao": "Editar",
     "descricao": "Alterar templates existentes", "categoria": "Documentos"},
    {"codigo": "templates.deletar", "recurso": "Templates", "acao": "Deletar",
     "descricao": "Remover templates", "categoria": "Documentos"},
    {"codigo": "templates.renderizar", "recurso": "Templates", "acao": "Renderizar",
     "descricao": "Gerar .docx a partir de um template", "categoria": "Documentos"},

    {"codigo": "peticoes.visualizar", "recurso": "Petições", "acao": "Visualizar",
     "descricao": "Listar e ver petições", "categoria": "Documentos"},
    {"codigo": "peticoes.criar", "recurso": "Petições", "acao": "Criar",
     "descricao": "Cadastrar novas petições", "categoria": "Documentos"},
    {"codigo": "peticoes.editar", "recurso": "Petições", "acao": "Editar",
     "descricao": "Alterar petições existentes", "categoria": "Documentos"},
    {"codigo": "peticoes.deletar", "recurso": "Petições", "acao": "Deletar",
     "descricao": "Remover petições", "categoria": "Documentos"},
    {"codigo": "peticoes.renderizar", "recurso": "Petições", "acao": "Renderizar",
     "descricao": "Gerar .docx da petição", "categoria": "Documentos"},

    {"codigo": "contratos.visualizar", "recurso": "Contratos", "acao": "Visualizar",
     "descricao": "Listar contratos", "categoria": "Documentos"},
    {"codigo": "contratos.criar", "recurso": "Contratos", "acao": "Criar",
     "descricao": "Cadastrar contratos", "categoria": "Documentos"},
    {"codigo": "contratos.editar", "recurso": "Contratos", "acao": "Editar",
     "descricao": "Alterar contratos", "categoria": "Documentos"},
    {"codigo": "contratos.deletar", "recurso": "Contratos", "acao": "Deletar",
     "descricao": "Remover contratos", "categoria": "Documentos"},

    {"codigo": "kits.visualizar", "recurso": "Produção de Kits", "acao": "Visualizar",
     "descricao": "Listar kits de produção", "categoria": "Documentos"},
    {"codigo": "kits.criar", "recurso": "Produção de Kits", "acao": "Criar",
     "descricao": "Criar novos kits", "categoria": "Documentos"},
    {"codigo": "kits.editar", "recurso": "Produção de Kits", "acao": "Editar",
     "descricao": "Alterar kits existentes", "categoria": "Documentos"},
    {"codigo": "kits.deletar", "recurso": "Produção de Kits", "acao": "Deletar",
     "descricao": "Remover kits", "categoria": "Documentos"},

    # ===================== Sistema =====================
    {"codigo": "bancos_tarifas.visualizar", "recurso": "Bancos e Tarifas", "acao": "Visualizar",
     "descricao": "Consultar descrições de bancos e tarifas", "categoria": "Sistema"},
    {"codigo": "bancos_tarifas.criar", "recurso": "Bancos e Tarifas", "acao": "Criar",
     "descricao": "Cadastrar descrições/tarifas de bancos", "categoria": "Sistema"},
    {"codigo": "bancos_tarifas.editar", "recurso": "Bancos e Tarifas", "acao": "Editar",
     "descricao": "Alterar descrições/tarifas", "categoria": "Sistema"},
    {"codigo": "bancos_tarifas.deletar", "recurso": "Bancos e Tarifas", "acao": "Deletar",
     "descricao": "Remover descrições/tarifas", "categoria": "Sistema"},
    {"codigo": "bancos_tarifas.ativar", "recurso": "Bancos e Tarifas", "acao": "Ativar",
     "descricao": "Marcar descrição como ativa (set-ativa)", "categoria": "Sistema"},

    {"codigo": "advogados.visualizar", "recurso": "Advogados", "acao": "Visualizar",
     "descricao": "Listar advogados", "categoria": "Sistema"},
    {"codigo": "advogados.criar", "recurso": "Advogados", "acao": "Criar",
     "descricao": "Cadastrar advogados", "categoria": "Sistema"},
    {"codigo": "advogados.editar", "recurso": "Advogados", "acao": "Editar",
     "descricao": "Alterar advogados", "categoria": "Sistema"},
    {"codigo": "advogados.deletar", "recurso": "Advogados", "acao": "Deletar",
     "descricao": "Remover advogados", "categoria": "Sistema"},

    {"codigo": "relatorios.visualizar", "recurso": "Relatórios", "acao": "Visualizar",
     "descricao": "Acessar dashboards e séries temporais", "categoria": "Sistema"},
    {"codigo": "relatorios.exportar", "recurso": "Relatórios", "acao": "Exportar",
     "descricao": "Baixar exports CSV de petições", "categoria": "Sistema"},

    {"codigo": "usuarios.visualizar", "recurso": "Usuários", "acao": "Visualizar",
     "descricao": "Listar usuários do sistema", "categoria": "Sistema"},
    {"codigo": "usuarios.criar", "recurso": "Usuários", "acao": "Criar",
     "descricao": "Criar novos usuários", "categoria": "Sistema"},
    {"codigo": "usuarios.editar", "recurso": "Usuários", "acao": "Editar",
     "descricao": "Alterar usuários (incluindo senha)", "categoria": "Sistema"},
    {"codigo": "usuarios.deletar", "recurso": "Usuários", "acao": "Deletar",
     "descricao": "Remover usuários", "categoria": "Sistema"},

    {"codigo": "permissoes.visualizar", "recurso": "Permissões", "acao": "Visualizar",
     "descricao": "Ver permissões cadastradas e o catálogo de capacidades", "categoria": "Sistema"},
    {"codigo": "permissoes.criar", "recurso": "Permissões", "acao": "Criar",
     "descricao": "Criar novas permissões (perfis)", "categoria": "Sistema"},
    {"codigo": "permissoes.editar", "recurso": "Permissões", "acao": "Editar",
     "descricao": "Alterar permissões existentes", "categoria": "Sistema"},
    {"codigo": "permissoes.deletar", "recurso": "Permissões", "acao": "Deletar",
     "descricao": "Remover permissões", "categoria": "Sistema"},

    # ===================== Acesso a páginas =====================
    # Gate de UI: controla se o usuário PODE ABRIR a página no frontend.
    # Independente das capacidades de dados (<recurso>.visualizar/criar/...),
    # que continuam gateando os endpoints REST. Isso permite, por exemplo,
    # dar a um operador de kits o direito de ler/criar clientes dentro do
    # fluxo de kits sem expor a página standalone de Clientes.
    {"codigo": "pagina.clientes", "recurso": "Página Clientes", "acao": "Acessar",
     "descricao": "Abrir a página de Clientes", "categoria": "Acesso a páginas"},
    {"codigo": "pagina.contas", "recurso": "Página Contas Bancárias", "acao": "Acessar",
     "descricao": "Abrir a página de contas bancárias do cliente", "categoria": "Acesso a páginas"},
    {"codigo": "pagina.conta_reu", "recurso": "Página Bancos Réus", "acao": "Acessar",
     "descricao": "Abrir a página de Bancos Réus", "categoria": "Acesso a páginas"},
    {"codigo": "pagina.templates", "recurso": "Página Templates", "acao": "Acessar",
     "descricao": "Abrir a página de Templates", "categoria": "Acesso a páginas"},
    {"codigo": "pagina.peticoes", "recurso": "Página Petições", "acao": "Acessar",
     "descricao": "Abrir a página de Petições", "categoria": "Acesso a páginas"},
    {"codigo": "pagina.contratos", "recurso": "Página Contratos", "acao": "Acessar",
     "descricao": "Abrir a página de Contratos", "categoria": "Acesso a páginas"},
    {"codigo": "pagina.kits", "recurso": "Página Produção de Kits", "acao": "Acessar",
     "descricao": "Abrir a página de Produção de Kits (lista, novo, editar)", "categoria": "Acesso a páginas"},
    {"codigo": "pagina.bancos_tarifas", "recurso": "Página Bancos e Tarifas", "acao": "Acessar",
     "descricao": "Abrir a página de Bancos e Tarifas", "categoria": "Acesso a páginas"},
    {"codigo": "pagina.advogados", "recurso": "Página Advogados", "acao": "Acessar",
     "descricao": "Abrir a página de Advogados", "categoria": "Acesso a páginas"},
    {"codigo": "pagina.relatorios", "recurso": "Página Relatórios", "acao": "Acessar",
     "descricao": "Abrir a página de Relatórios", "categoria": "Acesso a páginas"},
    {"codigo": "pagina.usuarios", "recurso": "Página Usuários", "acao": "Acessar",
     "descricao": "Abrir a página de Usuários", "categoria": "Acesso a páginas"},
    {"codigo": "pagina.permissoes", "recurso": "Página Permissões", "acao": "Acessar",
     "descricao": "Abrir a página de Permissões", "categoria": "Acesso a páginas"},
]

"""Testes do funil de assinatura e do ciclo da esteira.

MEDIA_ROOT vai para um diretório temporário: os testes gravam arquivos de
verdade (FileField) e não podem sujar o media de desenvolvimento.
"""
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from cadastro.models import Cliente
from kits.models import DocumentoKit, Kit
from kits.services_esteira import (
    assumir_na_esteira,
    documentos_presenciais,
    marcar_assinado,
    marcar_concluido,
    remover_documento_presencial,
    salvar_documentos_presenciais,
    tem_prova_de_assinatura,
)

_MEDIA_TEMP = tempfile.mkdtemp(prefix="jurisdoc-testes-")


class MediaIsoladaTestCase(TestCase):
    """Base que joga os uploads dos testes num diretório temporário."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TEMP, ignore_errors=True)
        super().tearDownClass()


@override_settings(MEDIA_ROOT=_MEDIA_TEMP)
class EsteiraServiceTests(MediaIsoladaTestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="op", password="x")
        self.cliente = Cliente.objects.create(nome_completo="Fulano de Tal", cpf="52998224725")
        self.kit = Kit.objects.create(cliente=self.cliente, criado_por=self.user, status="finalizado")

    def test_kit_nasce_em_producao(self):
        self.assertEqual(self.kit.status_esteira, "em_producao")
        self.assertIsNone(self.kit.entrou_esteira_em)

    def test_assinar_disponibiliza_mas_nao_poe_na_esteira(self):
        """Assinar leva a `aguardando`; quem move dali é a aplicação externa."""
        marcar_assinado(self.kit, via="zapsign")
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status, "assinado")
        self.assertEqual(self.kit.status_esteira, "aguardando")
        self.assertEqual(self.kit.via_assinatura, "zapsign")
        self.assertIsNotNone(self.kit.entrou_esteira_em)
        self.assertIsNone(self.kit.assumido_em)

    def test_assumir_move_de_aguardando_para_na_esteira(self):
        marcar_assinado(self.kit)
        self.assertTrue(assumir_na_esteira(self.kit))
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status_esteira, "na_esteira")
        self.assertIsNotNone(self.kit.assumido_em)

    def test_assumir_duas_vezes_nao_muda_nada(self):
        marcar_assinado(self.kit)
        assumir_na_esteira(self.kit)
        primeiro = self.kit.assumido_em
        self.assertFalse(assumir_na_esteira(self.kit))
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.assumido_em, primeiro)

    def test_assumir_kit_nao_assinado_e_recusado(self):
        self.assertFalse(assumir_na_esteira(self.kit))
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status_esteira, "em_producao")

    def test_baixar_sem_assumir_registra_a_passagem(self):
        """Quem baixa direto ainda deixa registrado quando pegou o kit."""
        marcar_assinado(self.kit)
        self.assertTrue(marcar_concluido(self.kit))
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status_esteira, "concluido")
        self.assertIsNotNone(self.kit.assumido_em)

    def test_download_conclui_e_repeticao_nao_muda(self):
        marcar_assinado(self.kit)
        assumir_na_esteira(self.kit)
        self.assertTrue(marcar_concluido(self.kit))
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status_esteira, "concluido")
        primeiro = self.kit.baixado_em
        # Repetir o download não reconclui nem mexe na data.
        self.assertFalse(marcar_concluido(self.kit))
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.baixado_em, primeiro)

    def test_kit_concluido_nao_volta_para_esteira(self):
        """Webhook repetido do ZapSign não pode ressuscitar um kit já consumido."""
        marcar_assinado(self.kit, via="zapsign")
        assumir_na_esteira(self.kit)
        marcar_concluido(self.kit)
        marcar_assinado(self.kit, via="zapsign")
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status_esteira, "concluido")

    def test_prova_de_assinatura_presencial(self):
        self.assertFalse(tem_prova_de_assinatura(self.kit))
        salvar_documentos_presenciais(
            self.kit, [SimpleUploadedFile("kit.pdf", b"conteudo", content_type="application/pdf")]
        )
        self.assertTrue(tem_prova_de_assinatura(self.kit))

    def test_uploads_acumulam(self):
        """O escritório digitaliza em partes — cada envio soma ao que já existe."""
        salvar_documentos_presenciais(self.kit, [SimpleUploadedFile("a.pdf", b"a")])
        salvar_documentos_presenciais(
            self.kit, [SimpleUploadedFile("b.pdf", b"b"), SimpleUploadedFile("c.pdf", b"c")]
        )
        self.assertEqual(documentos_presenciais(self.kit).count(), 3)

    def test_arquivos_recebem_nome_previsivel_e_nao_colidem(self):
        salvar_documentos_presenciais(
            self.kit,
            [SimpleUploadedFile("digitalizar.pdf", b"1"), SimpleUploadedFile("digitalizar.pdf", b"2")],
        )
        nomes = [d.arquivo.name for d in documentos_presenciais(self.kit)]
        self.assertEqual(len(set(nomes)), 2, nomes)
        self.assertTrue(all(f"kit_{self.kit.id}_assinado_" in n for n in nomes), nomes)

    def test_remover_um_nao_derruba_os_outros(self):
        docs = salvar_documentos_presenciais(
            self.kit, [SimpleUploadedFile("a.pdf", b"a"), SimpleUploadedFile("b.pdf", b"b")]
        )
        self.assertTrue(remover_documento_presencial(self.kit, docs[0].id))
        self.assertEqual(documentos_presenciais(self.kit).count(), 1)

    def test_remover_documento_de_outro_kit_e_recusado(self):
        outro = Kit.objects.create(cliente=self.cliente, criado_por=self.user, status="finalizado")
        docs = salvar_documentos_presenciais(outro, [SimpleUploadedFile("x.pdf", b"x")])
        self.assertFalse(remover_documento_presencial(self.kit, docs[0].id))

    def test_prova_nao_entra_na_lista_de_pecas_a_assinar(self):
        DocumentoKit.objects.create(kit=self.kit, tipo="contrato", arquivo="x.docx")
        salvar_documentos_presenciais(self.kit, [SimpleUploadedFile("k.pdf", b"k")])
        pecas = self.kit.documentos.exclude(tipo__in=DocumentoKit.TIPOS_PROVA)
        self.assertEqual([p.tipo for p in pecas], ["contrato"])


@override_settings(MEDIA_ROOT=_MEDIA_TEMP)
class AssinarEndpointTests(MediaIsoladaTestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="adm", password="x", is_admin=True)
        # A API autentica por JWT: force_authenticate é o equivalente do DRF.
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        cliente = Cliente.objects.create(nome_completo="Beltrano", cpf="15350946056")
        self.kit = Kit.objects.create(cliente=cliente, criado_por=self.user, status="finalizado")

    def test_presencial_sem_digitalizacao_e_recusado(self):
        self.kit.via_assinatura = "presencial"
        self.kit.save()
        r = self.client.post(f"/api/kits/{self.kit.id}/assinar/")
        self.assertEqual(r.status_code, 400)
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status_esteira, "em_producao")

    def test_upload_de_varios_arquivos_de_uma_vez(self):
        r = self.client.post(
            f"/api/kits/{self.kit.id}/documento-assinado/",
            {
                "arquivos": [
                    SimpleUploadedFile("p1.pdf", b"1"),
                    SimpleUploadedFile("p2.pdf", b"2"),
                    SimpleUploadedFile("p3.pdf", b"3"),
                ]
            },
            format="multipart",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(documentos_presenciais(self.kit).count(), 3)

    def test_uploads_sucessivos_acumulam_no_endpoint(self):
        for nome in ("a.pdf", "b.pdf"):
            self.client.post(
                f"/api/kits/{self.kit.id}/documento-assinado/",
                {"arquivos": SimpleUploadedFile(nome, b"x")},
                format="multipart",
            )
        self.assertEqual(documentos_presenciais(self.kit).count(), 2)

    def test_campo_arquivo_no_singular_ainda_funciona(self):
        r = self.client.post(
            f"/api/kits/{self.kit.id}/documento-assinado/",
            {"arquivo": SimpleUploadedFile("unico.pdf", b"x")},
            format="multipart",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(documentos_presenciais(self.kit).count(), 1)

    def test_delete_exige_documento_id(self):
        salvar_documentos_presenciais(self.kit, [SimpleUploadedFile("a.pdf", b"a")])
        r = self.client.delete(f"/api/kits/{self.kit.id}/documento-assinado/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(documentos_presenciais(self.kit).count(), 1)

    def test_delete_remove_apenas_o_indicado(self):
        docs = salvar_documentos_presenciais(
            self.kit, [SimpleUploadedFile("a.pdf", b"a"), SimpleUploadedFile("b.pdf", b"b")]
        )
        r = self.client.delete(
            f"/api/kits/{self.kit.id}/documento-assinado/?documento_id={docs[0].id}"
        )
        self.assertEqual(r.status_code, 200)
        restantes = [d.id for d in documentos_presenciais(self.kit)]
        self.assertEqual(restantes, [docs[1].id])

    def test_presencial_com_digitalizacao_assina(self):
        self.kit.via_assinatura = "presencial"
        self.kit.save()
        salvar_documentos_presenciais(self.kit, [SimpleUploadedFile("k.pdf", b"k")])
        r = self.client.post(f"/api/kits/{self.kit.id}/assinar/")
        self.assertEqual(r.status_code, 200)
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status_esteira, "aguardando")


@override_settings(MEDIA_ROOT=_MEDIA_TEMP)
class EsteiraAPITests(MediaIsoladaTestCase):
    """Contrato com a aplicação externa (Client Credentials)."""

    def setUp(self):
        from accounts.service_auth import issue_service_token

        User = get_user_model()
        user = User.objects.create_user(username="op2", password="x")
        cliente = Cliente.objects.create(nome_completo="Ciclana Silva", cpf="11144477735")
        self.kit = Kit.objects.create(cliente=cliente, criado_por=user, status="finalizado")
        salvar_documentos_presenciais(
            self.kit,
            [
                SimpleUploadedFile("kit.pdf", b"%PDF-1.4 parte 1", content_type="application/pdf"),
                SimpleUploadedFile("kit.pdf", b"%PDF-1.4 parte 2", content_type="application/pdf"),
            ],
        )
        marcar_assinado(self.kit, via="presencial")

        self.client = APIClient()
        token = issue_service_token("app-esteira")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_sem_token_bloqueia(self):
        anon = APIClient()
        self.assertEqual(anon.get("/api/app/esteira/").status_code, 401)

    def test_lista_traz_os_kits_aguardando(self):
        r = self.client.get("/api/app/esteira/")
        self.assertEqual(r.status_code, 200)
        ids = [k["id"] for k in r.data["results"]]
        self.assertIn(self.kit.id, ids)

    def test_lista_esconde_concluidos_por_padrao(self):
        assumir_na_esteira(self.kit)
        marcar_concluido(self.kit)
        r = self.client.get("/api/app/esteira/")
        self.assertEqual([k["id"] for k in r.data["results"]], [])
        # Mas continuam visíveis quando pedidos explicitamente.
        r2 = self.client.get("/api/app/esteira/?status_esteira=concluido")
        self.assertEqual([k["id"] for k in r2.data["results"]], [self.kit.id])

    def test_detalhe_nao_expoe_honorarios(self):
        r = self.client.get(f"/api/app/esteira/{self.kit.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("honorarios_iniciais", r.data)

    def test_download_entrega_zip_e_conclui(self):
        import io, zipfile

        r = self.client.get(f"/api/app/esteira/{self.kit.id}/download/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/zip")

        nomes = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        self.assertTrue(any(n.startswith("assinados/") for n in nomes), nomes)

        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status_esteira, "concluido")
        self.assertIsNotNone(self.kit.baixado_em)

    def test_zip_nao_perde_arquivos_de_mesmo_nome(self):
        """Duas digitalizações vindas do scanner como 'kit.pdf' precisam coexistir."""
        import io, zipfile

        r = self.client.get(f"/api/app/esteira/{self.kit.id}/download/")
        nomes = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        assinados = [n for n in nomes if n.startswith("assinados/")]
        self.assertEqual(len(assinados), 2, nomes)
        self.assertEqual(len(set(assinados)), 2, nomes)
        self.assertEqual(r["X-Esteira-Arquivos"], "2")

    def test_download_repetido_continua_funcionando(self):
        self.client.get(f"/api/app/esteira/{self.kit.id}/download/")
        r = self.client.get(f"/api/app/esteira/{self.kit.id}/download/")
        self.assertEqual(r.status_code, 200)

    def test_header_de_conteudo_desconhecido_e_recusado(self):
        r = self.client.get(
            f"/api/app/esteira/{self.kit.id}/download/",
            HTTP_X_ESTEIRA_CONTEUDO="assinados,inventado",
        )
        self.assertEqual(r.status_code, 400)
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status_esteira, "aguardando")

    def test_query_param_incluir_equivale_ao_header(self):
        r = self.client.get(f"/api/app/esteira/{self.kit.id}/download/?incluir=assinados")
        self.assertEqual(r.status_code, 200)

    def test_conteudo_sem_arquivo_devolve_404_e_nao_conclui(self):
        r = self.client.get(
            f"/api/app/esteira/{self.kit.id}/download/", HTTP_X_ESTEIRA_CONTEUDO="anexos"
        )
        self.assertEqual(r.status_code, 404)
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status_esteira, "aguardando")

    def test_assumir_pelo_endpoint(self):
        r = self.client.post(f"/api/app/esteira/{self.kit.id}/assumir/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["alterado"])
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status_esteira, "na_esteira")
        self.assertIsNotNone(self.kit.assumido_em)

    def test_kits_em_producao_nao_aparecem_na_api(self):
        """Kit não assinado não existe para a aplicação externa."""
        outro = Kit.objects.create(
            cliente=self.kit.cliente, criado_por=self.kit.criado_por, status="finalizado"
        )
        r = self.client.get(f"/api/app/esteira/{outro.id}/")
        self.assertEqual(r.status_code, 404)

    def test_concluir_explicito(self):
        r = self.client.post(f"/api/app/esteira/{self.kit.id}/concluir/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["alterado"])
        self.kit.refresh_from_db()
        self.assertEqual(self.kit.status_esteira, "concluido")


@override_settings(MEDIA_ROOT=_MEDIA_TEMP)
class LimpezaDeArquivosTests(MediaIsoladaTestCase):
    """Nenhum caminho de remoção pode deixar arquivo órfão no MEDIA_ROOT."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="op3", password="x")
        self.cliente = Cliente.objects.create(nome_completo="Órfão Teste", cpf="27267372035")
        self.kit = Kit.objects.create(cliente=self.cliente, criado_por=self.user, status="finalizado")

    def _existe(self, doc):
        return default_storage.exists(doc.arquivo.name)

    def test_remover_digitalizacao_apaga_o_arquivo(self):
        """O caso do dia a dia: anexou o documento errado e tirou."""
        with self.captureOnCommitCallbacks(execute=True):
            docs = salvar_documentos_presenciais(
                self.kit, [SimpleUploadedFile("errado.pdf", b"errado")]
            )
        caminho = docs[0].arquivo.name
        self.assertTrue(default_storage.exists(caminho))

        with self.captureOnCommitCallbacks(execute=True):
            remover_documento_presencial(self.kit, docs[0].id)

        self.assertFalse(default_storage.exists(caminho), "arquivo ficou órfão no disco")

    def test_remover_um_nao_apaga_o_arquivo_dos_outros(self):
        with self.captureOnCommitCallbacks(execute=True):
            docs = salvar_documentos_presenciais(
                self.kit, [SimpleUploadedFile("a.pdf", b"a"), SimpleUploadedFile("b.pdf", b"b")]
            )
        manter = docs[1].arquivo.name

        with self.captureOnCommitCallbacks(execute=True):
            remover_documento_presencial(self.kit, docs[0].id)

        self.assertTrue(default_storage.exists(manter))

    def test_excluir_kit_leva_os_arquivos_junto(self):
        """CASCADE apaga as linhas; sem o signal os arquivos ficariam para trás."""
        with self.captureOnCommitCallbacks(execute=True):
            docs = salvar_documentos_presenciais(
                self.kit, [SimpleUploadedFile("x.pdf", b"x"), SimpleUploadedFile("y.pdf", b"y")]
            )
        caminhos = [d.arquivo.name for d in docs]

        with self.captureOnCommitCallbacks(execute=True):
            self.kit.delete()

        for caminho in caminhos:
            self.assertFalse(default_storage.exists(caminho), f"órfão: {caminho}")

    def test_queryset_delete_tambem_limpa(self):
        """post_delete cobre queryset.delete(), que nem chama Model.delete()."""
        with self.captureOnCommitCallbacks(execute=True):
            docs = salvar_documentos_presenciais(self.kit, [SimpleUploadedFile("q.pdf", b"q")])
        caminho = docs[0].arquivo.name

        with self.captureOnCommitCallbacks(execute=True):
            DocumentoKit.objects.filter(pk=docs[0].pk).delete()

        self.assertFalse(default_storage.exists(caminho))

    def test_rollback_nao_apaga_o_arquivo(self):
        """Se a transação da remoção não efetivar, o arquivo tem de continuar lá."""
        from django.db import transaction

        with self.captureOnCommitCallbacks(execute=True):
            docs = salvar_documentos_presenciais(self.kit, [SimpleUploadedFile("r.pdf", b"r")])
        caminho = docs[0].arquivo.name

        try:
            with transaction.atomic():
                remover_documento_presencial(self.kit, docs[0].id)
                raise RuntimeError("falha simulada depois da remoção")
        except RuntimeError:
            pass

        self.assertTrue(default_storage.exists(caminho))
        self.assertTrue(DocumentoKit.objects.filter(pk=docs[0].pk).exists())

    def test_regerar_documentos_preserva_a_prova_de_assinatura(self):
        """Regerar as peças não pode destruir a digitalização já assinada."""
        from kits.services_documentos import gerar_documentos_kit

        DocumentoKit.objects.create(kit=self.kit, tipo="contrato", arquivo="kits/documentos/velho.docx")
        with self.captureOnCommitCallbacks(execute=True):
            salvar_documentos_presenciais(self.kit, [SimpleUploadedFile("prova.pdf", b"prova")])

        with self.captureOnCommitCallbacks(execute=True):
            try:
                gerar_documentos_kit(self.kit)
            except Exception:
                # Sem templates .docx cadastrados a geração falha — o que importa
                # aqui é o que aconteceu com a prova antes disso.
                pass

        self.assertEqual(documentos_presenciais(self.kit).count(), 1)

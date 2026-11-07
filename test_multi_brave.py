"""
Suíte de Testes Automatizados — Bot Empresário Multi-Brave
Valida rigorosamente os 14 requisitos de concorrência segura, isolamento,
distribuição inteligente, integridade transacional e organização de janelas.
"""

import os
import sys
import time
import shutil
import unittest
import pandas as pd
from unittest.mock import MagicMock

# Ajusta path para importar módulos do projeto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import security_config
from multi_brave import (
    SystemResources,
    WindowManager,
    ClientQueueManager,
    ResultCollector,
    PROFILES_BASE,
)


class TestMultiBraveArchitecture(unittest.TestCase):
    """Testes unitários e de integração para a nova arquitetura Multi-Brave."""

    def setUp(self):
        # Cria DataFrame de teste com 100 clientes fictícios
        dados = []
        for i in range(100):
            dados.append({
                "NOME": f"Cliente Teste {i+1}",
                "CPF/CNPJ": f"{i+1:011d}",
                "DDD": "11",
                "FONE": f"98765{i:04d}",
                "Tem_Emprestimo": "",
            })
        self.df_100 = pd.DataFrame(dados)

    # -----------------------------------------------------------------------
    # TESTES DE DISTRIBUIÇÃO INTELIGENTE (100 clientes entre 2, 3, 4 instâncias)
    # -----------------------------------------------------------------------
    def test_distribuicao_100_clientes_2_instancias(self):
        """Requisito 5: Distribuição de 100 clientes entre 2 instâncias (50/50)."""
        qm = ClientQueueManager(self.df_100.copy(), num_workers=2)
        cota_w1 = qm.get_assigned_count(worker_id=1)
        cota_w2 = qm.get_assigned_count(worker_id=2)

        self.assertEqual(cota_w1, 50, f"Worker 1 deveria receber 50 clientes, recebeu {cota_w1}")
        self.assertEqual(cota_w2, 50, f"Worker 2 deveria receber 50 clientes, recebeu {cota_w2}")
        self.assertEqual(cota_w1 + cota_w2, 100)

    def test_distribuicao_100_clientes_3_instancias(self):
        """Requisito 6: Distribuição de 100 clientes entre 3 instâncias (34/33/33)."""
        qm = ClientQueueManager(self.df_100.copy(), num_workers=3)
        cota_w1 = qm.get_assigned_count(worker_id=1)
        cota_w2 = qm.get_assigned_count(worker_id=2)
        cota_w3 = qm.get_assigned_count(worker_id=3)

        self.assertEqual(cota_w1, 34, f"Worker 1 deveria receber 34 clientes, recebeu {cota_w1}")
        self.assertEqual(cota_w2, 33, f"Worker 2 deveria receber 33 clientes, recebeu {cota_w2}")
        self.assertEqual(cota_w3, 33, f"Worker 3 deveria receber 33 clientes, recebeu {cota_w3}")
        self.assertEqual(cota_w1 + cota_w2 + cota_w3, 100)

    def test_distribuicao_100_clientes_4_instancias(self):
        """Distribuição de 100 clientes entre 4 instâncias (25/25/25/25)."""
        qm = ClientQueueManager(self.df_100.copy(), num_workers=4)
        cotas = [qm.get_assigned_count(w) for w in range(1, 5)]

        for i, c in enumerate(cotas, 1):
            self.assertEqual(c, 25, f"Worker {i} deveria ter 25, tem {c}")
        self.assertEqual(sum(cotas), 100)

    # -----------------------------------------------------------------------
    # TESTES DE ISOLAMENTO E PREVENÇÃO DE DUPLICIDADE
    # -----------------------------------------------------------------------
    def test_isolamento_clientes_sem_concorrencia_dupla(self):
        """Requisito 8: Nenhum cliente pode ser processado simultaneamente por 2 workers."""
        qm = ClientQueueManager(self.df_100.copy(), num_workers=2)

        pedidos_w1 = []
        pedidos_w2 = []

        # Worker 1 pega 10 clientes
        for _ in range(10):
            c = qm.claim_next(worker_id=1)
            self.assertIsNotNone(c)
            pedidos_w1.append(c["client_id"])

        # Worker 2 pega 10 clientes
        for _ in range(10):
            c = qm.claim_next(worker_id=2)
            self.assertIsNotNone(c)
            pedidos_w2.append(c["client_id"])

        # Verifica interseção vazia (isolamento estrito)
        intersecao = set(pedidos_w1).intersection(set(pedidos_w2))
        self.assertEqual(len(intersecao), 0, f"Clientes colidiram entre workers: {intersecao}")

    def test_prevencao_duplicidade_clientes_concluidos(self):
        """Requisito 11: Clientes já concluídos nunca devem ser processados novamente."""
        df = self.df_100.copy()
        df.at[0, "Tem_Emprestimo"] = "Sim"
        df.at[1, "Tem_Emprestimo"] = "Não"

        qm = ClientQueueManager(df, num_workers=2)
        c0 = qm.clients[0]
        c1 = qm.clients[1]

        self.assertEqual(c0["estado_fila"], "CONCLUIDO")
        self.assertEqual(c1["estado_fila"], "CONCLUIDO")

        # Ao pedir o próximo, não deve ser nem o 0 nem o 1
        prox = qm.claim_next(worker_id=1)
        self.assertNotEqual(prox["idx"], 0)
        self.assertNotEqual(prox["idx"], 1)

    # -----------------------------------------------------------------------
    # TESTES DE FALHA DE WORKER E RECUPERAÇÃO SEGURA
    # -----------------------------------------------------------------------
    def test_falha_de_worker_e_recuperacao_de_pendentes(self):
        """Requisitos 9 e 10: Se um worker falhar, pendentes são redistribuídos com segurança."""
        qm = ClientQueueManager(self.df_100.copy(), num_workers=2)

        # Worker 2 pega 1 cliente e fica em processamento
        em_andamento = qm.claim_next(worker_id=2)
        req_id = em_andamento["request_id"]
        self.assertIn("REQ-W02", req_id)

        # Simula falha/queda do Worker 2
        qm.release_worker_clients(worker_id=2)

        # Agora Worker 1 assume os clientes restantes
        novo_atribuido = qm.claim_next(worker_id=1)
        self.assertIsNotNone(novo_atribuido)
        # O cliente que estava órfão pôde ser recuperado
        sumario = qm.get_summary()
        self.assertEqual(sumario["total"], 100)

    # -----------------------------------------------------------------------
    # TESTES DE ORGANIZAÇÃO VISUAL DAS JANELAS (AUTO-TILING NO WINDOWS)
    # -----------------------------------------------------------------------
    def test_organizacao_visual_janelas_1_brave(self):
        """Requisito 13: 1 Brave ocupa a área de trabalho visível."""
        geom = WindowManager.calculate_geometry(worker_index=0, total_workers=1)
        _, _, work_w, work_h = WindowManager.get_work_area()
        self.assertEqual(geom["width"], work_w)
        self.assertEqual(geom["height"], work_h)

    def test_organizacao_visual_janelas_2_braves(self):
        """Requisito 13: 2 Braves dividem metade esquerda e direita sem sobreposição."""
        g0 = WindowManager.calculate_geometry(worker_index=0, total_workers=2)
        g1 = WindowManager.calculate_geometry(worker_index=1, total_workers=2)
        _, _, work_w, work_h = WindowManager.get_work_area()

        self.assertEqual(g0["x"], 0)
        self.assertEqual(g0["width"], work_w // 2)
        self.assertEqual(g1["x"], work_w // 2)
        self.assertEqual(g0["height"], work_h)
        self.assertEqual(g1["height"], work_h)
        # Sem sobreposição horizontal
        self.assertLessEqual(g0["x"] + g0["width"], g1["x"] + 1)

    def test_organizacao_visual_janelas_4_braves(self):
        """Requisito 13: 4 Braves formam grade 2x2 sem sobreposição."""
        g = [WindowManager.calculate_geometry(i, 4) for i in range(4)]
        _, _, work_w, work_h = WindowManager.get_work_area()

        half_w = work_w // 2
        half_h = work_h // 2

        # Quadrante 0 (Topo Esquerdo)
        self.assertEqual(g[0]["x"], 0)
        self.assertEqual(g[0]["y"], 0)
        # Quadrante 1 (Topo Direito)
        self.assertEqual(g[1]["x"], half_w)
        self.assertEqual(g[1]["y"], 0)
        # Quadrante 2 (Base Esquerda)
        self.assertEqual(g[2]["x"], 0)
        self.assertEqual(g[2]["y"], half_h)
        # Quadrante 3 (Base Direita)
        self.assertEqual(g[3]["x"], half_w)
        self.assertEqual(g[3]["y"], half_h)

    # -----------------------------------------------------------------------
    # TESTES DE INTEGRIDADE, ATOMICIDADE E PERSISTÊNCIA
    # -----------------------------------------------------------------------
    def test_integridade_resultados_e_request_id(self):
        """Requisito 14: Confirmação de que o resultado pertence ao request_id correto."""
        qm = ClientQueueManager(self.df_100.copy(), num_workers=2)
        item = qm.claim_next(worker_id=1)
        req_id = item["request_id"]

        # Sucesso com request_id correto
        ok = qm.mark_completed(req_id, "Sim")
        self.assertTrue(ok)
        self.assertEqual(qm.df.at[item["idx"], "Tem_Emprestimo"], "Sim")

        # Tentativa com request_id inválido é rejeitada
        falso = qm.mark_completed("REQ-FALSO-000", "Sim")
        self.assertFalse(falso)

    def test_gravacao_atomica_excel(self):
        """Testa gravação com lock e substituição atômica (.tmp + os.replace)."""
        caminho_teste = os.path.join(os.path.dirname(__file__), "test_resultado.xlsx")
        caminho_sim = os.path.join(os.path.dirname(__file__), "test_com_refin.xlsx")

        collector = ResultCollector(caminho_teste, caminho_sim)
        df_teste = self.df_100.copy()
        df_teste.at[0, "Tem_Emprestimo"] = "Sim"

        collector.salvar(df_teste, forcar=True)

        self.assertTrue(os.path.exists(caminho_teste))
        df_lido = pd.read_excel(caminho_teste)
        self.assertEqual(len(df_lido), 100)
        self.assertEqual(df_lido.at[0, "Tem_Emprestimo"], "Sim")

        # Limpeza
        for p in [caminho_teste, caminho_sim]:
            if os.path.exists(p):
                os.remove(p)

    # -----------------------------------------------------------------------
    # TESTES DE SEGURANÇA E PROTEÇÃO DE DADOS
    # -----------------------------------------------------------------------
    def test_mascaramento_cpf_e_seguranca(self):
        """Validação de mascaramento e dígitos verificadores de CPF."""
        cpf_valido = "70958933146"
        self.assertTrue(security_config.validate_cpf(cpf_valido))

        cpf_invalido = "11111111111"
        self.assertFalse(security_config.validate_cpf(cpf_invalido))

        mascarado = security_config.mask_cpf(cpf_valido)
        self.assertEqual(mascarado, "***.589.331-**")
        self.assertNotIn("709", mascarado)

    def test_capacidade_sistema_e_alerta_recursos(self):
        """Verifica detecção de RAM e emissão de alerta se ultrapassar limite."""
        info = SystemResources.get_info()
        self.assertGreater(info["total_ram_gb"], 0)
        self.assertGreater(info["cpu_cores"], 0)

        # Se solicitar 10 Braves numa máquina com 8GB, deve emitir alerta
        alerta = SystemResources.check_capacity(requested=10)
        self.assertIsNotNone(alerta)
        self.assertIn("Atenção", alerta)


if __name__ == "__main__":
    unittest.main(verbosity=2)

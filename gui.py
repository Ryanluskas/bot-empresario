"""
Interface gráfica — Bot Santander (Novo Design com Gerenciamento Multi-Brave)
"""
import os
import time
import logging
import threading
import tkinter as tk
from tkinter import ttk, filedialog
import customtkinter as ctk
from datetime import datetime

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

import bot_santander as bot
import security_config
from multi_brave import SystemResources

# Paleta de cores
C_BG    = "#141414"
C_CARD  = "#1e1e1e"
C_CARD2 = "#252525"
C_BORDER= "#2e2e2e"
C_TEXT  = "#e8e8e8"
C_TEXT2 = "#888888"
C_TEXT3 = "#444444"
C_RED   = "#CC0000"
C_RED2  = "#a80000"
C_GREEN = "#3A9D5C"
C_AMBER = "#C18A1A"
C_ERR   = "#C0392B"
C_BLUE  = "#1A5FA8"


class BotApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Bot Santander — Multi-Brave")
        self.geometry("1260x900")
        self.minsize(1120, 780)
        self.configure(fg_color=C_BG)

        self._running  = False
        self._inicio   = None
        self._proc_sess = 0
        self._dot_on   = True
        self._dot_color = C_TEXT3
        self._dot_anim  = False
        self._session_start = datetime.now().strftime("%H:%M")

        # Configurações Multi-Brave
        self._braves_count = 1
        self._coord_holder = []
        self._workers_data = {}
        self._sys_info = SystemResources.get_info()


        self._build_ui()
        self._poll()
        self._animate_dot()

    # ───────────────────────────── BUILD ─────────────────────────────────────
    def _build_ui(self):
        self._build_header()

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=(10, 0))

        self._build_metrics(content)
        self._build_controls(content)

        # Two-column area
        two = ctk.CTkFrame(content, fg_color="transparent")
        two.pack(fill="both", expand=True, pady=(0, 8))

        left = ctk.CTkFrame(two, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        right = ctk.CTkFrame(two, width=320, fg_color="transparent")
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        # Seção de Gerenciamento de Instâncias + Tabela de Clientes no lado esquerdo
        self._build_instances_section(left)
        self._build_table(left)

        # Configurações e Carregamento no lado direito
        self._build_right(right)

        # Logs e barra inferior
        self._build_log(content)
        self._build_bottom()

    def _build_header(self):
        hdr = ctk.CTkFrame(self, height=58, fg_color=C_CARD, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        lft = ctk.CTkFrame(hdr, fg_color="transparent")
        lft.pack(side="left", padx=16, pady=10)

        badge = ctk.CTkFrame(lft, width=36, height=36, fg_color=C_RED, corner_radius=8)
        badge.pack(side="left", padx=(0, 10))
        badge.pack_propagate(False)
        ctk.CTkLabel(badge, text="STB",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="#fff").place(relx=0.5, rely=0.5, anchor="center")

        tblock = ctk.CTkFrame(lft, fg_color="transparent")
        tblock.pack(side="left")
        ctk.CTkLabel(tblock,
                     text="Bot Santander  —  Automação Multi-Brave",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C_TEXT).pack(anchor="w")
        ctk.CTkLabel(tblock,
                     text=f"Parceiro Santander · Sessão iniciada {self._session_start}",
                     font=ctk.CTkFont(size=11),
                     text_color=C_TEXT2).pack(anchor="w")

        rgt = ctk.CTkFrame(hdr, fg_color="transparent")
        rgt.pack(side="right", padx=16)

        pill = ctk.CTkFrame(rgt, fg_color=C_CARD2, corner_radius=99,
                             border_color=C_BORDER, border_width=1)
        pill.pack(side="right")

        self._dot_cv = tk.Canvas(pill, width=10, height=10,
                                  bg=C_CARD2, highlightthickness=0)
        self._dot_cv.pack(side="left", padx=(10, 4), pady=8)
        self._dot_id = self._dot_cv.create_oval(1, 1, 9, 9, fill=C_TEXT3, outline="")

        self._lbl_status = ctk.CTkLabel(pill, text="Parado",
                                         font=ctk.CTkFont(size=12),
                                         text_color=C_TEXT2)
        self._lbl_status.pack(side="left", padx=(0, 12), pady=8)

    def _build_metrics(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 10))
        for i in range(4):
            row.columnconfigure(i, weight=1)

        specs = [
            ("total",  "TOTAL NA LISTA",    C_TEXT,   "clientes carregados"),
            ("feitos", "PROCESSADOS",        C_GREEN,  "—"),
            ("erros",  "ERROS",              C_ERR,    "CPF inválido / timeout"),
            ("otp",    "AGUARDANDO OTP",     C_AMBER,  "aguardando código SMS"),
        ]
        self._mv  = {}
        self._msv = {}
        for i, (k, lbl, clr, sub) in enumerate(specs):
            pad_left = 6 if i > 0 else 0
            card = ctk.CTkFrame(row, fg_color=C_CARD, corner_radius=10,
                                 border_color=C_BORDER, border_width=1)
            card.grid(row=0, column=i, padx=(pad_left, 0), sticky="ew", ipady=2)

            ctk.CTkLabel(card, text=lbl,
                         font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=C_TEXT3).pack(anchor="w", padx=16, pady=(10, 2))

            v = ctk.StringVar(value="—")
            self._mv[k] = v
            ctk.CTkLabel(card, textvariable=v,
                         font=ctk.CTkFont(size=24, weight="bold"),
                         text_color=clr).pack(anchor="w", padx=16)

            sv = ctk.StringVar(value=sub)
            self._msv[k] = sv
            ctk.CTkLabel(card, textvariable=sv,
                         font=ctk.CTkFont(size=11),
                         text_color=C_TEXT2).pack(anchor="w", padx=16, pady=(1, 10))

    def _build_controls(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8))

        self._btn_main = ctk.CTkButton(
            row, text="▶  Iniciar", width=120, height=36,
            fg_color=C_RED, hover_color=C_RED2,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._toggle_run
        )
        self._btn_main.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            row, text="↺  Reprocessar erros", height=36, width=150,
            fg_color=C_CARD, hover_color=C_CARD2,
            border_color=C_BORDER, border_width=1,
            font=ctk.CTkFont(size=12), text_color=C_TEXT,
            command=lambda: self._log_line(
                "INFO", "Reprocessar: reinicie o bot — os clientes com erro serão retomados.")
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            row, text="⬇  Exportar relatório", height=36, width=150,
            fg_color=C_CARD, hover_color=C_CARD2,
            border_color=C_BORDER, border_width=1,
            font=ctk.CTkFont(size=12), text_color=C_TEXT,
            command=self._abrir_resultados
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            row, text="⊞  Reorganizar Janelas", height=36, width=160,
            fg_color=C_CARD, hover_color=C_CARD2,
            border_color=C_BORDER, border_width=1,
            font=ctk.CTkFont(size=12), text_color=C_TEXT,
            command=self._reorganizar_janelas
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            row, text="⏹  Encerrar sessão", height=36, width=140,
            fg_color="transparent", hover_color="#2e1010",
            border_color=C_ERR, border_width=1,
            font=ctk.CTkFont(size=12), text_color=C_ERR,
            command=self._parar
        ).pack(side="right")

    # ──────────────────────── GERENCIAMENTO DE INSTÂNCIAS ───────────────────
    def _build_instances_section(self, parent):
        card = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=10,
                             border_color=C_BORDER, border_width=1)
        card.pack(fill="x", pady=(0, 8))

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(10, 6))

        ctk.CTkLabel(hdr, text="⚡ Gerenciamento de Instâncias",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C_TEXT).pack(side="left")

        self._lbl_inst_resumo = ctk.CTkLabel(
            hdr,
            text=f"Config: {self._braves_count} | Ativos: 0 | Workers: 0 | Pendentes: — | Falhas: 0",
            font=ctk.CTkFont(size=11),
            text_color=C_TEXT2
        )
        self._lbl_inst_resumo.pack(side="right")

        ctk.CTkFrame(card, height=1, fg_color=C_BORDER).pack(fill="x")

        # Treeview de Instâncias
        sty = ttk.Style()
        self._tree_inst = ttk.Treeview(
            card,
            columns=("instancia", "status", "cliente", "etapa", "processados", "erros", "tempo"),
            show="headings",
            style="Bot.Treeview",
            height=3
        )
        self._tree_inst.heading("instancia",   text="Instância")
        self._tree_inst.heading("status",      text="Status")
        self._tree_inst.heading("cliente",     text="Cliente Atual")
        self._tree_inst.heading("etapa",       text="Etapa Atual")
        self._tree_inst.heading("processados", text="Processados")
        self._tree_inst.heading("erros",       text="Erros")
        self._tree_inst.heading("tempo",       text="Tempo")

        self._tree_inst.column("instancia",   width=90,  stretch=False)
        self._tree_inst.column("status",      width=100, stretch=False)
        self._tree_inst.column("cliente",     width=180, stretch=True)
        self._tree_inst.column("etapa",       width=130, stretch=False)
        self._tree_inst.column("processados", width=90,  stretch=False)
        self._tree_inst.column("erros",       width=70,  stretch=False)
        self._tree_inst.column("tempo",       width=75,  stretch=False)

        self._tree_inst.tag_configure("run",  foreground=C_GREEN)
        self._tree_inst.tag_configure("wait", foreground=C_AMBER)
        self._tree_inst.tag_configure("err",  foreground=C_ERR)
        self._tree_inst.tag_configure("off",  foreground=C_TEXT3)

        self._tree_inst.pack(fill="both", expand=True, padx=10, pady=(6, 8))

    def _build_table(self, parent):
        card = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=10,
                             border_color=C_BORDER, border_width=1)
        card.pack(fill="both", expand=True)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(10, 6))
        ctk.CTkLabel(hdr, text="Clientes em processamento",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C_TEXT).pack(side="left")
        self._lbl_vel = ctk.CTkLabel(hdr, text="",
                                      font=ctk.CTkFont(size=11),
                                      text_color=C_TEXT2)
        self._lbl_vel.pack(side="right")

        ctk.CTkFrame(card, height=1, fg_color=C_BORDER).pack(fill="x")

        # Treeview de Clientes
        self._tree = ttk.Treeview(card, columns=("nome","cpf","fone","status"),
                                   show="headings", style="Bot.Treeview", height=5)
        self._tree.heading("nome",   text="Nome")
        self._tree.heading("cpf",    text="CPF / CNPJ")
        self._tree.heading("fone",   text="DDD · Fone")
        self._tree.heading("status", text="Status")
        self._tree.column("nome",   width=220, stretch=True)
        self._tree.column("cpf",    width=150, stretch=False)
        self._tree.column("fone",   width=120, stretch=False)
        self._tree.column("status", width=110, stretch=False)
        self._tree.tag_configure("sim",   foreground=C_GREEN)
        self._tree.tag_configure("nao",   foreground=C_TEXT2)
        self._tree.tag_configure("erro",  foreground=C_ERR)
        self._tree.tag_configure("atual", foreground="#5B9CF6")
        self._tree.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        ctk.CTkFrame(card, height=1, fg_color=C_BORDER).pack(fill="x")

        # Progress section
        pb = ctk.CTkFrame(card, fg_color="transparent")
        pb.pack(fill="x", padx=16, pady=8)

        top = ctk.CTkFrame(pb, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text="Progresso geral",
                     font=ctk.CTkFont(size=11), text_color=C_TEXT2).pack(side="left")
        self._lbl_prog = ctk.CTkLabel(top, text="0 / 0",
                                       font=ctk.CTkFont(size=11), text_color=C_TEXT2)
        self._lbl_prog.pack(side="right")

        self._prog = ctk.CTkProgressBar(pb, height=5,
                                         progress_color=C_RED, fg_color=C_CARD2)
        self._prog.set(0)
        self._prog.pack(fill="x", pady=(4, 0))

        bot_row = ctk.CTkFrame(pb, fg_color="transparent")
        bot_row.pack(fill="x", pady=(2, 0))
        self._lbl_sim_cnt = ctk.CTkLabel(bot_row, text="",
                                          font=ctk.CTkFont(size=11), text_color=C_GREEN)
        self._lbl_sim_cnt.pack(side="left")
        self._lbl_rest = ctk.CTkLabel(bot_row, text="",
                                       font=ctk.CTkFont(size=11), text_color=C_TEXT2)
        self._lbl_rest.pack(side="right")

    def _build_right(self, parent):
        # Card de Configuração Multi-Brave
        cfg = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=10,
                            border_color=C_BORDER, border_width=1)
        cfg.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(cfg, text="Configuração de Instâncias",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C_TEXT).pack(anchor="w", padx=16, pady=(10, 4))
        ctk.CTkFrame(cfg, height=1, fg_color=C_BORDER).pack(fill="x", padx=16)

        # Seletor de Quantidade de Braves
        r_braves = ctk.CTkFrame(cfg, fg_color="transparent")
        r_braves.pack(fill="x", padx=16, pady=(10, 4))
        ctk.CTkLabel(r_braves, text="Quantidade de Braves:",
                     font=ctk.CTkFont(size=12), text_color=C_TEXT2).pack(side="left")

        ctl = ctk.CTkFrame(r_braves, fg_color="transparent")
        ctl.pack(side="right")

        ctk.CTkButton(ctl, text="-", width=28, height=28,
                      fg_color=C_CARD2, hover_color=C_BORDER,
                      command=self._diminuir_braves).pack(side="left", padx=2)

        self._ent_braves = ctk.CTkEntry(ctl, width=42, height=28, justify="center",
                                        font=ctk.CTkFont(size=12, weight="bold"),
                                        fg_color=C_CARD2, border_color=C_BORDER)
        self._ent_braves.insert(0, str(self._braves_count))
        self._ent_braves.pack(side="left", padx=2)

        ctk.CTkButton(ctl, text="+", width=28, height=28,
                      fg_color=C_CARD2, hover_color=C_BORDER,
                      command=self._aumentar_braves).pack(side="left", padx=2)

        # Botão Salvar Configuração
        ctk.CTkButton(cfg, text="💾  Salvar configuração", height=30,
                      fg_color=C_CARD2, hover_color=C_BORDER,
                      border_color=C_BORDER, border_width=1,
                      font=ctk.CTkFont(size=11), text_color=C_TEXT,
                      command=self._salvar_config_braves).pack(fill="x", padx=16, pady=(4, 6))

        # Capacidade da Máquina
        rec_txt = f"RAM Livre: {self._sys_info['free_ram_gb']} GB / {self._sys_info['total_ram_gb']} GB"
        ctk.CTkLabel(cfg, text=rec_txt,
                     font=ctk.CTkFont(size=10), text_color=C_TEXT3).pack(anchor="w", padx=16)
        ctk.CTkLabel(cfg, text=f"Recomendado: {self._sys_info['recommended_workers']} Brave(s)",
                     font=ctk.CTkFont(size=10, weight="bold"), text_color=C_GREEN).pack(anchor="w", padx=16)

        self._lbl_aviso_ram = ctk.CTkLabel(
            cfg, text="", font=ctk.CTkFont(size=10), text_color=C_AMBER, wraplength=280
        )
        self._lbl_aviso_ram.pack(anchor="w", padx=16, pady=(2, 6))

        ctk.CTkFrame(cfg, height=1, fg_color=C_BORDER).pack(fill="x", padx=16)

        # Switches
        self._switches = {}
        for lbl, on in [("Retentar em erro", True),
                         ("Fechar abas extras", True),
                         ("Modo stealth", True)]:
            r = ctk.CTkFrame(cfg, fg_color="transparent")
            r.pack(fill="x", padx=16)
            inner = ctk.CTkFrame(r, fg_color="transparent")
            inner.pack(fill="x")
            ctk.CTkLabel(inner, text=lbl, font=ctk.CTkFont(size=11),
                         text_color=C_TEXT2).pack(side="left", pady=6)
            sw = ctk.CTkSwitch(inner, text="", width=36, height=18,
                                switch_height=14, switch_width=30,
                                button_color="#ffffff", button_hover_color="#dddddd",
                                progress_color=C_GREEN, fg_color=C_CARD2)
            if on:
                sw.select()
            sw.pack(side="right")
            self._switches[lbl] = sw

        ctk.CTkFrame(cfg, height=1, fg_color=C_BORDER).pack(fill="x", padx=16, pady=(4, 0))

        vr = ctk.CTkFrame(cfg, fg_color="transparent")
        vr.pack(fill="x", padx=16)
        ctk.CTkLabel(vr, text="Velocidade", font=ctk.CTkFont(size=11),
                     text_color=C_TEXT2).pack(side="left", pady=6)
        self._lbl_vel_r = ctk.CTkLabel(vr, text="—",
                                        font=ctk.CTkFont(size=11, weight="bold"),
                                        text_color=C_TEXT)
        self._lbl_vel_r.pack(side="right")

        rr = ctk.CTkFrame(cfg, fg_color="transparent")
        rr.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(rr, text="Tempo restante", font=ctk.CTkFont(size=11),
                     text_color=C_TEXT2).pack(side="left")
        self._lbl_rest_r = ctk.CTkLabel(rr, text="—",
                                         font=ctk.CTkFont(size=11, weight="bold"),
                                         text_color=C_TEXT)
        self._lbl_rest_r.pack(side="right")

        # File card
        file_c = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=10,
                               border_color=C_BORDER, border_width=1)
        file_c.pack(fill="x")

        ctk.CTkLabel(file_c, text="Carregar lista",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C_TEXT).pack(anchor="w", padx=16, pady=(10, 4))
        ctk.CTkFrame(file_c, height=1, fg_color=C_BORDER).pack(fill="x", padx=16)

        drop = ctk.CTkFrame(file_c, fg_color=C_CARD2, corner_radius=8,
                             border_color=C_BORDER, border_width=1)
        drop.pack(fill="x", padx=16, pady=(8, 6))
        drop.bind("<Button-1>", lambda e: self._escolher_arquivo())
        ctk.CTkLabel(drop, text="📄",
                     font=ctk.CTkFont(size=18)).pack(pady=(8, 2))
        ctk.CTkLabel(drop, text="Soltar CSV / XLSX aqui",
                     font=ctk.CTkFont(size=11), text_color=C_TEXT2).pack()
        ctk.CTkLabel(drop, text="NOME · CPF/CNPJ · DDD · FONE",
                     font=ctk.CTkFont(size=9), text_color=C_TEXT3).pack(pady=(1, 8))

        ctk.CTkButton(file_c, text="📂  Escolher arquivo", height=30,
                       fg_color=C_CARD2, hover_color=C_BORDER,
                       border_color=C_BORDER, border_width=1,
                       font=ctk.CTkFont(size=11), text_color=C_TEXT,
                       command=self._escolher_arquivo).pack(fill="x", padx=16, pady=(0, 10))

    def _build_log(self, parent):
        card = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=10,
                             border_color=C_BORDER, border_width=1)
        card.pack(fill="x", pady=(0, 8))

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(8, 4))
        ctk.CTkLabel(hdr, text="Log em tempo real",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C_TEXT).pack(side="left")
        ctk.CTkButton(hdr, text="Limpar", width=60, height=24,
                       fg_color=C_CARD2, hover_color=C_BORDER,
                       border_color=C_BORDER, border_width=1,
                       font=ctk.CTkFont(size=10), text_color=C_TEXT2,
                       command=self._clear_log).pack(side="right")

        ctk.CTkFrame(card, height=1, fg_color=C_BORDER).pack(fill="x")

        self._log_box = ctk.CTkTextbox(
            card, height=120,
            font=ctk.CTkFont(family="Consolas", size=10),
            fg_color=C_CARD, text_color=C_TEXT2,
            scrollbar_button_color=C_CARD2,
            state="disabled"
        )
        self._log_box.pack(fill="x", padx=10, pady=(4, 8))

        tb = self._log_box._textbox
        tb.tag_configure("ok",   foreground=C_GREEN)
        tb.tag_configure("err",  foreground=C_ERR)
        tb.tag_configure("info", foreground="#5B9CF6")
        tb.tag_configure("warn", foreground=C_AMBER)
        tb.tag_configure("otp",  foreground=C_AMBER)
        tb.tag_configure("ts",   foreground=C_TEXT3)

    def _build_bottom(self):
        bar = ctk.CTkFrame(self, height=48, fg_color=C_CARD, corner_radius=0)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(side="left", padx=16, pady=8)

        ctk.CTkLabel(inner, text="OTP:",
                     font=ctk.CTkFont(size=12), text_color=C_TEXT2
                     ).pack(side="left", padx=(0, 6))
        self._otp_entry = ctk.CTkEntry(inner, width=90,
                                        placeholder_text="123456",
                                        font=ctk.CTkFont(size=12),
                                        fg_color=C_CARD2, border_color=C_BORDER)
        self._otp_entry.pack(side="left")
        self._otp_entry.bind("<Return>", lambda e: self._enviar_otp())

        ctk.CTkButton(inner, text="Enviar", width=65, height=28,
                       fg_color=C_BLUE, hover_color="#163e6b",
                       font=ctk.CTkFont(size=11),
                       command=self._enviar_otp).pack(side="left", padx=(6, 0))

        self._lbl_cliente = ctk.CTkLabel(bar, text="Aguardando início...",
                                          font=ctk.CTkFont(size=11),
                                          text_color=C_TEXT3)
        self._lbl_cliente.pack(side="right", padx=16)

    # ───────────────────────────── AÇÕES ─────────────────────────────────────
    def _aumentar_braves(self):
        val = int(self._ent_braves.get().strip() or "1")
        if val < 8:
            self._ent_braves.delete(0, "end")
            self._ent_braves.insert(0, str(val + 1))
            self._salvar_config_braves()

    def _diminuir_braves(self):
        val = int(self._ent_braves.get().strip() or "1")
        if val > 1:
            self._ent_braves.delete(0, "end")
            self._ent_braves.insert(0, str(val - 1))
            self._salvar_config_braves()

    def _salvar_config_braves(self):
        try:
            val = int(self._ent_braves.get().strip())
            val = max(1, min(8, val))
            self._braves_count = val

            warn = SystemResources.check_capacity(val)
            if warn:
                self._lbl_aviso_ram.configure(text=f"⚠️ {warn}", text_color=C_AMBER)
            else:
                self._lbl_aviso_ram.configure(text="Capacidade adequada para estabilidade.", text_color=C_GREEN)

            self._log_line("info", f"Configuração salva: {val} Brave(s).")

            # Se estiver em execução, atualiza dinamicamente sem interromper clientes atuais
            if self._running and self._coord_holder:
                self._coord_holder[0].set_worker_count(val)
                self._log_line("info", f"Instâncias rebalanceadas dinamicamente para {val} workers.")

        except ValueError:
            self._log_line("warn", "Insira um número válido para a quantidade de Braves.")

    def _reorganizar_janelas(self):
        if self._coord_holder:
            self._coord_holder[0].reorganize_windows()
            self._log_line("info", "Janelas organizadas na tela.")
        else:
            self._log_line("info", "As janelas serão organizadas automaticamente ao iniciar.")

    def _toggle_run(self):
        if self._running:
            self._parar()
        else:
            self._iniciar()

    def _iniciar(self):
        if self._running:
            return
        self._running = True
        bot._stop_event.clear()
        bot._start_event.clear()
        self._coord_holder.clear()

        self._btn_main.configure(
            text="⏸  Pausar", fg_color=C_CARD2, hover_color=C_BORDER,
            border_color=C_BORDER, border_width=1, text_color=C_TEXT
        )
        self._set_status("Executando", C_GREEN, anim=True)
        self._log_line("info", f"Bot iniciado com {self._braves_count} Brave(s)")
        self._inicio = time.time()
        self._proc_sess = 0
        threading.Thread(target=self._run_bot, daemon=True).start()

    def _parar(self):
        bot._stop_event.set()
        self._set_status("Parando...", C_AMBER, anim=False)
        self._log_line("warn", "Parada solicitada — finalizando clientes em andamento com segurança.")

    def _enviar_otp(self):
        code = self._otp_entry.get().strip()
        if code:
            bot._otp_queue.put(code)
            self._otp_entry.delete(0, "end")
            self._log_line("info", f"OTP enviado: {code}")
            self._mv["otp"].set("0")

    def _abrir_resultados(self):
        p = os.path.abspath("resultado_filtrado.xlsx")
        if os.path.exists(p):
            os.startfile(p)
        else:
            self._log_line("warn", "resultado_filtrado.xlsx não encontrado.")

    def _escolher_arquivo(self):
        f = filedialog.askopenfilename(
            title="Selecionar lista de clientes",
            filetypes=[("CSV", "*.csv"), ("Excel", "*.xlsx *.xls"), ("Todos", "*.*")]
        )
        if f:
            import shutil
            dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clientes.csv")
            if f.lower().endswith(".csv"):
                shutil.copy(f, dst)
                self._log_line("ok", f"Lista carregada: {os.path.basename(f)}")
            else:
                self._log_line("warn", "Use arquivo .csv como entrada.")

    def _clear_log(self):
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    # ───────────────────────────── THREAD ────────────────────────────────────
    def _run_bot(self):
        h = _GuiHandler(bot._status_queue)
        logging.getLogger().addHandler(h)
        try:
            bot.main_gui(num_workers=self._braves_count, coordinator_holder=self._coord_holder)
        except Exception as e:
            bot._status_queue.put({"type": "log", "msg": f"ERRO FATAL: {e}"})
            bot._status_queue.put({"type": "stopped"})
        finally:
            logging.getLogger().removeHandler(h)
            self._running = False

    # ───────────────────────────── POLL ──────────────────────────────────────
    def _poll(self):
        try:
            while True:
                self._handle(bot._status_queue.get_nowait())
        except Exception:
            pass
        self.after(120, self._poll)

    def _handle(self, item):
        t = item.get("type", "")

        if t == "worker_status":
            w_id = item["worker_id"]
            st = item["status"]
            cli = item["cliente"]
            etp = item["etapa"]
            prc = item["processados"]
            err = item["erros"]
            tmp = item["tempo"]

            self._workers_data[w_id] = item
            self._update_worker_row(w_id, st, cli, etp, prc, err, tmp)
            self._update_instances_header()

        elif t == "log":
            msg = item["msg"]
            tag = "err" if any(w in msg.lower() for w in ("erro","error","fail","fatal")) \
                  else "warn" if any(w in msg.lower() for w in ("warn","timeout","expir")) \
                  else "ok"  if any(w in msg.lower() for w in ("ok","sucesso","login ok")) \
                  else "info"
            self._log_line(tag, msg)

        elif t == "progress":
            idx    = item["idx"]
            total  = item["total"]
            nome   = item["nome"]
            cpf    = item.get("cpf", "")
            status = item["status"]
            sim    = item["sim"]
            erros  = item["erros"]

            self._proc_sess += 1
            pct = idx / total if total > 0 else 0

            self._mv["total"].set(str(total))
            self._mv["feitos"].set(str(idx))
            self._mv["erros"].set(str(erros))
            self._msv["feitos"].set(f"{pct*100:.1f}% concluído")
            self._prog.set(pct)
            self._lbl_prog.configure(text=f"{idx} / {total}")
            self._lbl_sim_cnt.configure(text=f"✓ {sim} com refinanciamento")
            self._lbl_cliente.configure(text=f"Processando: {nome[:40]}")

            if self._inicio and self._proc_sess > 1:
                el = time.time() - self._inicio
                vel = self._proc_sess / el * 3600
                rest_h = (total - idx) / vel if vel > 0 else 0
                rest_txt = f"{rest_h:.1f}h" if rest_h >= 1 else f"{rest_h*60:.0f}min"
                self._lbl_vel.configure(text=f"{vel:.0f} / hora")
                self._lbl_vel_r.configure(text=f"{vel:.0f}/h")
                self._lbl_rest.configure(text=f"⏱ {rest_txt} restante")
                self._lbl_rest_r.configure(text=rest_txt)

            tag  = "sim" if status == "Sim" else "erro" if "Erro" in status or "Inválido" in status else "nao"
            stxt = "✓ Sim" if status == "Sim" else "✗ Não" if status == "Não" else f"⚠ {status}"
            self._tree.insert("", 0,
                              values=(nome[:34], security_config.mask_cpf(cpf), "—", stxt),
                              tags=(tag,))
            kids = self._tree.get_children()
            if len(kids) > 8:
                self._tree.delete(kids[-1])

            ltag = "ok" if status == "Sim" else "err" if "Erro" in status else ""
            self._log_line(ltag, f"[{idx}/{total}] {nome[:24]} ({security_config.mask_cpf(cpf)}) → {status}")

        elif t == "init_stats":
            total  = item["total"]
            feitos = item["feitos"]
            pct = feitos / total if total > 0 else 0
            self._mv["total"].set(str(total))
            self._mv["feitos"].set(str(feitos))
            self._mv["erros"].set(str(item["erros"]))
            self._msv["feitos"].set(f"{pct*100:.1f}% concluído")
            self._prog.set(pct)
            self._lbl_prog.configure(text=f"{feitos} / {total}")
            self._lbl_sim_cnt.configure(text=f"✓ {item['sim']} com refinanciamento")

        elif t == "otp_needed":
            cur = int(self._mv["otp"].get() or "0")
            self._mv["otp"].set(str(cur + 1))
            self._set_status("OTP necessário!", C_AMBER, anim=False)
            self._log_line("otp", "Código de verificação necessário — digite no campo OTP abaixo!")
            self._otp_entry.focus()
            self.lift()
            self.attributes("-topmost", True)
            self.after(3000, lambda: self.attributes("-topmost", False))
            self._piscar(6)

        elif t == "sessao_expirada":
            self._set_status("Reconectando...", C_AMBER, anim=True)
            self._log_line("warn", "Sessão expirada — tentando login automático...")

        elif t == "login_ok":
            self._set_status("Executando", C_GREEN, anim=True)
            self._log_line("ok", "Login automático OK — continuando!")

        elif t == "aguardando_login":
            self._set_status("Aguardando login", C_AMBER, anim=False)
            self._log_line("info", "Brave aberto — faça o login. O bot detecta automaticamente.")

        elif t == "rodando":
            self._set_status("Executando", C_GREEN, anim=True)
            self._log_line("ok", "Instâncias ativas — iniciando processamento!")

        elif t == "stopped":
            self._running = False
            self._btn_main.configure(
                text="▶  Iniciar", fg_color=C_RED, hover_color=C_RED2,
                border_width=0, text_color="#fff"
            )
            self._set_status("Parado", C_TEXT2, anim=False)
            self._log_line("info", "Bot parado")
            self._lbl_cliente.configure(text="Parado")
            self._update_instances_header()

    def _update_worker_row(self, w_id, status, cliente, etapa, processados, erros, tempo):
        """Atualiza a linha do worker na tabela de instâncias."""
        item_id = f"w_{w_id}"
        nome_brave = f"Brave {w_id:02d}"
        tag = "run" if "executando" in status.lower() else "wait" if "micro" in status.lower() or "iniciando" in status.lower() else "err" if "falha" in status.lower() else "off"

        values = (nome_brave, status, cliente, etapa, str(processados), str(erros), tempo)
        if self._tree_inst.exists(item_id):
            self._tree_inst.item(item_id, values=values, tags=(tag,))
        else:
            self._tree_inst.insert("", "end", iid=item_id, values=values, tags=(tag,))

    def _update_instances_header(self):
        """Atualiza o resumo superior de gerenciamento de instâncias."""
        ativos = sum(1 for w in self._workers_data.values() if w["status"] in ["Executando", "Micro-pausa", "Autenticando", "Iniciando"])
        falhas = sum(w["erros"] for w in self._workers_data.values())
        txt = f"Config: {self._braves_count} | Ativos: {ativos} | Workers: {len(self._workers_data)} | Falhas: {falhas}"
        self._lbl_inst_resumo.configure(text=txt)

    # ───────────────────────────── HELPERS ───────────────────────────────────
    def _set_status(self, text, color, anim=False):
        self._dot_color = color
        self._dot_anim  = anim
        self._dot_on    = True
        self._lbl_status.configure(text=text, text_color=color)
        try:
            self._dot_cv.itemconfig(self._dot_id, fill=color)
        except Exception:
            pass

    def _animate_dot(self):
        if self._dot_anim:
            self._dot_on = not self._dot_on
            clr = self._dot_color if self._dot_on else C_CARD2
            try:
                self._dot_cv.itemconfig(self._dot_id, fill=clr)
            except Exception:
                pass
        self.after(700, self._animate_dot)

    def _log_line(self, tag: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_box.configure(state="normal")
        tb = self._log_box._textbox
        tb.insert("end", ts + "  ", "ts")
        tb.insert("end", msg + "\n", tag)
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _piscar(self, n: int):
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            class FI(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_void_p),
                             ("dwFlags", ctypes.c_uint), ("uCount", ctypes.c_uint),
                             ("dwTimeout", ctypes.c_uint)]
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(
                FI(ctypes.sizeof(FI), hwnd, 3 | 12, n, 0)))
        except Exception:
            pass


class _GuiHandler(logging.Handler):
    def __init__(self, q):
        super().__init__()
        self._q = q

    def emit(self, record):
        try:
            self._q.put({"type": "log", "msg": self.format(record)})
        except Exception:
            pass


if __name__ == "__main__":
    app = BotApp()
    app.mainloop()

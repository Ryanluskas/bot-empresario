"""
Interface gráfica — Bot Santander (novo design)
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


class BotApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Bot Santander")
        self.geometry("1220x860")
        self.minsize(1100, 760)
        self.configure(fg_color=C_BG)

        self._running  = False
        self._inicio   = None
        self._proc_sess = 0
        self._dot_on   = True
        self._dot_color = C_TEXT3
        self._dot_anim  = False
        self._session_start = datetime.now().strftime("%H:%M")

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
        two.pack(fill="both", expand=True, pady=(0, 10))

        left = ctk.CTkFrame(two, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        right = ctk.CTkFrame(two, width=296, fg_color="transparent")
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        self._build_table(left)
        self._build_right(right)
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
                     text="Bot Santander  —  Automação de Listas",
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
        specs = [
            ("total",  "TOTAL NA LISTA",    C_TEXT,   "clientes carregados"),
            ("feitos", "PROCESSADOS",        C_GREEN,  "—"),
            ("erros",  "ERROS",              C_ERR,    "CPF inválido / timeout"),
        ]
        self._mv  = {}
        self._msv = {}
        for i, (k, lbl, clr, sub) in enumerate(specs):
            row.columnconfigure(i, weight=1)
            pad_left = 6 if i > 0 else 0
            card = ctk.CTkFrame(row, fg_color=C_CARD, corner_radius=10,
                                 border_color=C_BORDER, border_width=1)
            card.grid(row=0, column=i, padx=(pad_left, 0), sticky="ew", ipady=2)

            ctk.CTkLabel(card, text=lbl,
                         font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=C_TEXT3).pack(anchor="w", padx=16, pady=(12, 2))

            v = ctk.StringVar(value="—")
            self._mv[k] = v
            ctk.CTkLabel(card, textvariable=v,
                         font=ctk.CTkFont(size=26, weight="bold"),
                         text_color=clr).pack(anchor="w", padx=16)

            sv = ctk.StringVar(value=sub)
            self._msv[k] = sv
            ctk.CTkLabel(card, textvariable=sv,
                         font=ctk.CTkFont(size=11),
                         text_color=C_TEXT2).pack(anchor="w", padx=16, pady=(1, 12))

    def _build_controls(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 10))

        self._btn_main = ctk.CTkButton(
            row, text="▶  Iniciar", width=120, height=36,
            fg_color=C_RED, hover_color=C_RED2,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._toggle_run
        )
        self._btn_main.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            row, text="↺  Reprocessar erros", height=36, width=166,
            fg_color=C_CARD, hover_color=C_CARD2,
            border_color=C_BORDER, border_width=1,
            font=ctk.CTkFont(size=12), text_color=C_TEXT,
            command=lambda: self._log_line(
                "INFO", "Reprocessar: reinicie o bot — ele retoma do ponto parado.")
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            row, text="⬇  Exportar relatório", height=36, width=166,
            fg_color=C_CARD, hover_color=C_CARD2,
            border_color=C_BORDER, border_width=1,
            font=ctk.CTkFont(size=12), text_color=C_TEXT,
            command=self._abrir_resultados
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            row, text="⏹  Encerrar sessão", height=36, width=150,
            fg_color="transparent", hover_color="#2e1010",
            border_color=C_ERR, border_width=1,
            font=ctk.CTkFont(size=12), text_color=C_ERR,
            command=self._parar
        ).pack(side="right")

    def _build_table(self, parent):
        card = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=10,
                             border_color=C_BORDER, border_width=1)
        card.pack(fill="both", expand=True)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(12, 8))
        ctk.CTkLabel(hdr, text="Clientes em processamento",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C_TEXT).pack(side="left")
        self._lbl_vel = ctk.CTkLabel(hdr, text="",
                                      font=ctk.CTkFont(size=11),
                                      text_color=C_TEXT2)
        self._lbl_vel.pack(side="right")

        # Separator
        ctk.CTkFrame(card, height=1, fg_color=C_BORDER).pack(fill="x")

        # Treeview
        sty = ttk.Style()
        sty.theme_use("clam")
        sty.configure("Bot.Treeview",
                      background=C_CARD, foreground=C_TEXT,
                      fieldbackground=C_CARD, rowheight=32,
                      bordercolor=C_BORDER, borderwidth=0,
                      font=("Segoe UI", 11))
        sty.configure("Bot.Treeview.Heading",
                      background=C_CARD2, foreground=C_TEXT2,
                      font=("Segoe UI", 10), relief="flat",
                      bordercolor=C_BORDER)
        sty.map("Bot.Treeview",
                background=[("selected", "#2a2a2a")],
                foreground=[("selected", C_TEXT)])
        sty.map("Bot.Treeview.Heading",
                background=[("active", C_CARD2)])

        self._tree = ttk.Treeview(card, columns=("nome","cpf","fone","status"),
                                   show="headings", style="Bot.Treeview", height=7)
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
        self._tree.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        ctk.CTkFrame(card, height=1, fg_color=C_BORDER).pack(fill="x")

        # Progress section
        pb = ctk.CTkFrame(card, fg_color="transparent")
        pb.pack(fill="x", padx=16, pady=10)

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
        self._prog.pack(fill="x", pady=(5, 0))

        bot_row = ctk.CTkFrame(pb, fg_color="transparent")
        bot_row.pack(fill="x", pady=(3, 0))
        self._lbl_sim_cnt = ctk.CTkLabel(bot_row, text="",
                                          font=ctk.CTkFont(size=11), text_color=C_GREEN)
        self._lbl_sim_cnt.pack(side="left")
        self._lbl_rest = ctk.CTkLabel(bot_row, text="",
                                       font=ctk.CTkFont(size=11), text_color=C_TEXT2)
        self._lbl_rest.pack(side="right")

    def _build_right(self, parent):
        # Config card
        cfg = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=10,
                            border_color=C_BORDER, border_width=1)
        cfg.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(cfg, text="Configurações",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C_TEXT).pack(anchor="w", padx=16, pady=(12, 6))
        ctk.CTkFrame(cfg, height=1, fg_color=C_BORDER).pack(fill="x", padx=16)

        self._switches = {}
        for lbl, on in [("Retentar em erro", True),
                         ("Fechar abas extras", True)]:
            r = ctk.CTkFrame(cfg, fg_color="transparent")
            r.pack(fill="x", padx=16)
            ctk.CTkFrame(r, height=1, fg_color=C_BORDER).pack(fill="x")
            inner = ctk.CTkFrame(r, fg_color="transparent")
            inner.pack(fill="x")
            ctk.CTkLabel(inner, text=lbl, font=ctk.CTkFont(size=12),
                         text_color=C_TEXT2).pack(side="left", pady=9)
            sw = ctk.CTkSwitch(inner, text="", width=38, height=20,
                                switch_height=16, switch_width=34,
                                button_color="#ffffff", button_hover_color="#dddddd",
                                progress_color=C_GREEN, fg_color=C_CARD2)
            if on:
                sw.select()
            sw.pack(side="right")
            self._switches[lbl] = sw

        ctk.CTkFrame(cfg, height=1, fg_color=C_BORDER).pack(fill="x", padx=16, pady=(4, 0))

        vr = ctk.CTkFrame(cfg, fg_color="transparent")
        vr.pack(fill="x", padx=16)
        ctk.CTkLabel(vr, text="Velocidade", font=ctk.CTkFont(size=12),
                     text_color=C_TEXT2).pack(side="left", pady=8)
        self._lbl_vel_r = ctk.CTkLabel(vr, text="—",
                                        font=ctk.CTkFont(size=12, weight="bold"),
                                        text_color=C_TEXT)
        self._lbl_vel_r.pack(side="right")

        rr = ctk.CTkFrame(cfg, fg_color="transparent")
        rr.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(rr, text="Tempo restante", font=ctk.CTkFont(size=12),
                     text_color=C_TEXT2).pack(side="left")
        self._lbl_rest_r = ctk.CTkLabel(rr, text="—",
                                         font=ctk.CTkFont(size=12, weight="bold"),
                                         text_color=C_TEXT)
        self._lbl_rest_r.pack(side="right")

        # File card
        file_c = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=10,
                               border_color=C_BORDER, border_width=1)
        file_c.pack(fill="x")

        ctk.CTkLabel(file_c, text="Carregar lista",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C_TEXT).pack(anchor="w", padx=16, pady=(12, 6))
        ctk.CTkFrame(file_c, height=1, fg_color=C_BORDER).pack(fill="x", padx=16)

        drop = ctk.CTkFrame(file_c, fg_color=C_CARD2, corner_radius=8,
                             border_color=C_BORDER, border_width=1)
        drop.pack(fill="x", padx=16, pady=(10, 8))
        drop.bind("<Button-1>", lambda e: self._escolher_arquivo())
        ctk.CTkLabel(drop, text="📄",
                     font=ctk.CTkFont(size=20)).pack(pady=(12, 2))
        ctk.CTkLabel(drop, text="Soltar CSV / XLSX aqui",
                     font=ctk.CTkFont(size=12), text_color=C_TEXT2).pack()
        ctk.CTkLabel(drop, text="NOME · CPF/CNPJ · DDD · FONE",
                     font=ctk.CTkFont(size=10), text_color=C_TEXT3).pack(pady=(1, 12))

        ctk.CTkButton(file_c, text="📂  Escolher arquivo", height=32,
                       fg_color=C_CARD2, hover_color=C_BORDER,
                       border_color=C_BORDER, border_width=1,
                       font=ctk.CTkFont(size=12), text_color=C_TEXT,
                       command=self._escolher_arquivo).pack(fill="x", padx=16, pady=(0, 14))

    def _build_log(self, parent):
        card = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=10,
                             border_color=C_BORDER, border_width=1)
        card.pack(fill="x", pady=(0, 10))

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(10, 6))
        ctk.CTkLabel(hdr, text="Log em tempo real",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C_TEXT).pack(side="left")
        ctk.CTkButton(hdr, text="Limpar", width=66, height=26,
                       fg_color=C_CARD2, hover_color=C_BORDER,
                       border_color=C_BORDER, border_width=1,
                       font=ctk.CTkFont(size=11), text_color=C_TEXT2,
                       command=self._clear_log).pack(side="right")

        ctk.CTkFrame(card, height=1, fg_color=C_BORDER).pack(fill="x")

        self._log_box = ctk.CTkTextbox(
            card, height=150,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=C_CARD, text_color=C_TEXT2,
            scrollbar_button_color=C_CARD2,
            state="disabled"
        )
        self._log_box.pack(fill="x", padx=10, pady=(6, 10))

        tb = self._log_box._textbox
        tb.tag_configure("ok",   foreground=C_GREEN)
        tb.tag_configure("err",  foreground=C_ERR)
        tb.tag_configure("info", foreground="#5B9CF6")
        tb.tag_configure("warn", foreground=C_AMBER)
        tb.tag_configure("ts",   foreground=C_TEXT3)

    def _build_bottom(self):
        bar = ctk.CTkFrame(self, height=52, fg_color=C_CARD, corner_radius=0)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        self._lbl_cliente = ctk.CTkLabel(bar, text="Aguardando...",
                                          font=ctk.CTkFont(size=11),
                                          text_color=C_TEXT3)
        self._lbl_cliente.pack(side="right", padx=16)

    # ───────────────────────────── AÇÕES ─────────────────────────────────────
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

        self._btn_main.configure(
            text="⏸  Pausar", fg_color=C_CARD2, hover_color=C_BORDER,
            border_color=C_BORDER, border_width=1, text_color=C_TEXT
        )
        self._set_status("Abrindo portal...", C_AMBER, anim=True)
        self._log_line("info", "Bot iniciado")
        self._inicio = time.time()
        self._proc_sess = 0
        threading.Thread(target=self._run_bot, daemon=True).start()

    def _parar(self):
        bot._stop_event.set()
        self._set_status("Parando...", C_AMBER, anim=False)
        self._log_line("warn", "Parada solicitada")

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
        erro_acesso = None
        try:
            bot.main_gui()
        except bot.AcessoSantanderNegado as e:
            erro_acesso = str(e)
        except Exception as e:
            bot._status_queue.put({"type": "log", "msg": f"ERRO FATAL: {e}"})
        finally:
            logging.getLogger().removeHandler(h)
            bot._status_queue.put({"type": "stopped", "erro_acesso": erro_acesso})

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

        if t == "log":
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
            fone_display = item.get("fone") or "—"
            self._tree.insert("", 0,
                              values=(nome[:34], self._mask_cpf(cpf), fone_display, stxt),
                              tags=(tag,))
            kids = self._tree.get_children()
            if len(kids) > 8:
                self._tree.delete(kids[-1])

            ltag = "ok" if status == "Sim" else "err" if "Erro" in status else ""
            self._log_line(ltag, f"[{idx}/{total}] {nome[:28]} → {status}")

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

        elif t == "sessao_expirada":
            self._set_status("Sessão expirada", C_AMBER, anim=False)
            self._log_line("warn", "Entre novamente no portal pelo Brave para continuar.")

        elif t == "login_ok":
            self._set_status("Executando", C_GREEN, anim=True)
            self._log_line("ok", "Login concluído. Retomando o processamento.")

        elif t == "aguardando_login":
            self._set_status("Aguardando login", C_AMBER, anim=False)
            self._log_line("info", bot._ORIENTACAO_LOGIN)

        elif t == "rodando":
            self._set_status("Executando", C_GREEN, anim=True)
            self._log_line("ok", "Formulário detectado — iniciando processamento!")

        elif t == "stopped":
            self._running = False
            self._btn_main.configure(
                text="▶  Iniciar", fg_color=C_RED, hover_color=C_RED2,
                border_width=0, text_color="#fff"
            )
            erro_acesso = item.get("erro_acesso")
            if erro_acesso:
                self._set_status("Acesso negado", C_ERR, anim=False)
                self._log_line("err", erro_acesso)
                self._lbl_cliente.configure(text="Acesso negado pelo Santander")
            else:
                self._set_status("Parado", C_TEXT2, anim=False)
                self._log_line("info", "Bot parado")
                self._lbl_cliente.configure(text="Parado")

    # ───────────────────────────── HELPERS ───────────────────────────────────
    def _mask_cpf(self, cpf: str) -> str:
        d = "".join(c for c in cpf if c.isdigit())
        if len(d) == 11:
            return f"***.{d[3:6]}.{d[6:9]}-**"
        return cpf[:7] + "..." if len(cpf) > 7 else cpf

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

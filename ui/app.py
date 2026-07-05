# =====================================================================
# DOCFLOW — Interface Principal (ui/app.py)
# =====================================================================
import os
import sys
import queue
import threading
import time
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.pipeline import processar_arquivos
from utils.config_manager import ConfigManager

try:
    from ui.tray import criar_icone_tray
    TRAY_OK = True
except ImportError:
    TRAY_OK = False

try:
    from winotify import Notification
    NOTIF_OK = True
except ImportError:
    NOTIF_OK = False


def _caminho_icone() -> str:
    """Retorna o caminho do ícone, compatível com execução normal e com o .exe gerado pelo PyInstaller."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "assets", "icone.ico")


_MESES_PT = {
    1: "Janeiro",  2: "Fevereiro", 3: "Março",    4: "Abril",
    5: "Maio",     6: "Junho",     7: "Julho",     8: "Agosto",
    9: "Setembro", 10: "Outubro",  11: "Novembro", 12: "Dezembro",
}

_COR_VERDE   = ("#1a6b1a", "#155215")
_COR_VERMELHO = ("#7a1f1f", "#5a1515")
_COR_AMARELO = ("#7a6a1f", "#5a4d15")
_COR_AZUL    = ("#1f4a8a", "#153268")


class DocFlowApp(ctk.CTk):

    # ─── Inicialização ────────────────────────────────────────────────

    def __init__(self):
        super().__init__()

        self._cfg          = ConfigManager()
        self._log_queue:   queue.Queue = queue.Queue()
        self._is_running   = False
        self._is_paused    = False
        self._is_processing= False
        self._next_scan:   datetime | None = None
        self._tray         = None
        self._history:     list[dict]  = []
        self._solteiros:   list[str]   = []
        self._hoje_count   = 0

        # Tema
        ctk.set_appearance_mode(self._cfg.get("tema", "dark"))
        ctk.set_default_color_theme("blue")

        # Janela
        self.title("DocFlow")
        self.geometry("980x660")
        self.minsize(860, 580)
        try:
            self.iconbitmap(_caminho_icone())
        except Exception:
            pass  # ícone é cosmético — segue sem travar caso o arquivo não exista (ex: Linux/Mac)
        self.protocol("WM_DELETE_WINDOW", self._minimizar_para_tray)

        self._build_ui()
        self._tick_log()
        self._tick_countdown()
        self._iniciar_tray()

    # ─── Layout principal ─────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()

    # ─── Sidebar ──────────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=272, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_rowconfigure(9, weight=1)

        # ── Logo ──────────────────────────────────────────────────────
        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.grid(row=0, column=0, padx=20, pady=(22, 6), sticky="ew")
        ctk.CTkLabel(logo, text="🌊 DocFlow",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkLabel(logo, text=" v1.0", font=ctk.CTkFont(size=11),
                     text_color="gray").pack(side="left", pady=(5, 0))

        ctk.CTkLabel(sb, text="CONFIGURAÇÕES",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray").grid(row=1, column=0, padx=20, pady=(10, 2), sticky="w")

        # ── Pasta Origem ──────────────────────────────────────────────
        ctk.CTkLabel(sb, text="📥  Pasta de Origem",
                     anchor="w").grid(row=2, column=0, padx=20, pady=(6, 2), sticky="ew")
        f2 = ctk.CTkFrame(sb, fg_color="transparent")
        f2.grid(row=3, column=0, padx=20, pady=(0, 6), sticky="ew")
        f2.grid_columnconfigure(0, weight=1)
        self._v_origem = ctk.StringVar(value=self._cfg.get("pasta_origem", ""))
        ctk.CTkEntry(f2, textvariable=self._v_origem,
                     placeholder_text="Escolha sua pasta de origem").grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(f2, text="📁", width=34,
                      command=lambda: self._pick_folder("origem")).grid(row=0, column=1, padx=(4, 0))

        # ── Pasta Destino (Mês) ───────────────────────────────────────
        ctk.CTkLabel(sb, text="📤  Destino — Pasta do Mês",
                     anchor="w").grid(row=4, column=0, padx=20, pady=(4, 2), sticky="ew")
        f4 = ctk.CTkFrame(sb, fg_color="transparent")
        f4.grid(row=5, column=0, padx=20, pady=(0, 2), sticky="ew")
        f4.grid_columnconfigure(0, weight=1)
        self._v_destino = ctk.StringVar(value=self._cfg.get("pasta_destino", ""))
        ctk.CTkEntry(f4, textvariable=self._v_destino,
                     placeholder_text="Escolha sua pasta de destino").grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(f4, text="📁", width=34,
                      command=lambda: self._pick_folder("destino")).grid(row=0, column=1, padx=(4, 0))

        now = datetime.now()
        ctk.CTkLabel(sb,
                     text=f"📅  Mês atual: {now.month:02d} — {_MESES_PT[now.month]}",
                     font=ctk.CTkFont(size=11), text_color="gray",
                     anchor="w").grid(row=6, column=0, padx=20, pady=(2, 10), sticky="w")

        # ── Intervalo ─────────────────────────────────────────────────
        ctk.CTkLabel(sb, text="⏱️  Intervalo de Varredura",
                     anchor="w").grid(row=7, column=0, padx=20, pady=(4, 2), sticky="ew")
        fi = ctk.CTkFrame(sb, fg_color="transparent")
        fi.grid(row=8, column=0, padx=20, pady=(0, 10), sticky="ew")
        self._v_intervalo = ctk.StringVar(value=str(self._cfg.get("intervalo_minutos", 15)))
        ctk.CTkOptionMenu(fi, variable=self._v_intervalo,
                          values=["5", "10", "15", "30", "60"],
                          command=self._on_intervalo,
                          width=110).pack(side="left")
        ctk.CTkLabel(fi, text=" minutos").pack(side="left")

        # ── Opções ────────────────────────────────────────────────────
        ctk.CTkLabel(sb, text="OPÇÕES",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray").grid(row=9, column=0, padx=20, pady=(4, 4), sticky="nw")

        opts = ctk.CTkFrame(sb, fg_color="transparent")
        opts.grid(row=10, column=0, padx=20, pady=(0, 6), sticky="new")

        self._tema_seg = ctk.CTkSegmentedButton(
            opts, values=["🌙 Escuro", "☀️ Claro"],
            command=self._on_tema, width=220)
        self._tema_seg.set("🌙 Escuro" if self._cfg.get("tema") == "dark" else "☀️ Claro")
        self._tema_seg.pack(fill="x", pady=(0, 8))

        self._sw_notif   = self._switch_row(opts, "Notificações ao concluir",
                                            self._cfg.get("notificacoes", True),
                                            lambda: self._cfg.set("notificacoes", bool(self._sw_notif.get())))
        self._sw_startup = self._switch_row(opts, "Iniciar com o Windows",
                                            self._cfg.get("iniciar_com_windows", False),
                                            lambda: self._cfg.set_startup(bool(self._sw_startup.get())))

        # ── Botões de controle ────────────────────────────────────────
        btns = ctk.CTkFrame(sb, fg_color="transparent")
        btns.grid(row=11, column=0, padx=20, pady=(6, 20), sticky="ew")
        btns.grid_columnconfigure((0, 1), weight=1)

        self._btn_start = ctk.CTkButton(btns, text="▶  Iniciar",
                                         fg_color=_COR_VERDE[0], hover_color=_COR_VERDE[1],
                                         command=self._toggle_scanner)
        self._btn_start.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        self._btn_pause = ctk.CTkButton(btns, text="⏸  Pausar",
                                         fg_color=_COR_AMARELO[0], hover_color=_COR_AMARELO[1],
                                         state="disabled", command=self.toggle_pause)
        self._btn_pause.grid(row=1, column=0, sticky="ew", padx=(0, 3))

        self._btn_now = ctk.CTkButton(btns, text="⚡  Agora",
                                       fg_color=_COR_AZUL[0], hover_color=_COR_AZUL[1],
                                       command=self.processar_agora)
        self._btn_now.grid(row=1, column=1, sticky="ew", padx=(3, 0))

    # ─── Área principal com abas ──────────────────────────────────────

    def _build_main(self):
        main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)

        self._tabs = ctk.CTkTabview(main, corner_radius=8)
        self._tabs.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        for name in ("📊  Dashboard", "⚠️  Solteiros", "📋  Histórico"):
            self._tabs.add(name)

        self._build_dashboard(self._tabs.tab("📊  Dashboard"))
        self._build_solteiros(self._tabs.tab("⚠️  Solteiros"))
        self._build_historico(self._tabs.tab("📋  Histórico"))

        self._build_statusbar(main)

    def _build_dashboard(self, parent):
        parent.grid_columnconfigure((0, 1), weight=1)
        parent.grid_rowconfigure(2, weight=1)

        self._c_status = self._card(parent, "Status",           "⏸  Aguardando", 0, 0)
        self._c_prox   = self._card(parent, "Próxima Varredura","—",              0, 1)
        self._c_hoje   = self._card(parent, "Combinações Hoje", "0",              1, 0)
        self._c_solt   = self._card(parent, "Solteiros",        "0 aguardando",   1, 1)

        log_f = ctk.CTkFrame(parent)
        log_f.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))
        log_f.grid_columnconfigure(0, weight=1)
        log_f.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(log_f, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=12, pady=(10, 2), sticky="ew")
        ctk.CTkLabel(hdr, text="Log em Tempo Real",
                     font=ctk.CTkFont(size=12, weight="bold"), anchor="w").pack(side="left")
        ctk.CTkButton(hdr, text="Limpar log", width=90,
                      command=self._limpar_log).pack(side="right")

        self._log_box = ctk.CTkTextbox(
            log_f, state="disabled",
            font=ctk.CTkFont(family="Consolas", size=11), wrap="word")
        self._log_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def _build_solteiros(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        ctk.CTkLabel(hdr,
                     text="Arquivos sem par — ficam na origem até o par chegar",
                     font=ctk.CTkFont(size=12), text_color="gray", anchor="w").pack(side="left")
        ctk.CTkButton(hdr, text="🔄 Atualizar", width=110,
                      command=self._atualizar_solteiros).pack(side="right")

        self._sol_scroll = ctk.CTkScrollableFrame(parent)
        self._sol_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._sol_scroll.grid_columnconfigure(0, weight=1)

    def _build_historico(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        ctk.CTkLabel(hdr, text="Histórico de processamentos",
                     font=ctk.CTkFont(size=12), text_color="gray", anchor="w").pack(side="left")
        ctk.CTkButton(hdr, text="🗑 Limpar", width=90,
                      command=self._limpar_historico).pack(side="right")

        self._hist_scroll = ctk.CTkScrollableFrame(parent)
        self._hist_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._hist_scroll.grid_columnconfigure(0, weight=1)

    def _build_statusbar(self, parent):
        bar = ctk.CTkFrame(parent, height=30, corner_radius=0)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)

        self._lbl_bar_status = ctk.CTkLabel(
            bar, text="⏸  Inativo", anchor="w", font=ctk.CTkFont(size=11))
        self._lbl_bar_status.grid(row=0, column=0, padx=14, sticky="w")

        self._lbl_bar_cd = ctk.CTkLabel(
            bar, text="", anchor="e", font=ctk.CTkFont(size=11), text_color="gray")
        self._lbl_bar_cd.grid(row=0, column=2, padx=14, sticky="e")

    # ─── Helpers de UI ────────────────────────────────────────────────

    def _card(self, parent, titulo, valor, row, col) -> ctk.CTkLabel:
        f = ctk.CTkFrame(parent)
        f.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
        ctk.CTkLabel(f, text=titulo,
                     font=ctk.CTkFont(size=11), text_color="gray", anchor="w").pack(
            padx=14, pady=(10, 1), anchor="w")
        lbl = ctk.CTkLabel(f, text=valor,
                            font=ctk.CTkFont(size=15, weight="bold"), anchor="w")
        lbl.pack(padx=14, pady=(0, 10), anchor="w")
        return lbl

    def _switch_row(self, parent, texto, inicial, cmd) -> ctk.CTkSwitch:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=texto, anchor="w").pack(side="left")
        sw = ctk.CTkSwitch(row, text="", command=cmd)
        if inicial:
            sw.select()
        sw.pack(side="right")
        return sw

    # ─── Log ──────────────────────────────────────────────────────────

    def _log(self, msg: str):
        self._log_queue.put(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _tick_log(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self._log_box.configure(state="normal")
                self._log_box.insert("end", msg + "\n")
                self._log_box.see("end")
                self._log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._tick_log)

    def _limpar_log(self):
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    # ─── Scanner ──────────────────────────────────────────────────────

    def _toggle_scanner(self):
        if self._is_running:
            self._parar()
        else:
            self._iniciar()

    def _iniciar(self):
        origem = self._v_origem.get().strip()
        if not origem or not os.path.isdir(origem):
            messagebox.showerror("Erro", "Selecione uma pasta de origem válida antes de iniciar.")
            return

        self._cfg.set("pasta_origem", origem)
        self._cfg.set("pasta_destino", self._v_destino.get().strip())

        self._is_running = True
        self._is_paused  = False
        self._agendar()

        threading.Thread(target=self._scan_loop, daemon=True).start()

        self._log("▶ Monitoramento iniciado.")
        self._set_status_ui("● Monitorando", "●  Monitorando")
        self._btn_start.configure(text="⏹  Parar",
                                   fg_color=_COR_VERMELHO[0], hover_color=_COR_VERMELHO[1])
        self._btn_pause.configure(state="normal")

    def _parar(self):
        self._is_running = False
        self._is_paused  = False
        self._next_scan  = None
        self._log("⏹ Monitoramento parado.")
        self._set_status_ui("⏸  Parado", "⏸  Inativo")
        self._btn_start.configure(text="▶  Iniciar",
                                   fg_color=_COR_VERDE[0], hover_color=_COR_VERDE[1])
        self._btn_pause.configure(state="disabled", text="⏸  Pausar")
        self._c_prox.configure(text="—")
        self._lbl_bar_cd.configure(text="")

    def _agendar(self):
        mins = int(self._v_intervalo.get())
        self._next_scan = datetime.now() + timedelta(minutes=mins)

    def _scan_loop(self):
        while self._is_running:
            if (not self._is_paused and self._next_scan
                    and datetime.now() >= self._next_scan):
                self._executar()
                self._agendar()
            time.sleep(1)

    def toggle_pause(self):
        if not self._is_running:
            return
        self._is_paused = not self._is_paused
        if self._is_paused:
            self._log("⏸ Monitoramento pausado.")
            self._btn_pause.configure(text="▶  Retomar")
            self._set_status_ui("⏸  Pausado", "⏸  Pausado")
        else:
            self._log("▶ Monitoramento retomado.")
            self._btn_pause.configure(text="⏸  Pausar")
            self._set_status_ui("●  Monitorando", "●  Monitorando")

    def processar_agora(self):
        if not self._is_processing:
            threading.Thread(target=self._executar, daemon=True).start()

    def _executar(self):
        if self._is_processing:
            return
        self._is_processing = True
        self.after(0, lambda: self._set_status_ui("⚙  Processando...", "⚙  Processando..."))
        self._log("🔍 Iniciando varredura...")

        try:
            res = processar_arquivos(
                pasta_origem   = self._cfg.get("pasta_origem",  ""),
                pasta_destino  = self._cfg.get("pasta_destino", ""),
                callback       = self._log,
                modo_gui       = True,
            )
            suc    = res.get("sucessos", 0)
            sol    = res.get("arquivos_solteiros", [])
            novos  = res.get("arquivos_novos", [])

            self._solteiros   = sol
            self._hoje_count += suc
            self._history.insert(0, {
                "ts":       datetime.now().strftime("%d/%m/%Y %H:%M"),
                "sucessos": suc,
                "arquivos": novos,
            })

            self._log(f"✅ Concluído — {suc} combinação(ões), {len(sol)} solteiro(s).")
            self.after(0, lambda: self._c_hoje.configure(text=str(self._hoje_count)))
            self.after(0, lambda: self._c_solt.configure(text=f"{len(sol)} aguardando"))
            self.after(0, self._atualizar_solteiros)
            self.after(0, self._atualizar_historico)

            if suc > 0:
                self._notificar(suc, len(sol))

        except Exception as e:
            self._log(f"❌ Erro: {e}")
        finally:
            self._is_processing = False
            status = "●  Monitorando" if (self._is_running and not self._is_paused) else "⏸  Aguardando"
            self.after(0, lambda: self._set_status_ui(status, status))

    # ─── Countdown ────────────────────────────────────────────────────

    def _tick_countdown(self):
        if self._is_running and not self._is_paused and self._next_scan:
            delta = self._next_scan - datetime.now()
            secs  = max(0, int(delta.total_seconds()))
            m, s  = divmod(secs, 60)
            txt   = f"Próxima varredura em {m:02d}:{s:02d}"
            self._lbl_bar_cd.configure(text=txt)
            self._c_prox.configure(text=self._next_scan.strftime("%H:%M:%S"))
        elif not self._is_running:
            self._lbl_bar_cd.configure(text="")
        self.after(1000, self._tick_countdown)

    # ─── Painéis dinâmicos ────────────────────────────────────────────

    def _atualizar_solteiros(self):
        for w in self._sol_scroll.winfo_children():
            w.destroy()

        origem = self._cfg.get("pasta_origem", "")
        if origem and os.path.isdir(origem):
            ext = {".pdf", ".jpg", ".jpeg", ".png"}
            self._solteiros = [
                f for f in os.listdir(origem)
                if os.path.splitext(f)[1].lower() in ext
                and not f.startswith("temp_")
            ]

        if not self._solteiros:
            ctk.CTkLabel(self._sol_scroll,
                         text="✅  Nenhum arquivo solteiro no momento",
                         text_color="gray").pack(pady=24)
            self._c_solt.configure(text="0 aguardando")
            return

        self._c_solt.configure(text=f"{len(self._solteiros)} aguardando")
        for f in sorted(self._solteiros):
            row = ctk.CTkFrame(self._sol_scroll, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=2)
            ctk.CTkLabel(row, text="⚠️", width=26).pack(side="left")
            ctk.CTkLabel(row, text=f, anchor="w",
                         font=ctk.CTkFont(size=12)).pack(side="left")

    def _atualizar_historico(self):
        for w in self._hist_scroll.winfo_children():
            w.destroy()

        if not self._history:
            ctk.CTkLabel(self._hist_scroll,
                         text="Nenhum arquivo processado ainda",
                         text_color="gray").pack(pady=24)
            return

        for entry in self._history[:100]:
            f = ctk.CTkFrame(self._hist_scroll)
            f.pack(fill="x", padx=4, pady=3)
            f.grid_columnconfigure(2, weight=1)

            ctk.CTkLabel(f, text=entry["ts"],
                         font=ctk.CTkFont(size=11), text_color="gray",
                         width=130).grid(row=0, column=0, padx=10, pady=8)

            ctk.CTkLabel(f, text=f"✅  {entry['sucessos']} combinação(ões)",
                         font=ctk.CTkFont(size=11),
                         anchor="w").grid(row=0, column=1, padx=4, pady=8, sticky="w")

            if entry["arquivos"]:
                primeiros = ", ".join(entry["arquivos"][:2])
                if len(entry["arquivos"]) > 2:
                    primeiros += f" +{len(entry['arquivos'])-2}"
                ctk.CTkLabel(f, text=primeiros,
                             font=ctk.CTkFont(size=10), text_color="gray",
                             anchor="w").grid(row=0, column=2, padx=(4, 10), pady=8, sticky="ew")

    def _limpar_historico(self):
        self._history.clear()
        self._hoje_count = 0
        self._c_hoje.configure(text="0")
        self._atualizar_historico()

    # ─── Eventos ──────────────────────────────────────────────────────

    def _pick_folder(self, tipo: str):
        pasta = filedialog.askdirectory(title=f"Selecionar pasta de {tipo}")
        if pasta:
            if tipo == "origem":
                self._v_origem.set(pasta)
                self._cfg.set("pasta_origem", pasta)
            else:
                self._v_destino.set(pasta)
                self._cfg.set("pasta_destino", pasta)

    def _on_tema(self, value: str):
        modo = "dark" if "Escuro" in value else "light"
        ctk.set_appearance_mode(modo)
        self._cfg.set("tema", modo)

    def _on_intervalo(self, value: str):
        self._cfg.set("intervalo_minutos", int(value))
        if self._is_running:
            self._agendar()

    def _set_status_ui(self, card: str, bar: str):
        self._c_status.configure(text=card)
        self._lbl_bar_status.configure(text=bar)

    # ─── Tray & Notificações ──────────────────────────────────────────

    def _iniciar_tray(self):
        if TRAY_OK:
            try:
                self._tray = criar_icone_tray(self)
            except Exception:
                pass

    def _minimizar_para_tray(self):
        self.withdraw()

    def _notificar(self, suc: int, sol: int):
        if not self._cfg.get("notificacoes", True) or not NOTIF_OK:
            return
        try:
            msg = f"{suc} arquivo(s) combinados com sucesso."
            if sol:
                msg += f" {sol} solteiro(s) aguardando."
            toast = Notification(app_id="DocFlow",
                                 title="DocFlow — Processamento Concluído",
                                 msg=msg)
            toast.show()
        except Exception:
            pass

    def sair_aplicacao(self):
        self._is_running = False
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        self.destroy()

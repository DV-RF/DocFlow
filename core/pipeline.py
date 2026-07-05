# =====================================================================
# DOCFLOW — Orquestrador do Pipeline (core/pipeline.py)
# =====================================================================
import os
import shutil
from datetime import datetime
from typing import Callable

from utils.helpers import remover_seguro
from extractors.rh import processar_rh
from extractors.logistica import processar_logistica
from extractors.financeiro import processar_financeiro


_EXTENSOES_DOC = {".pdf", ".jpg", ".jpeg", ".png"}


def processar_arquivos(
    pasta_origem: str,
    pasta_destino: str = "",
    callback: Callable[[str], None] | None = None,
    modo_gui: bool = False,
) -> dict:
    def log(msg: str) -> None:
        if callback:
            callback(msg)
        elif not modo_gui:
            print(msg)

    if not modo_gui:
        from utils.logger import imprimir_banner
        imprimir_banner()

    if not os.path.exists(pasta_origem):
        msg = f"❌ ERRO: A pasta '{pasta_origem}' não foi encontrada."
        log(msg)
        return {"erro": msg, "sucessos": 0, "arquivos_novos": [], "arquivos_solteiros": []}

    arquivos_antes = {
        f for f in os.listdir(pasta_origem)
        if os.path.splitext(f)[1].lower() in _EXTENSOES_DOC
    }

    arquivos_na_pasta    = os.listdir(pasta_origem)
    arquivos_processados: set[str] = set()
    lixeira_inteligente: set[str]  = set()
    sucessos  = 0
    solteiros = 0

    log("🔍 Iniciando varredura na pasta...")

    # ── Módulo 1: RH ─────────────────────────────────────────────────
    try:
        sucessos += processar_rh(pasta_origem, arquivos_na_pasta, arquivos_processados)
    except Exception as e:
        log(f"⚠️ Módulo RH — arquivo problemático ignorado: {e}")

    # ── Módulo 2: Logística ──────────────────────────────────────────
    try:
        s_log, sol_log = processar_logistica(
            pasta_origem, arquivos_na_pasta, arquivos_processados, lixeira_inteligente
        )
        sucessos  += s_log
        solteiros += sol_log
    except Exception as e:
        log(f"⚠️ Módulo Logística — arquivo problemático ignorado: {e}")

    # ── Módulo 3: Financeiro ─────────────────────────────────────────
    try:
        s_fin, sol_fin = processar_financeiro(
            pasta_origem, arquivos_na_pasta, arquivos_processados, lixeira_inteligente
        )
        sucessos  += s_fin
        solteiros += sol_fin
    except Exception as e:
        log(f"⚠️ Módulo Financeiro — arquivo problemático ignorado: {e}")

    # ── Limpeza de contratos incorporados ────────────────────────────
    for contrato in lixeira_inteligente:
        remover_seguro(contrato)

    # ── Identifica arquivos novos (= combinações geradas) ────────────
    arquivos_depois = {
        f for f in os.listdir(pasta_origem)
        if os.path.splitext(f)[1].lower() in _EXTENSOES_DOC
        and not f.startswith("temp_")
    }
    arquivos_novos     = list(arquivos_depois - arquivos_antes)
    arquivos_solteiros = [f for f in arquivos_depois if f not in arquivos_novos]

    # ── Envia combinações para a pasta do mês ────────────────────────
    if pasta_destino and os.path.isdir(pasta_destino):
        for f in arquivos_novos:
            src = os.path.join(pasta_origem, f)
            dst = os.path.join(pasta_destino, f)
            try:
                if os.path.exists(dst):
                    os.remove(dst)
                shutil.move(src, dst)
                log(f"📤 Enviado: '{f}'")
            except Exception as e:
                log(f"⚠️ Não foi possível mover '{f}': {e}")
    elif pasta_destino:
        log(f"⚠️ Pasta de destino não encontrada: '{pasta_destino}'")

    resultado = {
        "sucessos":           sucessos,
        "solteiros":          solteiros,
        "arquivos_novos":     arquivos_novos,
        "arquivos_solteiros": arquivos_solteiros,
        "timestamp":          datetime.now().isoformat(),
    }

    if not modo_gui:
        from utils.logger import imprimir_resumo
        imprimir_resumo(sucessos, solteiros)
        input("Pressione ENTER para fechar o programa...")

    return resultado

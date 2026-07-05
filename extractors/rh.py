# =====================================================================
# DOCFLOW — Módulo RH (extractors/rh.py)
# =====================================================================
import os
import re
from pypdf import PdfWriter

from services.ocr_service import extrair_dados_pix, extrair_dados_emergencia
from utils.helpers import (
    remover_seguro,
    sanitizar_nome,
    formatar_valor_br,
    imagem_para_pdf_temp,
    escrever_e_renomear,
)


def processar_rh(pasta_alvo: str, arquivos_na_pasta: list, arquivos_processados: set) -> int:
    """
    Módulo RH — Folha de Pagamento.

    Identifica comprovantes PIX de salário/adiantamento e os une com os
    respectivos Recibos de Pagamento em um único PDF consolidado.

    Modifica `arquivos_processados` in-place.
    Retorna o número de pacotes gerados com sucesso.
    """
    rh_pix_files: list[str] = []
    rh_base_docs: list[str] = []

    for f in arquivos_na_pasta:
        f_upper = f.upper()
        if "CTE" in f_upper or "CT-E" in f_upper:
            continue

        # Recibo = PDF com "RC"/"RECIBO" + identificador salarial
        #          OU qualquer PDF com "COLAB" no nome (ex: "Sal Colab", "Folha Colab")
        eh_recibo = f.lower().endswith(".pdf") and (
            (("RC" in f_upper or "RECIBO" in f_upper)
             and any(k in f_upper for k in ("SAL", "ADT", "COLAB")))
            or ("COLAB" in f_upper)
        )
        eh_comprovante = (
            "SALARIAL"     in f_upper
            or "SALARIO"   in f_upper
            or "SALÁRIO"   in f_upper
            or "ADT SAL"   in f_upper
            or "LABORE"    in f_upper   # pró-labore
            or ("ADIANTAMENTO" in f_upper and "CTE" not in f_upper)
        )

        if eh_recibo:
            rh_base_docs.append(f)
            arquivos_processados.add(f)
        elif eh_comprovante and f not in rh_base_docs:
            rh_pix_files.append(f)
            arquivos_processados.add(f)

    if not rh_base_docs or not rh_pix_files:
        return 0

    total = len(rh_pix_files)
    print(f"💼 [MÓDULO RH] Montando {total} comprovante(s) + {len(rh_base_docs)} Recibo(s)...")

    merger = PdfWriter()
    soma = 0.0
    data_final: str | None = None
    arquivos_temp: list[str] = []

    for idx, pix_rh in enumerate(rh_pix_files):
        pct = int(((idx + 1) / total) * 100)
        caminho_pix = os.path.join(pasta_alvo, pix_rh)
        print(f"   ⏳ [{idx+1}/{total} - {pct}%] Lendo OCR: '{pix_rh}'...")

        d, _n, v = extrair_dados_pix(caminho_pix)
        d_em, v_em = extrair_dados_emergencia(caminho_pix)

        # Fallback de data e valor para o extrator de emergência
        if not d or d == "DATA_DESCONHECIDA":
            d = d_em
        if not v or v == "VALOR_DESCONHECIDO":
            v = v_em

        if d and d != "DATA_DESCONHECIDA" and not data_final:
            data_final = d

        if v and v != "VALOR_DESCONHECIDO":
            try:
                soma += float(v.replace(".", "").replace(",", "."))
            except ValueError:
                pass

        # Usa índice numérico no prefixo para evitar problemas com
        # nomes longos ou caracteres especiais no Windows
        try:
            temp = imagem_para_pdf_temp(caminho_pix, pasta_alvo, f"temp_rh_{idx}")
            if temp:
                merger.append(temp)
                arquivos_temp.append(temp)
            else:
                merger.append(caminho_pix)
        except Exception as e:
            print(f"   ⚠️ Arquivo ignorado (corrompido?) '{pix_rh}': {e}")
            continue

    for base_doc in rh_base_docs:
        try:
            merger.append(os.path.join(pasta_alvo, base_doc))
        except Exception as e:
            print(f"   ⚠️ Recibo ignorado (corrompido?) '{base_doc}': {e}")

    # ── Persistência ────────────────────────────────────────────────
    data_final = data_final or "DATA_DESCONHECIDA"

    # Detecta o tipo do lote: ADT (adiantamento) ou SAL (salário/pró-labore)
    _adt_kws = ("ADIANTAMENTO", "ADT SAL")
    _sal_kws = ("SALÁRIO", "SALARIO", "SALARIAL", "LABORE")
    tem_adt = any(any(k in f.upper() for k in _adt_kws) for f in rh_pix_files)
    tem_sal = any(any(k in f.upper() for k in _sal_kws) for f in rh_pix_files)

    if tem_adt and not tem_sal:
        tipo_lote = "ADT SAL COLAB"
    else:
        tipo_lote = "SAL COLAB"

    nome_final = sanitizar_nome(f"{data_final} {tipo_lote} {formatar_valor_br(soma)}.pdf")
    caminho_final = os.path.join(pasta_alvo, nome_final)
    caminho_temp_pdf = os.path.join(pasta_alvo, "temp_rh_docflow.pdf")

    try:
        merger.write(caminho_temp_pdf)
        merger.close()
    except Exception as e:
        print(f"❌ Erro ao gravar PDF de RH: {e}")
        try:
            merger.close()
        except Exception:
            pass
        return 0
    finally:
        # Garante que os temporários de imagem são sempre removidos
        for temp in arquivos_temp:
            try:
                if os.path.exists(temp):
                    os.remove(temp)
            except Exception:
                pass

    for f in rh_pix_files + rh_base_docs:
        orig = os.path.join(pasta_alvo, f)
        if orig != caminho_final:
            remover_seguro(orig)

    if os.path.exists(caminho_temp_pdf):
        try:
            if os.path.exists(caminho_final):
                os.remove(caminho_final)
            os.rename(caminho_temp_pdf, caminho_final)
        except Exception:
            pass

    print(f"✅ Pacote de RH finalizado: '{nome_final}'\n")
    return 1

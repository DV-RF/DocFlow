# =====================================================================
# DOCFLOW — Módulo Financeiro (extractors/financeiro.py)
# =====================================================================
import os
import re
import fitz
from pypdf import PdfWriter

from services.ocr_service import extrair_dados_pix, extrair_dados_emergencia, obter_texto_seguro
from utils.helpers import remover_seguro, sanitizar_nome, imagem_para_pdf_temp, formatar_valor_br


def extrair_dados_guia(caminho_pdf: str) -> tuple[str, str, str]:
    """
    Extrai VENCIMENTO, ESTADO (SEFAZ) e VALOR TOTAL de guias ICMS/DARE.
    """
    try:
        doc = fitz.open(caminho_pdf)
        texto_completo = "".join(pagina.get_text() for pagina in doc)
        texto_upper = texto_completo.upper()

        # ── Estado ──────────────────────────────────────────────────
        estado = "SEFAZ DESCONHECIDA"
        if "PARANÁ" in texto_upper or "PARANA" in texto_upper:
            estado = "SEFAZ PR"
        elif "SÃO PAULO" in texto_upper or "DARE" in texto_upper:
            estado = "SEFAZ SP"
        elif "CEARÁ" in texto_upper:
            estado = "SEFAZ CE"
        elif "ESPÍRITO SANTO" in texto_upper:
            estado = "SEFAZ ES"
        elif "BAHIA" in texto_upper:
            estado = "SEFAZ BA"
        elif "PERNAMBUCO" in texto_upper:
            estado = "SEFAZ PE"
        else:
            # Formato GNRE (Guia Nacional) não escreve o nome do estado por
            # extenso — só a sigla, que aparece logo após o rótulo
            # "Dados do Destinatário" (valor da UF Favorecida).
            m_uf = re.search(r"DESTINAT[ÁA]RIO\s*\n?\s*([A-Z]{2})\s*\n?\s*\d", texto_upper)
            if m_uf:
                estado = f"SEFAZ {m_uf.group(1)}"

        # ── Data de vencimento ───────────────────────────────────────
        data = "DATA_DESCONHECIDA"
        m_data = re.search(r"(?:VALIDADE|VENCIMENTO)[^\d]*(\d{2}/\d{2}/\d{4})", texto_upper)
        if not m_data:
            m_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo)
        if m_data:
            d = m_data.group(1).split("/")
            data = f"{d[0]}-{d[1]}-{d[2][2:]}"

        # ── Valor total (cobre tanto "Valor Total" quanto GNRE "Total a Recolher") ─
        valor = "VALOR_DESCONHECIDO"
        for chave in ("VALOR TOTAL", "TOTAL A RECOLHER", "VALOR PRINCIPAL"):
            idx_vt = texto_upper.rfind(chave)
            if idx_vt != -1:
                trecho = texto_completo[idx_vt: idx_vt + 200]
                m_valor = re.search(r"([\d]{1,3}(?:\.\d{3})*,\d{2})", trecho)
                if m_valor:
                    valor = m_valor.group(1)
                    break

        return data, estado, valor

    except Exception:
        return "ERRO", "ERRO", "ERRO"


# ─── Palavras que NÃO identificam um tipo de documento ───────────────
_IGNORE_WORDS = {
    "BOLETO", "BOL", "COMPROVANTE", "COMP", "PAGAMENTO",
    "PGTO", "PIX", "RECIBO", "NOTA", "NF", "NFSE", "NFS",
}

# Empresas/entidades tipicamente associadas a boletos e guias
_EMPRESAS_DOCUMENTO = {
    "COPASA", "CEMIG", "VIVO", "SETCOM", "FETTROMINAS",
    "SOMPO", "FGTS", "INSS", "IRPJ", "COFINS", "ICMS",
    "SEFAZ", "DARE", "DAE", "CSL", "PIS",
}

# Tipos de documento (indicam que o arquivo é a conta, não o comprovante)
_TIPOS_DOCUMENTO = {
    "FAT", "FATURA", "GUIA", "IMPOSTO", "TRIBUTO",
    "LICENCA", "LICENÇA", "CONTRATO",
}

# ─── Palavras-chave de S-Nota (recargas) ─────────────────────────────
_S_NOTA_KEYS = ("TARGET", "E-FRETE", "EFRETE", "SETCOM")


_KEYWORDS_CURTAS = {"VR"}  # códigos de 2 letras que precisam ser reconhecidos


def _get_keywords(filename: str) -> set[str]:
    """Extrai palavras significativas do nome de arquivo para emparelhamento."""
    name_only = os.path.splitext(filename)[0]
    clean = re.sub(r"\d+[-\.]\d+[-\.]\d+", "", name_only)
    clean = re.sub(r"\d+[,.]\d+", "", clean)
    clean_upper = clean.upper()
    words = re.findall(r"[A-Za-z]{3,}", clean_upper)
    # Códigos curtos conhecidos (ex: "VR") não passam no filtro de 3+ letras
    # por padrão — adiciona-os explicitamente quando aparecem como palavra isolada.
    curtas = set(re.findall(r"\b[A-Za-z]{2}\b", clean_upper)) & _KEYWORDS_CURTAS
    return {w for w in words if w not in _IGNORE_WORDS} | curtas


def _score_comprovante(filename: str, texto_upper: str) -> int:
    """
    Pontua quão provável é que um arquivo seja o comprovante (PIX)
    em vez do boleto/documento.
    Positivo = comprovante de pagamento. Negativo = documento/boleto/guia.
    """
    score = 0
    f_upper = filename.upper()

    # ── Indicadores de comprovante (positivo) ─────────────────────
    for kw in ("PIX", "COMP", "PGTO", "PAGAMENTO", "RECIBO", "COMPROVANTE"):
        if kw in f_upper:
            score += 2
    # Imagens têm maior chance de ser screenshots de comprovante
    if not filename.lower().endswith(".pdf"):
        score += 2

    # ── Indicadores de documento/boleto (negativo) ────────────────
    for kw in ("BOL", "FATURA", "CONTA", "NF", "GUIA", "DOCUMENTO"):
        if kw in f_upper:
            score -= 2
    # Tipos de documento conhecidos
    for kw in _TIPOS_DOCUMENTO:
        if kw in f_upper:
            score -= 2
    # Empresas/entidades tipicamente associadas a boletos e guias
    for kw in _EMPRESAS_DOCUMENTO:
        if kw in f_upper and filename.lower().endswith(".pdf"):
            score -= 1  # só penaliza PDF; PIX screenshot pode ter mesmo nome

    # ── Conteúdo: comprovante ──────────────────────────────────────
    for kw in ("COMPROVANTE", "EFETIVADO", "TRANSFERIDO", "ENVIO PIX",
               "PAGO", "SUCESSO", "PAGAMENTO REALIZADO"):
        if kw in texto_upper:
            score += 5

    # ── Conteúdo: documento/boleto/guia ───────────────────────────
    for kw in ("VENCIMENTO", "PAGAR ESTE DOCUMENTO", "MINISTÉRIO",
               "MULTA", "JUROS", "CNPJ DO EMPREGADOR", "CÓDIGO DE BARRAS",
               "LINHA DIGITÁVEL", "SECRETARIA", "ARRECADAÇÃO"):
        if kw in texto_upper:
            score -= 5

    return score


def _processar_s_notas(
    pasta_alvo: str,
    arquivos_fin: list,
    sucessos_ref: list,
) -> None:
    """Sub-rotina: renomeia e converte arquivos de recarga (S-Nota)."""
    s_notas = [
        f for f in arquivos_fin
        if any(kw in f.upper() for kw in _S_NOTA_KEYS)
    ]
    total = len(s_notas)
    if total == 0:
        return

    print(f"💳 [MÓDULO FINANCEIRO] {total} Recarga(s) (S-Nota) encontrada(s).")

    for idx, f in enumerate(s_notas):
        kw = next(kw for kw in _S_NOTA_KEYS if kw in f.upper())
        pct = int(((idx + 1) / total) * 100)
        caminho_pix = os.path.join(pasta_alvo, f)
        print(f"   ⏳ [{idx+1}/{total} - {pct}%] Processando OCR: '{f}'...")

        d, _n, v = extrair_dados_pix(caminho_pix)
        d_em, v_em = extrair_dados_emergencia(caminho_pix)

        if not d or d == "DATA_DESCONHECIDA":
            d = d_em
        if not v or v == "VALOR_DESCONHECIDO":
            v = v_em

        d_str = d if d and d != "DATA_DESCONHECIDA" else "DATA"
        v_str = v if v and v != "VALOR_DESCONHECIDO" else "VALOR"

        nome_limpo = sanitizar_nome(f"{d_str} REC {kw} {v_str} S-NOTA.pdf")
        caminho_final = os.path.join(pasta_alvo, nome_limpo)
        caminho_temp = os.path.join(pasta_alvo, "temp_snota_docflow.pdf")

        merger = PdfWriter()
        temp_img = None
        if caminho_pix.lower().endswith((".jpeg", ".jpg", ".png")):
            temp_img = os.path.join(pasta_alvo, f"temp_fin_{f}.pdf")
            from PIL import Image
            with Image.open(caminho_pix) as img:
                img.convert("RGB").save(temp_img)
            merger.append(temp_img)
        else:
            merger.append(caminho_pix)

        merger.write(caminho_temp)
        merger.close()

        if temp_img and os.path.exists(temp_img):
            os.remove(temp_img)
        if caminho_pix != caminho_final:
            remover_seguro(caminho_pix)

        if os.path.exists(caminho_temp):
            try:
                if os.path.exists(caminho_final):
                    os.remove(caminho_final)
                os.rename(caminho_temp, caminho_final)
            except Exception:
                pass

        arquivos_fin.remove(f)
        sucessos_ref[0] += 1


def _processar_guias_sefaz(
    pasta_alvo: str,
    arquivos_fin: list,
    sucessos_ref: list,
) -> None:
    """
    Sub-rotina: pareia comprovante PIX (ICMS/GUIA + Cte NNNN) com a Guia
    SEFAZ correspondente, gerando o nome no mesmo padrão usado em
    logística: "{data} SEFAZ {estado} Cte {numero} {valor}.pdf".

    Usa extrair_dados_guia (já existia mas nunca era chamada) para
    identificar o estado a partir do conteúdo da guia.
    """
    candidatos_pix = [
        f for f in arquivos_fin
        if re.search(r"\bICMS\b", f.upper())
        and re.search(r"CTE[\s_]*\d+", f.upper())
        and not f.upper().startswith("GUIA")
    ]
    guias = [
        f for f in arquivos_fin
        if f.lower().endswith(".pdf")
        and (f.upper().startswith("GUIA") or "SEFAZ" in f.upper())
    ]
    if not candidatos_pix or not guias:
        return

    print(f"🏛️ [MÓDULO FINANCEIRO] {len(candidatos_pix)} Guia(s) SEFAZ/ICMS encontrada(s).")

    usados_aqui = []
    for pix_f in candidatos_pix:
        m_num = re.search(r"CTE[\s_]*(\d+)", pix_f.upper())
        numero = m_num.group(1) if m_num else ""
        guia_f = next(
            (g for g in guias if numero and re.search(rf"(?<!\d){re.escape(numero)}(?!\d)", g)),
            None,
        )
        if not guia_f:
            continue

        caminho_pix  = os.path.join(pasta_alvo, pix_f)
        caminho_guia = os.path.join(pasta_alvo, guia_f)

        d_p, _n, v_p = extrair_dados_pix(caminho_pix)
        d_g, estado, v_g = extrair_dados_guia(caminho_guia)

        d_final = d_p if d_p and d_p != "DATA_DESCONHECIDA" else d_g
        v_final = v_p if v_p and v_p != "VALOR_DESCONHECIDO" else v_g
        if d_final == "DATA_DESCONHECIDA":
            d_final = "DATA"
        if v_final == "VALOR_DESCONHECIDO":
            v_final = "VALOR"

        nome_sujo = f"{d_final} {estado} Cte {numero} {v_final}.pdf"
        nome_limpo = sanitizar_nome(nome_sujo)
        caminho_final = os.path.join(pasta_alvo, nome_limpo)
        caminho_temp = os.path.join(pasta_alvo, "temp_guiasefaz_docflow.pdf")

        try:
            merger = PdfWriter()
            temp_pix = imagem_para_pdf_temp(caminho_pix, pasta_alvo, f"temp_gpix_{pix_f}")
            merger.append(temp_pix if temp_pix else caminho_pix)
            merger.append(caminho_guia)
            merger.write(caminho_temp)
            merger.close()

            if temp_pix and os.path.exists(temp_pix):
                os.remove(temp_pix)

            if caminho_pix != caminho_final:
                remover_seguro(caminho_pix)
            if caminho_guia != caminho_final:
                remover_seguro(caminho_guia)

            if os.path.exists(caminho_temp):
                if os.path.exists(caminho_final):
                    os.remove(caminho_final)
                os.rename(caminho_temp, caminho_final)

            usados_aqui.extend([pix_f, guia_f])
            sucessos_ref[0] += 1
            print(f"   ✅ Guia SEFAZ: '{nome_limpo}'")

        except Exception as e:
            print(f"   ❌ Erro Guia SEFAZ '{pix_f}': {e}")

    for f in usados_aqui:
        if f in arquivos_fin:
            arquivos_fin.remove(f)


def processar_financeiro(
    pasta_alvo: str,
    arquivos_na_pasta: list,
    arquivos_processados: set,
    lixeira_inteligente: set,
) -> tuple[int, int]:
    """
    Módulo Financeiro — Boletos, Impostos e Recargas.

    1. Processa recargas S-Nota individualmente.
    2. Usa o algoritmo "Cupido" para emparelhar comprovantes PIX com
       seus documentos-base (boletos, guias) via palavras-chave no nome.

    Retorna (sucessos, solteiros).
    """
    arquivos_fin = [
        f for f in arquivos_na_pasta
        if f not in arquivos_processados and f not in lixeira_inteligente
        # RC-prefixados são tratados exclusivamente pelo módulo RC Financeiro
        # (evita que 2 comprovantes genéricos como "Prestação de Serviço" se
        # juntem entre si por engano, deixando o RC real órfão)
        and not (re.search(r"\bRC\b", f.upper()) and f.lower().endswith(".pdf") and "CTE" not in f.upper())
    ]

    sucessos_ref = [0]  # lista mutável para uso em sub-rotinas
    _processar_s_notas(pasta_alvo, arquivos_fin, sucessos_ref)
    _processar_guias_sefaz(pasta_alvo, arquivos_fin, sucessos_ref)

    # ── Cupido Financeiro: emparelhamento por palavras-chave ─────────
    usados: set[str] = set()
    pares = 0

    for i, f1 in enumerate(arquivos_fin):
        if f1 in usados:
            continue
        kw1 = _get_keywords(f1)
        if not kw1:
            continue

        for f2 in arquivos_fin[i + 1:]:
            if f2 in usados:
                continue
            intersecao = kw1 & _get_keywords(f2)
            if not intersecao:
                continue

            # Lê conteúdo para pontuar qual é comprovante e qual é documento
            txt_f1 = obter_texto_seguro(os.path.join(pasta_alvo, f1)).upper()
            txt_f2 = obter_texto_seguro(os.path.join(pasta_alvo, f2)).upper()

            score1 = _score_comprovante(f1, txt_f1)
            score2 = _score_comprovante(f2, txt_f2)

            # Segurança: se os dois têm score negativo são dois documentos
            # (ex: NFS-e + NFS-e). Pula o par sem processar.
            if score1 < 0 and score2 < 0:
                continue
            # Segurança: se os dois têm score positivo são dois comprovantes
            # (ex: 2 PIX com descrição genérica "Prestação de Serviço" para
            # pessoas diferentes). Pula — não faz sentido juntar 2 recibos.
            if score1 > 0 and score2 > 0:
                continue

            pares += 1
            palavra_chave = next(iter(intersecao))
            print(f"🧾 [CUPIDO FIN] Par {pares} detectado ('{palavra_chave}'). Unindo...")

            if score1 >= score2:
                pix_f, bol_f = f1, f2
                txt_pix = txt_f1
            else:
                pix_f, bol_f = f2, f1
                txt_pix = txt_f2

            caminho_pix = os.path.join(pasta_alvo, pix_f)
            caminho_bol = os.path.join(pasta_alvo, bol_f)

            d, _n, v = extrair_dados_pix(caminho_pix)
            d_em, v_em = extrair_dados_emergencia(caminho_pix)

            if not d or d == "DATA_DESCONHECIDA":
                d = d_em
            if not v or v == "VALOR_DESCONHECIDO":
                v = v_em

            d_str = d if d and d != "DATA_DESCONHECIDA" else "DATA"
            v_str = v if v and v != "VALOR_DESCONHECIDO" else "VALOR"

            # Limpa a descrição extraída do nome do comprovante
            desc = os.path.splitext(pix_f)[0].upper()
            desc = re.sub(r"\d{2}[-\.]\d{2}[-\.]\d{2,4}", "", desc)
            desc = re.sub(r"\b(COMPROVANTE|COMP|PIX|PGTO|PAGAMENTO)\b", "", desc).strip()
            desc = _abreviar_desc_rc(desc)
            if "INSS" in desc:
                desc = "INSS TERC"

            # Fallback: quando OCR do PIX falha, lê o DOCUMENTO (RC/boleto)
            if d_str == "DATA" or v_str == "VALOR":
                try:
                    from services.ocr_service import obter_texto_seguro as _ots2
                    doc_text = _ots2(caminho_bol)
                    if d_str == "DATA":
                        m_d = re.search(r"(\d{2}/\d{2}/202\d)", doc_text)
                        if m_d:
                            p = m_d.group(1).split("/")
                            d_str = f"{p[0]}-{p[1]}-{p[2][2:]}"
                    if v_str == "VALOR":
                        m_vf = re.search(r"([\d]{1,3}(?:\.[\d]{3})*,[\d]{2})", bol_f)
                        if m_vf:
                            v_str = m_vf.group(1)
                        else:
                            m_vc = re.search(r"Valor\s+([\d]{1,3}(?:\.[\d]{3})*,[\d]{2})", doc_text)
                            if not m_vc:
                                m_vc = re.search(r"R\$\s*([\d]{1,3}(?:\.[\d]{3})*,[\d]{2})", doc_text)
                            if m_vc:
                                v_str = m_vc.group(1)
                except Exception:
                    pass
            nome_sujo = f"{d_str} {desc} {v_str}.pdf"
            nome_limpo = re.sub(r"\s+", " ", sanitizar_nome(nome_sujo))
            caminho_final = os.path.join(pasta_alvo, nome_limpo)
            caminho_temp = os.path.join(pasta_alvo, "temp_cupido_docflow.pdf")

            merger = PdfWriter()
            temp_pix = imagem_para_pdf_temp(caminho_pix, pasta_alvo, f"temp_pix_{pix_f}")
            temp_bol = imagem_para_pdf_temp(caminho_bol, pasta_alvo, f"temp_bol_{bol_f}")

            merger.append(temp_pix if temp_pix else caminho_pix)
            merger.append(temp_bol if temp_bol else caminho_bol)

            merger.write(caminho_temp)
            merger.close()

            for tmp in (temp_pix, temp_bol):
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)

            if caminho_pix != caminho_final:
                remover_seguro(caminho_pix)
            if caminho_bol != caminho_final:
                remover_seguro(caminho_bol)

            if os.path.exists(caminho_temp):
                try:
                    if os.path.exists(caminho_final):
                        os.remove(caminho_final)
                    os.rename(caminho_temp, caminho_final)
                except Exception:
                    pass

            usados.add(f1)
            usados.add(f2)
            sucessos_ref[0] += 1
            break

    solteiros = len([f for f in arquivos_fin if f not in usados])

    # ── Módulo RC Financeiro: pares comprovante + RC sem CT-e ────────
    # Trata funcionários: DIAS TRAB, PREST SERV, etc.
    # Comprovante (imagem/PDF) + RC com palavras-chave em comum
    sucessos_ref[0] += _processar_rc_financeiro(
        pasta_alvo, arquivos_na_pasta, arquivos_processados
    )

    return sucessos_ref[0], solteiros


_IGNORE_RC = {
    "RC", "SAL", "ADT", "COM", "POR", "SEM", "DOS", "DAS",
    "PDF", "JPEG", "JPG", "PNG", "CTE", "DESC", "PIX",
}
_EXT_DOC = {".pdf", ".jpg", ".jpeg", ".png"}

# Palavras por extenso que devem virar a abreviação já usada no padrão
# de nomenclatura do projeto (ex: "AL MARCIO", "PASS MARCIO")
_ABREVIACOES_RC = {
    "ALIMENTAÇÃO": "AL",
    "ALIMENTACAO": "AL",
    "PASSAGEM": "PASS",
}


def _abreviar_desc_rc(desc: str) -> str:
    """Substitui palavras por extenso pela abreviação padrão do projeto."""
    for completa, abreviada in _ABREVIACOES_RC.items():
        desc = re.sub(rf"\b{completa}\b", abreviada, desc, flags=re.IGNORECASE)
    return desc


def _processar_rc_financeiro(
    pasta_alvo: str,
    arquivos_na_pasta: list,
    arquivos_processados: set,
) -> int:
    """
    Módulo Financeiro RC — Funcionários sem CT-e.

    Detecta arquivos RC em qualquer posição do nome (inclusive com data prefixada)
    e pareia com TODOS os comprovantes que compartilhem palavras-chave.
    Suporta múltiplos comprovantes por RC (ex: AL SEM + PASS SEM na mesma semana).
    """
    # RC: "RC" em qualquer posição do nome, excluindo arquivos com CT-e (logística)
    rcs = [
        f for f in arquivos_na_pasta
        if f not in arquivos_processados
        and re.search(r"\bRC\b", f.upper()) is not None
        and f.lower().endswith(".pdf")
        and "CTE" not in f.upper()
        and not f.upper().startswith("CF_")
    ]

    if not rcs:
        return 0

    sucessos = 0

    for rc in rcs:
        kws_rc = {
            w for w in re.findall(r"[A-Za-z\u00C0-\u00FF]{3,}", rc.upper())
            if w not in _IGNORE_RC
        }
        if not kws_rc:
            continue

        caminho_rc = os.path.join(pasta_alvo, rc)

        # Extrai o Fornecedor do CONTEÚDO do RC (mais confiável que o nome
        # do arquivo quando a descrição é genérica, ex: "Prestação de Serviço",
        # que pode se repetir para várias pessoas diferentes)
        rc_texto = obter_texto_seguro(caminho_rc)
        fornecedor = ""
        m_forn = re.search(r"Fornecedor\s+([\s\S]+?)\s*Conta\s*Dep", rc_texto, re.IGNORECASE)
        if m_forn:
            fornecedor = re.sub(r"\s+", " ", m_forn.group(1)).strip()
        fornecedor_primeiro_nome = fornecedor.split()[0].upper() if fornecedor else ""

        # Encontra o MELHOR comprovante. Pontuação:
        #   +1 por palavra-chave em comum no NOME do arquivo
        #   +100 se o nome do Fornecedor aparecer no CONTEÚDO do comprovante
        # (o bônus de conteúdo resolve o caso de 2 PIX com descrição genérica
        # idêntica, ex: "Prestação de Serviço", onde só o conteúdo distingue
        # quem realmente é o destinatário)
        best_match  = None
        best_score  = 0
        for f in arquivos_na_pasta:
            if f in arquivos_processados or f == rc:
                continue
            if os.path.splitext(f)[1].lower() not in _EXT_DOC:
                continue
            if re.search(r"\bRC\b", f.upper()) and f.lower().endswith(".pdf"):
                continue
            if f.upper().startswith("CF_"):
                continue

            kws_f = {
                w for w in re.findall(r"[A-Za-z\u00C0-\u00FF]{3,}", f.upper())
                if w not in _IGNORE_RC
            }
            score = len(kws_rc & kws_f)

            if fornecedor_primeiro_nome:
                caminho_f = os.path.join(pasta_alvo, f)
                # Arquivo pode já ter sido consumido (renomeado/movido) por
                # uma etapa anterior no mesmo processamento (S-Nota, Guia
                # SEFAZ, Cupido). Pula silenciosamente em vez de tentar ler.
                if os.path.exists(caminho_f):
                    texto_f = obter_texto_seguro(caminho_f).upper()
                    if fornecedor_primeiro_nome in texto_f:
                        score += 100

            if score > best_score:
                best_score = score
                best_match = f

        if not best_match:
            continue

        matches = [best_match]  # single-match

        print(f"   👔 [RC FINANCEIRO] {len(matches)} comprovante(s) + \'{rc}\'")

        # Descrição = RC sem prefixo "RC" (pode estar no meio do nome) e sem valor
        desc = re.sub(r"(?i)\bRC\b", "", os.path.splitext(rc)[0]).strip()
        desc = re.sub(r"\d{2}[-\.]\d{2}[-\.]\d{2,4}", "", desc).strip()
        desc = re.sub(r"\s*\d{1,3}(?:\.\d{3})*,\d{2}\s*", " ", desc).strip()
        desc = re.sub(r"\s+", " ", desc).strip()
        desc = _abreviar_desc_rc(desc)

        # Garante que o nome do fornecedor apareça na nomeação final
        # (evita arquivos genéricos como "PRESTAÇÃO DE SERVIÇO.pdf" sem
        # identificar quem recebeu o pagamento)
        if fornecedor_primeiro_nome and fornecedor_primeiro_nome not in desc.upper():
            desc = f"{desc} {fornecedor_primeiro_nome}".strip()

        # Data e valor: agrega de todos os comprovantes
        soma   = 0.0
        data_f = "DATA"
        for comp in matches:
            caminho_comp = os.path.join(pasta_alvo, comp)
            m_data = re.search(r"(\d{2}[-\.]\d{2}[-\.]\d{2,4})", comp)
            if m_data and data_f == "DATA":
                data_f = m_data.group(1).replace(".", "-")
            else:
                from services.ocr_service import extrair_dados_pix as _edp
                d_pix, _, v_pix = _edp(caminho_comp)
                if d_pix and d_pix != "DATA_DESCONHECIDA" and data_f == "DATA":
                    data_f = d_pix
                if v_pix and v_pix != "VALOR_DESCONHECIDO":
                    try:
                        soma += float(v_pix.replace(".", "").replace(",", "."))
                    except Exception:
                        pass

        # Se soma = 0, tenta pegar do conteúdo do RC
        if soma == 0:
            from services.ocr_service import obter_texto_seguro as _ots
            rc_txt = _ots(caminho_rc)
            m_rc_v = re.search(r"Valor\s+([\d]{1,3}(?:\.\d{3})*,\d{2})", rc_txt)
            if m_rc_v:
                try:
                    soma = float(m_rc_v.group(1).replace(".", "").replace(",", "."))
                except Exception:
                    pass

        valor = formatar_valor_br(soma) if soma > 0 else "VALOR"

        nome_limpo    = sanitizar_nome(f"{data_f} {desc} {valor}.pdf")
        caminho_final = os.path.join(pasta_alvo, nome_limpo)
        caminho_temp  = os.path.join(pasta_alvo, "temp_rcfin_docflow.pdf")

        try:
            merger   = PdfWriter()
            temps    = []

            # Adiciona todos os comprovantes primeiro
            for comp in matches:
                caminho_comp = os.path.join(pasta_alvo, comp)
                if caminho_comp.lower().endswith((".jpeg", ".jpg", ".png")):
                    from PIL import Image
                    tmp = os.path.join(pasta_alvo, f"temp_rc_{comp}.pdf")
                    with Image.open(caminho_comp) as img:
                        img.convert("RGB").save(tmp)
                    merger.append(tmp)
                    temps.append(tmp)
                else:
                    merger.append(caminho_comp)

            # Adiciona o RC por último
            merger.append(caminho_rc)

            merger.write(caminho_temp)
            merger.close()

            for tmp in temps:
                if os.path.exists(tmp):
                    os.remove(tmp)

            from utils.helpers import remover_seguro as _rs
            for comp in matches:
                _rs(os.path.join(pasta_alvo, comp))
            _rs(caminho_rc)

            if os.path.exists(caminho_temp):
                try:
                    if os.path.exists(caminho_final):
                        os.remove(caminho_final)
                    os.rename(caminho_temp, caminho_final)
                except Exception:
                    pass

            for comp in matches:
                arquivos_processados.add(comp)
            arquivos_processados.add(rc)
            sucessos += 1
            print(f"   ✅ RC Financeiro: \'{nome_limpo}\'")

        except Exception as e:
            print(f"   ❌ Erro RC Financeiro: {e}")

    return sucessos

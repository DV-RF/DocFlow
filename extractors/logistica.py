# =====================================================================
# DOCFLOW — Módulo Logística (extractors/logistica.py)
# =====================================================================
import os
import re
import fitz
from pypdf import PdfWriter

from services.ocr_service import extrair_dados_pix, obter_texto_seguro
from utils.helpers import remover_seguro, sanitizar_nome, imagem_para_pdf_temp


# ─── Tabela de normalização de mnemônicos ────────────────────────────
_VOCAB_MNEMONICO: dict[str, str] = {
    "SALDO":          "SAL",
    "ADIANTAMENTO":   "ADT",
    "DESCARGA":       "DESC",
    "DESLOCAMENTO":   "DESLOC",
    "RESTANTE":       "REST SAL",    # ex: "Restante Saldo Cte XXXX"
    "DIARIA":         "DIA",
    "DIÁRIA":         "DIA",
    "LICENCA":        "LIC",
    "LICENÇA":        "LIC",
    "FRETE":          "FRT",         # ex: "Frete OC 46"
    # ── Variações de grafia ──────────────────────────────────────────
    "DESLC":          "DESLOC",      # ex: "DESLC OC 38 ROGELIO"
    "ANT.SAL":        "ADT",         # ex: "ANT.SAL Cte 3762 JOEL"
    "ANT":            "ADT",         # ex: "ANT SAL Cte XXXX"
    # ── Serviços de carga e paletização ─────────────────────────────
    "PALETIZAÇÃO":    "PALET",       # ex: "Paletização Cte 3619"
    "PALETIZACAO":    "PALET",
    "CHAPA":          "CHAPA",       # ex: "Chapa e Paletização Cte 3637"
}

# Tipos conhecidos usados para busca em qualquer posição do nome
# (resolve "JOAO ADT Cte 1234" → primeiro word = JOAO, tipo = ADT)
_TIPOS_DIRETOS: set[str] = {
    "ADT", "SAL", "DESC", "DESCARGA", "DESLOC", "DESLC",
    "DIA", "LIC", "OC", "FRT", "CHAPA", "PALET", "REST",
}

# Padrões compostos detectados antes da extração por primeira palavra
_PADROES_COMPOSTOS: list[tuple[str, str]] = [
    ("REST SAL",  "REST SAL"),  # "REST SAL Cte 4019"
    ("ADT SAL",   "ADT"),       # "ADT SAL Cte XXXX"
    ("FRETE OC",  "OC"),        # "Frete OC 46" — Ordem de Carregamento
    ("CHAPA E",   "CHAPA"),     # "Chapa e Paletização Cte XXXX"
    ("ANT.SAL",   "ADT"),       # "ANT.SAL Cte XXXX JOEL" — Antecipação Salarial
    ("ANT SAL",   "ADT"),       # sem ponto
]


def extrair_dados_contrato(caminho_pdf: str, mnemonico: str) -> tuple[str, str, str]:
    """
    Extrai DATA, NOME e VALOR de Contratos Bsoft via análise geométrica de blocos.
    """
    try:
        doc = fitz.open(caminho_pdf)
        texto_completo = ""
        for pagina in doc:
            blocos = pagina.get_text("blocks")
            blocos.sort(key=lambda b: (round(b[1] / 10), b[0]))
            for b in blocos:
                texto_completo += b[4].replace("\n", " ").strip() + "\n"

        # ── DATA ────────────────────────────────────────────────────
        data = "DATA_DESCONHECIDA"
        # 1ª prioridade: "Impresso em: 09 de Junho de 2026" = data de geração/pagamento
        _MESES = {
            "JANEIRO":1,"FEVEREIRO":2,"MARÇO":3,"ABRIL":4,"MAIO":5,"JUNHO":6,
            "JULHO":7,"AGOSTO":8,"SETEMBRO":9,"OUTUBRO":10,"NOVEMBRO":11,"DEZEMBRO":12
        }
        m_imp = re.search(
            r"Impresso em:\s*(\d+)\s+de\s+(\w+)\s+de\s+(\d{4})",
            texto_completo, re.IGNORECASE
        )
        if m_imp:
            dia  = int(m_imp.group(1))
            mes  = _MESES.get(m_imp.group(2).upper(), 0)
            ano  = m_imp.group(3)
            if mes:
                data = f"{dia:02d}-{mes:02d}-{ano[2:]}"
        # 2ª prioridade: Dt. Fiscal ou qualquer data DD/MM/AAAA
        if data == "DATA_DESCONHECIDA":
            m_data = re.search(r"Dt\. Fiscal[\s\S]*?(\d{2}/\d{2}/\d{4})", texto_completo)
            if not m_data:
                m_data = re.search(r"(\d{2}/\d{2}/20\d{2})", texto_completo)
            if m_data:
                d = m_data.group(1).split("/")
                data = f"{d[0]}-{d[1]}-{d[2][2:]}"

        # ── NOME (Antivírus de campos vazios) ───────────────────────
        _IGNORADOS = {"IE", "CHAVE", "PIX", "ENDEREÇO", "OP"}
        nome = "RECEBEDOR_DESCONHECIDO"
        for match in re.finditer(r"Nome/(?:CNPJ|CPF):[\s]*([^\n]+)", texto_completo):
            linha_limpa = re.sub(r'[\d\.\-\/:]+', ' ', match.group(1)).strip()
            palavras = [p for p in linha_limpa.split() if p.upper() not in _IGNORADOS]
            if palavras:
                nome = palavras[0]
                break

        # ── VALOR ────────────────────────────────────────────────────────
        valor = "VALOR_DESCONHECIDO"
        palavra_chave = (
            "Adiantamento" if mnemonico == "ADT"
            else ("Saldo" if mnemonico == "SAL" else "Líquido")
        )
        # O PyMuPDF às vezes extrai "VALOR =R$ Saldo" (valor antes do label)
        # e às vezes "Saldo =R$ VALOR" (normal). Buscamos os dois padrões.
        # Padrão A: "VALUE =R$ KEYWORD" (valor antes do label)
        m_antes = re.search(
            rf"([\d]{{1,3}}(?:\.[\d]{{3}})*,[\d]{{2}})\s*=R\$\s*{palavra_chave}",
            texto_completo, re.IGNORECASE,
        )
        # Padrão B: "KEYWORD =R$ VALUE" (valor depois do label)
        m_depois = re.search(
            rf"{palavra_chave}\s*=R\$\s*([\d]{{1,3}}(?:\.[\d]{{3}})*,[\d]{{2}})",
            texto_completo, re.IGNORECASE,
        )
        for m in (m_antes, m_depois):
            if m:
                v = m.group(1)
                if v != "0,00":
                    valor = v
                    break
        # Fallback: qualquer número na janela em torno do keyword
        if valor == "VALOR_DESCONHECIDO":
            idx_kw = texto_completo.rfind(palavra_chave)
            if idx_kw != -1:
                start = max(0, idx_kw - 60)
                trecho = texto_completo[start:idx_kw + 60]
                nums = re.findall(r"[\d]{1,3}(?:\.[\d]{3})*,[\d]{2}", trecho)
                validos = [n for n in nums if n != "0,00"]
                if validos:
                    valor = validos[-1]  # último = mais próximo do keyword

        return data, nome, valor

    except Exception as e:
        print(f"❌ Erro ao ler o contrato '{caminho_pdf}': {e}")
        return "ERRO", "ERRO", "ERRO"


def _numero_exato_em(numero: str, texto: str) -> bool:
    """
    Verifica se `numero` aparece como número COMPLETO em `texto`,
    e não apenas como substring de um número maior.
    Ex: "49" não deve casar com "4249" (CF_4249.pdf), mas deve casar
    com "OC_49" (CF_OC_49.pdf).
    """
    return re.search(rf"(?<!\d){re.escape(numero)}(?!\d)", texto) is not None


def _resolver_mnemonico(nome_base_upper: str, data_imagem: str | None) -> str:
    """
    Traduz o nome do arquivo para o mnemônico interno.

    Ordem de busca:
    1. Padrões compostos (REST SAL, FRETE OC, CHAPA E…)
    2. Primeira palavra no vocab
    3. Qualquer palavra no nome → resolve "JOAO ADT Cte 1234"
    """
    sem_data = re.sub(r"^(\d{2}[-\.]\d{2}[-\.]\d{2,4})\s*", "", nome_base_upper).strip()

    # 1. Padrões compostos
    for padrao, mnemonico in _PADROES_COMPOSTOS:
        if sem_data.startswith(padrao):
            return mnemonico

    palavras = sem_data.split()
    bruto    = palavras[0] if palavras else ""

    # 2. Primeira palavra
    if bruto in _VOCAB_MNEMONICO:
        return _VOCAB_MNEMONICO[bruto]

    # 3. Qualquer palavra no nome (nome antes do tipo)
    for palavra in palavras[1:]:
        if palavra in _VOCAB_MNEMONICO:
            return _VOCAB_MNEMONICO[palavra]
        if palavra in _TIPOS_DIRETOS:
            return palavra

    return bruto


def processar_logistica(
    pasta_alvo: str,
    arquivos_na_pasta: list,
    arquivos_processados: set,
    lixeira_inteligente: set,
) -> tuple[int, int]:
    """
    Módulo Logística — CT-e e Fretes.

    Emparelha cada comprovante de frete (PIX/imagem) com seu contrato
    base (CF_ ou RC) e gera um PDF único por operação.

    Modifica `arquivos_processados` e `lixeira_inteligente` in-place.
    Retorna (sucessos, solteiros).
    """
    arquivos_logistica = [
        f for f in arquivos_na_pasta
        if f not in arquivos_processados
        # Arquivos ICMS/SEFAZ pertencem ao módulo Financeiro, mesmo contendo
        # "Cte NNNN" no nome — excluí-los aqui evita que fiquem marcados
        # como "processados" sem nunca terem sido de fato unidos.
        and "ICMS" not in f.upper()
        and (
            "CTE" in f.upper()
            or f.upper().startswith("CF_")
            or f.upper().startswith("RC")
            or re.search(r"OC\s*\d+", f.upper()) is not None   # Ordem de Carregamento
        )
    ]

    arquivos_pix_log = [f for f in arquivos_logistica if not f.upper().startswith(("RC", "CF_"))]
    pdfs_base_log = [
        f for f in arquivos_logistica
        if f not in arquivos_pix_log
        and (
            f.lower().endswith(".pdf")
            # RC de descarga pode ser uma FOTO do recibo físico (.jpg/.jpeg/.png),
            # não só PDF — o prefixo "RC" já garante que não é PIX.
            or (f.upper().startswith("RC") and f.lower().endswith((".jpg", ".jpeg", ".png")))
        )
    ]

    total = len(arquivos_pix_log)
    if total == 0:
        return 0, 0

    print(f"🚛 [MÓDULO LOGÍSTICA] {total} comprovante(s) de frete encontrado(s).")

    sucessos = 0
    solteiros = 0

    for idx, pix in enumerate(arquivos_pix_log):
        pct = int(((idx + 1) / total) * 100)
        arquivos_processados.add(pix)

        nome_base = os.path.splitext(pix)[0]
        nome_upper = nome_base.upper()

        m_data = re.search(r"^(\d{2}[-\.]\d{2}[-\.]\d{2,4})", nome_base)
        data_imagem = m_data.group(1).replace(".", "-") if m_data else None

        mnemonico = _resolver_mnemonico(nome_upper, data_imagem)

        # Extrai números do CT-e ou OC no nome do arquivo
        # Ex: "SAL Cte 4011 4012"   → prefixo="Cte", numeros=["4011","4012"]
        # Ex: "ADT Cte 4150 A 4135" → prefixo="Cte", numeros=["4150","4135"]
        # Ex: "Frete OC 46"          → prefixo="OC",  numeros=["46"]
        m_cte_bloco = re.search(r"CTE\s*([\dA\s]+)", nome_upper)
        m_oc_bloco  = re.search(r"OC\s*(\d+)",     nome_upper)

        if m_cte_bloco:
            bloco_cte      = m_cte_bloco.group(1).strip()
            numeros        = re.findall(r"\d+", bloco_cte)
            texto_cte_desc = re.sub(r"\s+", " ", bloco_cte).strip()
            prefixo_doc    = "Cte"
        elif m_oc_bloco:
            numeros        = [m_oc_bloco.group(1)]
            texto_cte_desc = m_oc_bloco.group(1)
            prefixo_doc    = "OC"
        else:
            m_num          = re.search(r"(\d+)(?=[^\d]|$)", nome_base[::-1])
            numeros        = [m_num.group(1)[::-1]] if m_num else []
            texto_cte_desc = numeros[0] if numeros else ""
            prefixo_doc    = "Cte"
        numero = numeros[0] if numeros else ""

        # ── Busca pelo contrato base correspondente ──────────────────
        contrato_real: str | None = None
        for pdf in pdfs_base_log:
            pdf_up = pdf.upper().replace(" ", "")
            # Tenta casar com QUALQUER número extraído do nome
            # (cobre casos como "SAL Cte 4011 4012" com contrato CF_4012)
            match_cf = (mnemonico in ("ADT", "SAL", "CF", "DESLOC", "REST SAL", "DIA", "LIC",
                                         "DESC", "DESCARGA", "OC", "FRT", "CHAPA", "PALET")
                        and "CF_" in pdf_up
                        and any(_numero_exato_em(n, pdf_up) for n in numeros))
            match_rc = (mnemonico in ("DESC", "DESCARGA")
                        and "RC" in pdf_up
                        and any(_numero_exato_em(n, pdf_up) for n in numeros))
            if match_cf or match_rc:
                contrato_real = pdf
                break

        if not contrato_real:
            solteiros += 1
            continue

        arquivos_processados.add(contrato_real)
        caminho_pix = os.path.join(pasta_alvo, pix)
        caminho_contrato = os.path.join(pasta_alvo, contrato_real)

        # O nome do arquivo PIX pode trazer só o PRIMEIRO Cte (ex: "Saldo
        # Cte 4168" mesmo quando o pagamento cobre Cte 4168 E 4169). O
        # contrato PDF sempre lista TODOS os CT-e reais na seção "Relação de
        # Documentos" — usamos essa lista completa como fonte da verdade.
        # (Não se aplica a RC em foto — recibo físico não tem esse padrão.)
        if prefixo_doc == "Cte" and contrato_real.lower().endswith(".pdf"):
            texto_contrato_raw = obter_texto_seguro(caminho_contrato)
            todos_ctes = re.findall(r"CT-e\s*/\s*(\d+)", texto_contrato_raw)
            if todos_ctes:
                vistos = []
                for n in todos_ctes:
                    if n not in vistos:
                        vistos.append(n)
                texto_cte_desc = ", ".join(vistos)

        print(f"   ▶ [{idx+1}/{total} - {pct}%] Grampeando: '{pix}'...")

        try:
            texto_cte = f"{prefixo_doc} {texto_cte_desc}"

            if mnemonico in ("ADT", "SAL", "CF", "DESLOC", "DESC", "DESCARGA", "DIA", "LIC", "PALET", "CHAPA", "OC", "FRT", "REST SAL"):
                d_p, n_p, v_p = extrair_dados_pix(caminho_pix)
                d_c, n_c, v_c = extrair_dados_contrato(caminho_contrato, mnemonico)
                # Prioridade: PIX > contrato "Impresso em" > nome do arquivo
                # (d_c agora usa "Impresso em" = data real de pagamento, mais confiável que o filename)
                if d_p and d_p != "DATA_DESCONHECIDA":
                    d_final = d_p
                elif d_c and d_c != "DATA_DESCONHECIDA":
                    d_final = d_c
                else:
                    d_final = data_imagem or "DATA_DESCONHECIDA"
                n_final = n_p if n_p and n_p != "NOME_DESCONHECIDO" else n_c
                v_final = v_p if v_p and v_p != "VALOR_DESCONHECIDO" else v_c
                # Evita duplicação: "OC OC 46" → "OC 46"
                # (ocorre quando mnemonico == prefixo_doc, ex: FRETE OC → mnemonico="OC", texto_cte="OC 46")
                if mnemonico == prefixo_doc:
                    nome_sujo = f"{d_final} {texto_cte} {n_final} {v_final}"
                else:
                    nome_sujo = f"{d_final} {mnemonico} {texto_cte} {n_final} {v_final}"

            else:
                nome_sujo = nome_base

            nome_limpo = sanitizar_nome(nome_sujo) + ".pdf"
            caminho_final = os.path.join(pasta_alvo, nome_limpo)
            caminho_temp = os.path.join(pasta_alvo, "temp_log_docflow.pdf")

            merger = PdfWriter()
            temp_img = imagem_para_pdf_temp(caminho_pix, pasta_alvo, f"temp_{nome_base}")
            if temp_img:
                merger.append(temp_img)
            else:
                merger.append(caminho_pix)

            # O contrato/RC também pode ser uma foto (.jpg/.jpeg/.png) — mesmo
            # tratamento de conversão usado para o PIX.
            temp_contrato = imagem_para_pdf_temp(
                caminho_contrato, pasta_alvo, f"temp_ctr_{os.path.splitext(contrato_real)[0]}"
            )
            if temp_contrato:
                merger.append(temp_contrato)
            else:
                merger.append(caminho_contrato)

            merger.write(caminho_temp)
            merger.close()

            if temp_img and os.path.exists(temp_img):
                os.remove(temp_img)
            if temp_contrato and os.path.exists(temp_contrato):
                os.remove(temp_contrato)

            if caminho_pix != caminho_final:
                remover_seguro(caminho_pix)
            lixeira_inteligente.add(caminho_contrato)

            if os.path.exists(caminho_temp):
                try:
                    if os.path.exists(caminho_final):
                        os.remove(caminho_final)
                    os.rename(caminho_temp, caminho_final)
                except Exception:
                    pass

            sucessos += 1

        except Exception as e:
            print(f"❌ Erro Logística '{pix}': {e}")

    print("")
    return sucessos, solteiros

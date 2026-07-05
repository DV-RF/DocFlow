# =====================================================================
# DOCFLOW — Serviço de OCR (services/ocr_service.py)
# =====================================================================
import os
import re
import fitz
from PIL import Image

# ─── Inicialização do Tesseract ──────────────────────────────────────
try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    OCR_DISPONIVEL = True
except Exception:
    OCR_DISPONIVEL = False


def _ocr_imagem(img) -> str:
    """
    Roda o Tesseract com fallback de idioma: tenta 'por' primeiro
    (mais preciso para nomes/acentos), e se a língua não estiver
    instalada no Windows, cai para 'eng' em vez de falhar silenciosamente.
    """
    try:
        return pytesseract.image_to_string(img, lang="por")
    except Exception as e:
        print(f"   ⚠️ OCR 'por' falhou ({e}). Tentando fallback 'eng'...")
        try:
            return pytesseract.image_to_string(img, lang="eng")
        except Exception as e2:
            print(f"   ❌ OCR 'eng' também falhou: {e2}")
            return ""


def obter_texto_seguro(caminho_arquivo: str) -> str:
    """
    Lê o texto de um PDF ou imagem.
    Fallback automático para OCR quando o PDF não contém texto nativo.
    """
    # Arquivo pode já ter sido consumido (renomeado/movido) por uma etapa
    # anterior no mesmo processamento — não é um erro real, só ausência.
    if not os.path.exists(caminho_arquivo):
        return ""
    txt = ""
    try:
        if caminho_arquivo.lower().endswith(".pdf"):
            with fitz.open(caminho_arquivo) as doc:
                txt = "".join(page.get_text() for page in doc)
                if len(txt.strip()) < 15 and OCR_DISPONIVEL:
                    txt = ""
                    for page in doc:
                        # DPI maior melhora a leitura de telas de celular fotografadas/PDF
                        pixmap = page.get_pixmap(dpi=200)
                        img = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                        txt += _ocr_imagem(img)
        elif OCR_DISPONIVEL:
            with Image.open(caminho_arquivo) as img:
                txt = _ocr_imagem(img)
    except Exception as e:
        print(f"   ⚠️ Falha ao ler '{os.path.basename(caminho_arquivo)}': {e}")
    return txt


def extrair_dados_emergencia(caminho_arquivo: str) -> tuple[str | None, str | None]:
    """
    Extrator Força Bruta: tenta extrair DATA e VALOR de qualquer documento
    usando heurísticas amplas. Usado como fallback quando os extratores
    específicos falham.
    """
    txt = obter_texto_seguro(caminho_arquivo)
    d_found: str | None = None
    v_found: str | None = None

    try:
        # DATA — prefere datas próximas a palavras-chave de pagamento
        padrao_ctx = (
            r"(?:pagamento|transferido|gerado|efetivado|pago|data)"
            r"[\s\S]{0,500}?(\d{2}[-/\.]\d{2}[-/\.]202\d)"
        )
        m = re.search(padrao_ctx, txt, re.IGNORECASE)
        if not m:
            m = re.search(r"(\d{2}[-/\.]\d{2}[-/\.]202\d)", txt)
        if m:
            p = re.split(r"[-/\.]", m.group(1))
            d_found = f"{p[0]}-{p[1]}-{p[2][2:]}"

        # VALOR — prefere padrão R$ primeiro, depois genérico
        m_val = re.search(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", txt, re.IGNORECASE)
        if not m_val:
            m_val = re.search(r"valor[\s\S]{0,100}?(\d{1,3}(?:\.\d{3})*,\d{2})", txt, re.IGNORECASE)
        if m_val:
            v_found = m_val.group(1)
    except Exception:
        pass

    return d_found, v_found


def extrair_dados_pix(caminho_arquivo: str) -> tuple[str | None, str | None, str | None]:
    """
    Extrai DATA, NOME e VALOR de comprovantes PIX (PDF nativo, PDF-envelope ou imagem).
    Retorna (None, None, None) se o OCR não estiver disponível e o arquivo não for PDF de texto.
    """
    texto = obter_texto_seguro(caminho_arquivo)

    # Sem texto e sem OCR disponível para imagens → não há o que processar
    if not texto.strip() and not OCR_DISPONIVEL:
        return None, None, None

    # ── DATA — múltiplos padrões SICOOB (PIX e boleto) ──────────────
    data = "DATA_DESCONHECIDA"
    # Padrão 1: PIX SICOOB ("Transferido em 09/06/2026")
    m_data = re.search(r"(?:Transferido|Efetuado|Pago)\s+em\s+(\d{2}/\d{2}/202\d)", texto, re.IGNORECASE)
    if not m_data:
        # Padrão 2: boleto SICOOB ("Data do pagamento 08/06/2026")
        m_data = re.search(r"Data\s+do\s+pagamento\s+(\d{2}/\d{2}/202\d)", texto, re.IGNORECASE)
    if not m_data:
        # Padrão 3: Vencimento / Data genérica
        m_data = re.search(r"(?:Vencimento|Emissão|Entrada)\s+(\d{2}/\d{2}/202\d)", texto, re.IGNORECASE)
    if not m_data:
        # Padrão 4: qualquer data DD/MM/202X no texto
        m_data = re.search(r"(\d{2}/\d{2}/202\d)", texto)
    if m_data:
        d = m_data.group(1).split("/")
        data = f"{d[0]}-{d[1]}-{d[2][2:]}"

    # ── VALOR — extração robusta para SICOOB e outros bancos ─────────
    valor = "VALOR_DESCONHECIDO"
    # Padrão 1: valor logo após cabeçalho SICOOB ("Comprovante de envio Pix\nR$ 660,33")
    m_valor = re.search(
        r"Comprovante\s+de\s+envio\s+Pix\s+R\$\s*([\d]{1,3}(?:\.\d{3})*,\d{2})",
        texto, re.IGNORECASE
    )
    if not m_valor:
        # Padrão 2: R$ no início de linha (PDF nativo SICOOB)
        m_valor = re.search(r"^\s*R\$\s*([\d]{1,3}(?:\.\d{3})*,\d{2})", texto, re.MULTILINE)
    if not m_valor:
        # Padrão 3: R$ com possível espaço interno (OCR lê "R $ 660,33" ou "RS 660,33")
        m_valor = re.search(r"R[\s\$S]\$?\s*([\d]{1,3}(?:\.\d{3})*,\d{2})", texto)
    if not m_valor:
        # Padrão 4: "Valor do documento/total R$ X" (SICOOB boleto/DAE)
        m_valor = re.search(
            r"Valor\s+(?:do\s+)?(?:documento|total)\s+R\$\s*([\d]{1,3}(?:\.\d{3})*,\d{2})",
            texto, re.IGNORECASE
        )
    if not m_valor:
        # Padrão 5: qualquer "R$" no texto
        m_valor = re.search(r"R\$[\s\n]*([\d]{1,3}(?:\.\d{3})*,\d{2})", texto)
    if m_valor:
        valor = m_valor.group(1)

    # ── NOME ────────────────────────────────────────────────────────
    nome = "NOME_DESCONHECIDO"
    linhas = [linha.strip() for linha in texto.split("\n") if linha.strip()]
    for i, linha in enumerate(linhas):
        linha_upper = linha.upper()
        if linha_upper.startswith("NOME"):
            # "NOME" em linha isolada → nome está na próxima linha
            if linha_upper == "NOME" and (i + 1) < len(linhas):
                nome_sujo = linhas[i + 1]
            else:
                nome_sujo = linha[4:].strip()

            if nome_sujo and "CPF" not in nome_sujo.upper() and "CNPJ" not in nome_sujo.upper():
                # Quando a chave Pix é CNPJ, o app mostra os dígitos antes
                # do nome (ex: "12 345 678 JOAO DA SILVA").
                # Ignora tokens puramente numéricos e pega a primeira
                # palavra que realmente tem letras.
                palavras = nome_sujo.split()
                nome = next(
                    (p for p in palavras if any(c.isalpha() for c in p)),
                    palavras[0] if palavras else "NOME_DESCONHECIDO",
                ).strip()
                break

    return data, nome, valor

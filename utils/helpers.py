# =====================================================================
# DOCFLOW — Helpers (utils/helpers.py)
# =====================================================================
import os
import re
from PIL import Image
from pypdf import PdfWriter
from send2trash import send2trash


def remover_seguro(caminho: str) -> None:
    """
    Envia o arquivo para a Lixeira do Windows (reversível).
    Se não conseguir, avisa e deixa o arquivo no lugar — nunca apaga permanentemente.
    """
    if not os.path.exists(caminho):
        return
    try:
        send2trash(caminho)
    except Exception as e:
        print(
            f"   ⚠️ Não foi possível mover '{os.path.basename(caminho)}' "
            f"para a Lixeira: {e}. Arquivo mantido."
        )
def sanitizar_nome(nome: str) -> str:
    """Remove caracteres inválidos para nomes de arquivo no Windows."""
    return re.sub(r'[\\/*?:"<>|\n\r]', "", nome)


def formatar_valor_br(valor: float) -> str:
    """Converte float para o padrão brasileiro: 1.234,56"""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def imagem_para_pdf_temp(caminho_img: str, pasta: str, prefixo: str = "temp") -> str | None:
    """
    Converte JPEG/PNG em um PDF temporário.
    Retorna o caminho do temp criado, ou None se o arquivo já for PDF.
    """
    if caminho_img.lower().endswith((".jpeg", ".jpg", ".png")):
        nome_temp = os.path.join(pasta, f"{prefixo}_{os.path.basename(caminho_img)}.pdf")
        with Image.open(caminho_img) as img:
            img.convert("RGB").save(nome_temp)
        return nome_temp
    return None


def escrever_e_renomear(merger: PdfWriter, caminho_temp: str, caminho_final: str) -> None:
    """
    Finaliza o PdfWriter em um arquivo temporário e o renomeia para o destino final.
    Garante atomicidade: só substitui o destino após a escrita ser concluída.
    """
    merger.write(caminho_temp)
    merger.close()
    if os.path.exists(caminho_temp):
        try:
            if os.path.exists(caminho_final):
                os.remove(caminho_final)
            os.rename(caminho_temp, caminho_final)
        except Exception as e:
            print(f"   ⚠️ Não foi possível renomear '{os.path.basename(caminho_temp)}': {e}")

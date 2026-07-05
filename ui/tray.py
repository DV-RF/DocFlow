# =====================================================================
# DOCFLOW — Bandeja do Sistema (ui/tray.py)
# =====================================================================
import threading
from PIL import Image, ImageDraw, ImageFont

try:
    import pystray
    PYSTRAY_DISPONIVEL = True
except ImportError:
    PYSTRAY_DISPONIVEL = False


def _criar_imagem_icone(size: int = 64) -> Image.Image:
    """Cria o ícone do DocFlow programaticamente (círculo azul com 'D')."""
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fundo — círculo azul escuro
    draw.ellipse([2, 2, size - 2, size - 2], fill="#1f538d")

    # Onda decorativa
    draw.arc([size // 4, size // 2, size * 3 // 4, size - 8], 0, 180, fill="#4fa3e0", width=3)

    # Letra "D" centralizada
    try:
        font = ImageFont.truetype("arial.ttf", int(size * 0.45))
    except Exception:
        font = ImageFont.load_default()

    draw.text((size // 2, size // 2 - 4), "D", fill="white", font=font, anchor="mm")
    return img


def criar_icone_tray(app) -> "pystray.Icon | None":
    """
    Cria e inicia o ícone na bandeja do sistema.
    Retorna o objeto Icon ou None se pystray não estiver disponível.
    """
    if not PYSTRAY_DISPONIVEL:
        return None

    img = _criar_imagem_icone()

    def abrir(icon, item):
        app.after(0, app.deiconify)
        app.after(0, app.lift)
        app.after(0, app.focus_force)

    def processar_agora(icon, item):
        app.after(0, app.processar_agora)

    def pausar_retomar(icon, item):
        app.after(0, app.toggle_pause)

    def sair(icon, item):
        app.after(0, app.sair_aplicacao)

    menu = pystray.Menu(
        pystray.MenuItem("📂  Abrir DocFlow",      abrir,           default=True),
        pystray.MenuItem("⚡  Processar Agora",    processar_agora),
        pystray.MenuItem("⏸  Pausar / Retomar",   pausar_retomar),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("✕  Sair",               sair),
    )

    icon = pystray.Icon("DocFlow", img, "DocFlow", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon

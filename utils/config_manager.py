# =====================================================================
# DOCFLOW — Gerenciador de Configurações (utils/config_manager.py)
# =====================================================================
import json
import os
import sys
from pathlib import Path


def _get_base_dir() -> Path:
    """Retorna a pasta raiz do projeto, compatível com PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


CONFIG_PATH = _get_base_dir() / "config.json"

DEFAULT_CONFIG = {
    "pasta_origem":        "",
    "pasta_destino":       "",
    "intervalo_minutos":   15,
    "tema":                "dark",
    "iniciar_com_windows": False,
    "notificacoes":        True,
    "tesseract_path":      r"C:\Program Files\Tesseract-OCR\tesseract.exe",
}


class ConfigManager:
    def __init__(self):
        self._data = DEFAULT_CONFIG.copy()
        self.load()

    def load(self) -> None:
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    self._data.update(json.load(f))
        except Exception:
            pass

    def save(self) -> None:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self.save()

    def set_startup(self, enable: bool) -> None:
        """Adiciona ou remove o DocFlow do startup do Windows."""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )
            if enable:
                exe = (
                    sys.executable
                    if getattr(sys, "frozen", False)
                    else f'"{sys.executable}" "{_get_base_dir() / "main.py"}"'
                )
                winreg.SetValueEx(key, "DocFlow", 0, winreg.REG_SZ, exe)
            else:
                try:
                    winreg.DeleteValue(key, "DocFlow")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass
        self.set("iniciar_com_windows", enable)

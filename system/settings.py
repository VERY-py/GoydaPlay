import json
from pathlib import Path

dir_path = Path(__file__).parent.resolve()
SETTINGS_FILE = dir_path / "settings.json"
LANGS_FILE = dir_path / "langs.json"
DOWNLOADS_STATE_FILE = dir_path / "downloads_state.json"


def load_settings():
    """Загружает настройки из файла"""
    if not SETTINGS_FILE.exists():
        default_settings = {
            "lang": "ru",
            "server_url": "http://95.181.212.148/",
            "max_parallel_downloads": 1,
            "downloads_folder": str(Path(__file__).parent.parent / "games" / "files")
        }
        save_settings(default_settings)
        return default_settings

    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_settings(settings):
    """Сохраняет настройки в файл"""
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def load_languages():
    """Загружает словари языков"""
    with open(LANGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_downloads_state():
    """Загружает состояние загрузок"""
    if not DOWNLOADS_STATE_FILE.exists():
        return {}
    with open(DOWNLOADS_STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_downloads_state(state):
    """Сохраняет состояние загрузок"""
    with open(DOWNLOADS_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


_worlds = load_languages()
_sett = load_settings()
_current_lang = _sett.get("lang", "ru")


def get_worlds():
    """Возвращает актуальный словарь для текущего языка"""
    if _current_lang == "en":
        return _worlds["en"]
    else:
        return _worlds["ru"]


def reload_language():
    """Перезагружает текущий язык из настроек"""
    global _sett, _current_lang
    _sett = load_settings()
    _current_lang = _sett.get("lang", "ru")


def switch_language():
    """Переключает язык и сохраняет настройки"""
    global _sett, _current_lang

    new_lang = "en" if _current_lang == "ru" else "ru"

    _sett["lang"] = new_lang
    save_settings(_sett)

    _current_lang = new_lang

    return new_lang


def get_current_language():
    """Возвращает текущий язык в читаемом виде"""
    return "RU" if _current_lang == "ru" else "EN"


def get_server_url():
    """Возвращает базовый URL сервера"""
    return _sett.get("server_url", "http://95.181.212.148/")


def get_max_parallel_downloads():
    """Возвращает максимальное количество параллельных загрузок"""
    return _sett.get("max_parallel_downloads", 1)


def get_downloads_folder():
    """Возвращает папку для загрузок"""
    return Path(_sett.get("downloads_folder", str(Path(__file__).parent.parent / "games" / "files")))
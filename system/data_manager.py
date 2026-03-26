import json
import shutil
import zipfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

GAMES_FILE = Path(__file__).parent.parent / "games" / "games.json"
LIBRARY_FILE = Path(__file__).parent.parent / "games" / "library.json"


def load_games():
    """Загружает список игр из games.json"""
    if not GAMES_FILE.exists():
        logger.warning(f"Games file not found: {GAMES_FILE}")
        return {}

    with open(GAMES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_library():
    """Загружает библиотеку из library.json"""
    if not LIBRARY_FILE.exists():
        return {}
    with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_library(library):
    """Сохраняет библиотеку в library.json"""
    LIBRARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LIBRARY_FILE, "w", encoding="utf-8") as f:
        json.dump(library, f, indent=2, ensure_ascii=False)


def add_game_to_library(game_id, game_data):
    """
    Добавляет игру в библиотеку (если ещё не добавлена)
    game_data - это список: [archive_name, name, size, requirements, launch_command, version]
    """
    library = load_library()
    if game_id not in library:
        lib_entry = {
            "archive_name": game_data[0],
            "name": game_data[1],
            "size": game_data[2],
            "requirements": game_data[3],
            "launch_command": game_data[4],
            "version": game_data[5],
            "downloaded": False,
            "install_path": None
        }
        library[game_id] = lib_entry
        save_library(library)
        logger.info(f"Game {game_id} added to library")
        return True
    return False


def remove_game_from_library(game_id):
    """Удаляет игру из библиотеки и, если скачана, удаляет папку с файлами"""
    library = load_library()
    if game_id in library:
        if library[game_id].get("downloaded", False):
            game_folder = get_game_install_path(game_id)
            if game_folder and game_folder.exists():
                try:
                    shutil.rmtree(game_folder)
                    logger.info(f"Removed game folder: {game_folder}")
                except Exception as e:
                    logger.error(f"Error removing game folder: {e}")

        del library[game_id]
        save_library(library)
        logger.info(f"Game {game_id} removed from library")
        return True
    return False


def update_library_version(game_id, new_version):
    """Обновляет версию игры в библиотеке"""
    library = load_library()
    if game_id in library:
        library[game_id]["version"] = new_version
        save_library(library)
        return True
    return False


def set_game_downloaded(game_id, downloaded=True, install_path=None):
    """Устанавливает статус загрузки игры"""
    library = load_library()
    if game_id in library:
        library[game_id]["downloaded"] = downloaded
        if install_path:
            library[game_id]["install_path"] = str(install_path)
        save_library(library)
        return True
    return False


def get_game_install_path(game_id):
    """Возвращает путь к установленной игре"""
    from settings import get_downloads_folder

    library = load_library()
    if game_id in library:
        install_path = library[game_id].get("install_path")
        if install_path:
            path = Path(install_path)
            if path.exists():
                return path

        default_path = get_downloads_folder() / game_id
        if default_path.exists():
            library[game_id]["install_path"] = str(default_path)
            save_library(library)
            return default_path

    return None


def get_game_data_from_library(game_id):
    """Возвращает данные игры из библиотеки в формате списка для совместимости"""
    library = load_library()
    if game_id in library:
        entry = library[game_id]
        return [
            entry.get("archive_name", ""),
            entry.get("name", ""),
            entry.get("size", 0),
            entry.get("requirements", []),
            entry.get("launch_command", ""),
            entry.get("version", "")
        ]
    return None


def extract_game_archive(game_id, archive_path):
    """Распаковывает архив игры"""
    from settings import get_downloads_folder

    try:
        install_path = get_downloads_folder() / game_id
        install_path.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(archive_path, 'r') as zf:
            zf.extractall(install_path)

        archive_path.unlink()
        set_game_downloaded(game_id, True, install_path)
        logger.info(f"Game {game_id} extracted to {install_path}")
        return True
    except Exception as e:
        logger.error(f"Error extracting game {game_id}: {e}")
        return False


def remove_game_files_only(game_id):
    """Удаляет только локальные файлы игры, не трогая запись в библиотеке"""
    library = load_library()
    if game_id in library:
        game_folder = get_game_install_path(game_id)
        if game_folder and game_folder.exists():
            try:
                shutil.rmtree(game_folder)
                logger.info(f"Removed game files only: {game_folder}")
                library[game_id]["downloaded"] = False
                library[game_id]["install_path"] = None
                save_library(library)
                return True
            except Exception as e:
                logger.error(f"Error removing game files: {e}")
                return False
    return False


def remove_game_completely(game_id):
    """Полностью удаляет игру: файлы и запись из библиотеки"""
    library = load_library()
    if game_id in library:
        if library[game_id].get("downloaded", False):
            game_folder = get_game_install_path(game_id)
            if game_folder and game_folder.exists():
                try:
                    shutil.rmtree(game_folder)
                    logger.info(f"Removed game folder: {game_folder}")
                except Exception as e:
                    logger.error(f"Error removing game folder: {e}")

        del library[game_id]
        save_library(library)
        logger.info(f"Game {game_id} completely removed from library")
        return True
    return False
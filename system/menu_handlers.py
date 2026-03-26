import logging
import queue
import subprocess
import shutil
import sys
import threading
import zipfile

import menuManager
import data_manager
from settings import get_worlds, get_current_language, get_server_url, get_downloads_folder

logger = logging.getLogger(__name__)


def get_text(key, default=""):
    """Получает текст для текущего языка"""
    worlds = get_worlds()
    return worlds.get(key, default)


def format_size(size_bytes):
    """Форматирует размер в человекочитаемый вид"""
    if size_bytes == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def draw_info_box(title, content_lines):
    """Рисует информационную рамку"""
    width = 50
    result = []
    result.append(f"+{'-' * width}+")
    result.append(f"|{' ' * ((width - len(title)) // 2)}{title}{' ' * ((width - len(title) + 1) // 2)}|")
    result.append(f"+{'-' * width}+")

    for line in content_lines:
        if len(line) > width - 2:
            line = line[:width - 5] + "..."
        padding = width - len(line) - 1
        result.append(f"| {line}{' ' * padding}|")

    result.append(f"+{'-' * width}+")
    return result


class MenuHandler:
    def __init__(self, menu_stack, download_manager, message_callback):
        self.menu_stack = menu_stack
        self.download_manager = download_manager
        self.message = message_callback

    def handle(self, menu_id, selected_index):
        pass

    def refresh_display(self):
        """Принудительное обновление отображения"""
        current = self.menu_stack.get_current()
        if current:
            current.prev_index = None
            current.prev_lines = None
            current.display()


class StoreMenuHandler(MenuHandler):
    def handle(self, menu_id, selected_index):
        worlds = get_worlds()
        games = data_manager.load_games()
        library = data_manager.load_library()

        items = []
        self.game_ids = []
        for gid, gdata in games.items():
            name = gdata[1]
            size_bytes = gdata[2]
            size_str = format_size(size_bytes)

            in_library = gid in library
            icon = "[✓]" if in_library else "[ ]"

            items.append(f"{icon} {name} ({size_str})")
            self.game_ids.append(gid)

        store_menu = menuManager.MenuNavigator(items, self.menu_stack, "store", show_back_option=False)
        store_menu.game_ids = self.game_ids
        store_menu.game_data = games
        store_menu.library_data = library
        self.menu_stack.push(store_menu)
        self.refresh_display()


class LibraryMenuHandler(MenuHandler):
    def handle(self, menu_id, selected_index):
        worlds = get_worlds()
        library = data_manager.load_library()
        items = []
        self.game_ids = []

        for gid, gdata in library.items():
            name = gdata.get("name", "Unknown")
            size_bytes = gdata.get("size", 0)
            size_str = format_size(size_bytes)
            downloaded = gdata.get("downloaded", False)
            icon = "[✓]" if downloaded else "[ ]"
            items.append(f"{icon} {name} ({size_str})")
            self.game_ids.append(gid)

        lib_menu = menuManager.MenuNavigator(items, self.menu_stack, "library", show_back_option=False)
        lib_menu.game_ids = self.game_ids
        lib_menu.game_data = library
        self.menu_stack.push(lib_menu)
        self.refresh_display()


class DownloadsMenuHandler(MenuHandler):
    def __init__(self, menu_stack, download_manager, message_callback):
        super().__init__(menu_stack, download_manager, message_callback)
        self.last_update = 0

    def handle(self, menu_id, selected_index):
        self.create_downloads_menu()

    def create_downloads_menu(self):
        """Создаёт меню загрузок с динамическим содержимым"""
        worlds = get_worlds()
        tasks = self.download_manager.get_all_tasks()

        if tasks:
            items = []
            self.task_ids = []

            for task in tasks:
                status_icons = {
                    "downloading": "▼",
                    "paused": "⏸",
                    "pending": "⏳",
                    "completed": "✓",
                    "cancelled": "✗",
                    "error": "✗"
                }
                icon = status_icons.get(task.status, "?")

                if task.total > 0:
                    percent = (task.progress / task.total) * 100
                    progress_str = f"{percent:.1f}%"
                else:
                    progress_str = "0%"

                size_str = format_size(task.progress)
                total_str = format_size(task.total)

                item = f"{icon} {task.game_name} - {size_str}/{total_str} ({progress_str})"
                items.append(item)
                self.task_ids.append(task.task_id)

            active_tasks = [t for t in tasks if t.status in ["downloading", "paused"]]
            if active_tasks:
                items.append("─" * 40)
                items.append("[⏸] Pause All")
                items.append("[▶] Resume All")
                items.append("[✗] Cancel All")

            download_menu = menuManager.MenuNavigator(items, self.menu_stack, "downloads",
                                                      show_back_option=False,
                                                      title="DOWNLOADS MANAGER")
            download_menu.task_ids = self.task_ids
            download_menu.download_manager = self.download_manager
        else:
            items = ["[ ] " + worlds.get("no_downloads", "No active downloads")]
            download_menu = menuManager.MenuNavigator(items, self.menu_stack, "downloads",
                                                      show_back_option=False)

        self.menu_stack.push(download_menu)
        self.refresh_display()


class SettingsMenuHandler(MenuHandler):
    def handle(self, menu_id, selected_index):
        self.create_settings_menu()

    def create_settings_menu(self):
        """Создаёт меню настроек"""
        worlds = get_worlds()

        lang = "[L] " + worlds.get("language", "Language") + " : " + get_current_language()
        about = "[i] " + worlds.get("about", "About")
        items = [lang, about]
        settings_menu = menuManager.MenuNavigator(items, self.menu_stack, "settings", show_back_option=False)
        self.menu_stack.push(settings_menu)
        self.refresh_display()


class GameDetailMenu(menuManager.MenuNavigator):
    """Меню для отображения информации об игре и действий"""

    def __init__(self, game_id, game_data, parent_stack, source, download_manager, message_callback):
        self.game_id = game_id
        self.source = source
        self.download_manager = download_manager
        self.message = message_callback
        self.current_task_id = None

        worlds = get_worlds()
        self.library_data = data_manager.load_library()

        if source == "store":
            self.name = game_data[1]
            self.size_bytes = game_data[2]
            self.requirements = game_data[3]
            self.launch_command = game_data[4]
            self.version = game_data[5]
            self.archive_name = game_data[0]
            self.game_data = game_data
            self.in_library = game_id in self.library_data
            self.downloaded = self.in_library and self.library_data.get(game_id, {}).get("downloaded", False)
        else:  # library
            self.name = game_data.get("name", "Unknown")
            self.size_bytes = game_data.get("size", 0)
            self.requirements = game_data.get("requirements", [])
            self.launch_command = game_data.get("launch_command", "")
            self.version = game_data.get("version", "")
            self.archive_name = game_data.get("archive_name", "")
            self.game_data = game_data
            self.in_library = True
            self.downloaded = game_data.get("downloaded", False)

        actions = []
        if source == "store":
            if self.in_library:
                if self.downloaded:
                    actions.append("[>] " + worlds.get("run", "Run"))
                else:
                    actions.append("[D] " + worlds.get("download", "Download"))
            else:
                actions.append("[+] " + worlds.get("add_to_library", "Add to library"))
        else:  # library
            if self.downloaded:
                actions.append("[>] " + worlds.get("run", "Run"))
                games_data = data_manager.load_games()
                if game_id in games_data:
                    server_version = games_data[game_id][5]
                    if server_version != self.version:
                        actions.append("[U] " + worlds.get("update", "Update"))
                actions.append("[X] " + worlds.get("delete_from_library", "Delete from library"))
                actions.append("[F] " + worlds.get("delete_from_device", "Delete from device"))
            else:
                actions.append("[D] " + worlds.get("download", "Download"))
                actions.append("[X] " + worlds.get("delete_from_library", "Delete from library"))

        super().__init__(actions, parent_stack, f"game_detail_{game_id}", show_back_option=False,
                         title=self.name)

        self.prev_info_lines = None

    def get_info_lines(self):
        """Формирует строки информации об игре"""
        worlds = get_worlds()

        info_lines = [
            f"Name: {self.name}",
            f"Size: {format_size(self.size_bytes)}",
            f"Requirements: {', '.join(self.requirements)}",
            f"Version: {self.version}",
        ]

        if self.source == "library" or self.in_library:
            status_text = "✓ Downloaded" if self.downloaded else "○ Not downloaded"
            info_lines.append(f"Status: {status_text}")

        return info_lines

    def needs_redraw(self):
        """Переопределяем проверку необходимости перерисовки"""
        if self.prev_index is None or self.prev_lines != self.lines:
            return True

        if self.prev_index != self.current_index:
            return True

        current_info = self.get_info_lines()
        if self.prev_info_lines != current_info:
            return True

        return False

    def display(self):
        """Отображает информацию и меню (только если нужно)"""
        if not self.needs_redraw():
            return

        self.clear_console()

        info_lines = self.get_info_lines()
        info_box = draw_info_box(self.name, info_lines)
        for line in info_box:
            print(line)

        print()

        menu_lines = self.draw_menu(self.name, self.lines, self.current_index)
        for line in menu_lines:
            print(line)

        sys.stdout.flush()

        self.prev_index = self.current_index
        self.prev_lines = self.lines.copy()
        self.prev_info_lines = info_lines.copy()

    def handle_selection(self, selected_index):
        """Обработка выбранного действия"""
        worlds = get_worlds()

        action = self.lines[selected_index]
        for prefix in ["[+] ", "[>] ", "[U] ", "[D] ", "[X] ", "[F] "]:
            action = action.replace(prefix, "")

        if self.source == "store":
            if action == worlds.get("add_to_library", "Add to library"):
                if data_manager.add_game_to_library(self.game_id, self.game_data):
                    self.message("✓ " + worlds.get("added_to_library", "Game added to library!"))
                    self.parent_stack.pop()
                else:
                    self.message("! Game already in library")

            elif action == worlds.get("download", "Download"):
                self._start_download()

        else:  # library
            if action == worlds.get("download", "Download"):
                self._start_download()

            elif action == worlds.get("run", "Run"):
                self._run_game()

            elif action == worlds.get("update", "Update"):
                self._update_game()

            elif action == worlds.get("delete_from_library", "Delete from library"):
                if data_manager.remove_game_completely(self.game_id):
                    self.message("✗ " + worlds.get("removed_from_library", "Game removed from library!"))
                    self.parent_stack.pop()
                else:
                    self.message("! Failed to remove game")

            elif action == worlds.get("delete_from_device", "Delete from device"):
                if data_manager.remove_game_files_only(self.game_id):
                    self.message("🗑 " + worlds.get("files_deleted", "Game files deleted!"))
                    self.parent_stack.pop()
                else:
                    self.message("! Failed to delete files")

    def _start_download(self):
        """Начинает загрузку игры"""
        worlds = get_worlds()

        game_folder = get_downloads_folder() / self.game_id
        game_folder.mkdir(parents=True, exist_ok=True)
        archive_path = game_folder / f"{self.game_id}.zip"

        base_url = get_server_url()
        url = base_url + self.archive_name

        progress_msg = [""]
        progress_active = [False]

        progress_queue = queue.Queue()

        def progress_updater():
            """Отдельный поток для обновления прогресса"""
            while progress_active[0]:
                try:
                    msg = progress_queue.get(timeout=0.1)
                    if msg:
                        self.message(msg, duration=1)
                except queue.Empty:
                    continue

        updater_thread = threading.Thread(target=progress_updater, daemon=True)
        progress_active[0] = True
        updater_thread.start()

        def progress_cb(current, total):
            """Колбэк прогресса"""
            if total > 0:
                percent = (current / total * 100)
                size_current = format_size(current)
                size_total = format_size(total)
                msg = f"▼ Download: {size_current}/{size_total} ({percent:.1f}%)"
                progress_queue.put(msg)

        def finished_cb(dest_path):
            """Завершение загрузки"""
            progress_active[0] = False

            def extract():
                try:
                    self.message(f"📦 Extracting {self.name}...", duration=2)
                    with zipfile.ZipFile(dest_path, 'r') as zf:
                        zf.extractall(game_folder)
                    dest_path.unlink()
                    data_manager.set_game_downloaded(self.game_id, True, game_folder)
                    self.message("✓ " + worlds.get("download_complete", "Download complete!"), duration=3)
                except Exception as e:
                    self.message(f"! Extract error: {e}", duration=3)

            threading.Thread(target=extract, daemon=True).start()

        def error_cb(err):
            """Ошибка загрузки"""
            progress_active[0] = False
            self.message(f"! Download error: {err}", duration=3)

        def status_cb(task_id, status, progress, total):
            """Обновление статуса"""
            if status == "cancelled":
                progress_active[0] = False
                self.message("✗ " + worlds.get("download_cancelled", "Download cancelled."), duration=2)
            elif status == "error":
                progress_active[0] = False

        self.download_manager.add_task(
            game_id=self.game_id,
            game_name=self.name,
            url=url,
            dest_path=archive_path,
            callback_progress=progress_cb,
            callback_finished=finished_cb,
            callback_error=error_cb,
            callback_status=status_cb
        )

        self.message("▼ " + worlds.get("download_started", "Download started..."), duration=2)
        self.parent_stack.pop()

    def _run_game(self):
        """Запускает игру"""
        worlds = get_worlds()

        install_path = data_manager.get_game_install_path(self.game_id)

        if not install_path:
            from settings import get_downloads_folder
            install_path = get_downloads_folder() / self.game_id

        if not install_path.exists():
            self.message(f"! Game not installed at: {install_path}")
            logger.error(f"Game not found at {install_path}")
            return

        if not self.launch_command:
            self.message("! No launch command specified")
            return

        if ' ' in self.launch_command:
            parts = self.launch_command.split(' ')
            cmd = parts[0]
            args = parts[1:]
        else:
            cmd = self.launch_command
            args = []

        exec_path = install_path / cmd

        if not exec_path.exists():
            found = False
            for exe in install_path.rglob(cmd):
                if exe.is_file():
                    exec_path = exe
                    found = True
                    break

            if not found:
                self.message(f"! Executable not found: {cmd}")
                logger.error(f"Executable not found: {exec_path}")
                return

        exec_path_abs = exec_path.resolve()

        try:
            logger.info(f"Launching game: {exec_path_abs} from {install_path.resolve()}")

            if exec_path_abs.suffix.lower() == '.bat':
                process = subprocess.Popen(
                    ['cmd', '/c', str(exec_path_abs)] + args,
                    cwd=str(install_path.resolve()),
                    shell=False,
                    creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0
                )
            else:
                if args:
                    process = subprocess.Popen(
                        [str(exec_path_abs)] + args,
                        cwd=str(install_path.resolve()),
                        shell=False
                    )
                else:
                    process = subprocess.Popen(
                        [str(exec_path_abs)],
                        cwd=str(install_path.resolve()),
                        shell=False
                    )

            self.message("> " + worlds.get("game_launched", "Game launched."))

        except Exception as e:
            self.message(f"! Failed to launch: {e}")
            logger.error(f"Launch error: {e}", exc_info=True)

    def _update_game(self):
        """Обновляет игру"""
        worlds = get_worlds()

        install_path = data_manager.get_game_install_path(self.game_id)
        if install_path and install_path.exists():
            shutil.rmtree(install_path)

        self._start_download()
        self.message("U " + worlds.get("update_started", "Update started..."))
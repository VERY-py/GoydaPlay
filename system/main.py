import sys
import io
import time
import signal
import logging
import threading
import queue
from pathlib import Path

import menuManager
import download_manager
from menu_handlers import (StoreMenuHandler, LibraryMenuHandler,
                           DownloadsMenuHandler, SettingsMenuHandler,
                           GameDetailMenu)
from settings import (get_worlds, switch_language, get_current_language,
                      get_downloads_folder, save_downloads_state)

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('goydaplay.log'),
    ]
)
logger = logging.getLogger(__name__)

menu_stack = menuManager.MenuStack()
download_mgr = download_manager.DownloadManager()
shutdown_requested = False

message_queue = queue.Queue()
current_message = None
message_expire_time = 0
message_lock = threading.Lock()
message_line_count = 0


def signal_handler(sig, frame):
    """Обработчик сигналов для graceful shutdown"""
    global shutdown_requested
    print("\n\nShutting down gracefully...")
    shutdown_requested = True

    for task in download_mgr.get_active_tasks():
        task.pause()

    download_mgr.shutdown()
    sys.exit(0)


def show_message(msg, duration=3):
    """Отправляет сообщение в очередь для отображения"""
    if msg is not None:
        message_queue.put(('show', msg, duration))


def clear_messages():
    """Очищает все сообщения"""
    message_queue.put(('clear', None, None))


def _process_messages():
    """Обрабатывает сообщения из очереди (вызывается в главном цикле)"""
    global current_message, message_expire_time, message_line_count

    try:
        while True:
            msg_type, msg, duration = message_queue.get_nowait()

            with message_lock:
                if msg_type == 'clear':
                    # Очищаем все строки сообщений
                    for _ in range(message_line_count):
                        sys.stdout.write('\033[F')
                        sys.stdout.write('\033[K')
                    sys.stdout.flush()
                    current_message = None
                    message_line_count = 0

                elif msg_type == 'show':
                    if current_message is not None:
                        sys.stdout.write('\033[F')
                        sys.stdout.write('\033[K')
                        sys.stdout.flush()

                    current_message = msg
                    message_expire_time = time.time() + duration

                    print(msg)
                    sys.stdout.flush()
                    message_line_count = 1

    except queue.Empty:
        pass


def update_message():
    """Обновляет состояние сообщения (таймаут)"""
    global current_message, message_expire_time, message_line_count

    with message_lock:
        if current_message is not None and time.time() > message_expire_time:
            sys.stdout.write('\033[F')
            sys.stdout.write('\033[K')
            sys.stdout.flush()
            current_message = None
            message_line_count = 0


def show_splash_screen():
    """Показывает заставку при запуске"""
    splash_lines = [
        "╔══════════════════════════════════════════════╗",
        "║                                              ║",
        "║            ░██████╗ ██████╗ ██╗   ██╗        ║",
        "║            ██╔════╝██╔═══██╗╚██╗ ██╔╝        ║",
        "║            ██║     ██║   ██║ ╚████╔╝         ║",
        "║            ██║     ██║   ██║  ╚██╔╝          ║",
        "║            ╚██████╗╚██████╔╝   ██║           ║",
        "║             ╚═════╝ ╚═════╝    ╚═╝           ║",
        "║                                              ║",
        "║         Game Launcher & Downloader           ║",
        "║                 v2.0                         ║",
        "╚══════════════════════════════════════════════╝"
    ]

    print("\n" * 2)
    for line in splash_lines:
        print(line)
        time.sleep(0.03)
    print("\n" * 2)
    time.sleep(1)


def update_all_menus():
    """Обновляет тексты во всех меню после смены языка"""
    worlds = get_worlds()

    main_menu.lines = [worlds["store"], worlds["library"], worlds["downloads"], worlds["settings"]]
    main_menu.prev_index = None
    main_menu.prev_lines = None

    current = menu_stack.get_current()
    if current and current.menu_id == "settings":
        lang = worlds.get("language", "Language") + " : " + get_current_language()
        about = worlds.get("about", "About")
        current.lines = ["[L] " + lang, "[i] " + about]
        current.prev_index = None
        current.prev_lines = None
        current.display()

    global handlers
    handlers = {
        "store": StoreMenuHandler(menu_stack, download_mgr, show_message),
        "library": LibraryMenuHandler(menu_stack, download_mgr, show_message),
        "downloads": DownloadsMenuHandler(menu_stack, download_mgr, show_message),
        "settings": SettingsMenuHandler(menu_stack, download_mgr, show_message),
    }


def push_game_detail(game_id, game_data, source):
    """Создает и добавляет меню деталей игры"""
    detail_menu = GameDetailMenu(game_id, game_data, menu_stack, source, download_mgr, show_message)
    menu_stack.push(detail_menu)
    detail_menu.display()


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

show_splash_screen()

downloads_folder = get_downloads_folder()
downloads_folder.mkdir(parents=True, exist_ok=True)

worlds = get_worlds()
main_lines = [worlds["store"], worlds["library"], worlds["downloads"], worlds["settings"]]
main_menu = menuManager.MenuNavigator(main_lines, menu_stack, "main", show_back_option=False)
menu_stack.push(main_menu)

handlers = {
    "store": StoreMenuHandler(menu_stack, download_mgr, show_message),
    "library": LibraryMenuHandler(menu_stack, download_mgr, show_message),
    "downloads": DownloadsMenuHandler(menu_stack, download_mgr, show_message),
    "settings": SettingsMenuHandler(menu_stack, download_mgr, show_message),
}

logger.info("GoydaPlay started")

last_redraw_time = 0

while menu_stack.running and not shutdown_requested:
    _process_messages()
    update_message()

    r = menu_stack.update()

    menu_stack.display()

    if r and r[0] == 'SELECT':
        current_menu = menu_stack.get_current()
        if current_menu is None:
            continue

        selected_index = r[1]
        menu_id = current_menu.menu_id

        if menu_id == "main":
            if selected_index == 0:
                handlers["store"].handle("store", 0)
            elif selected_index == 1:
                handlers["library"].handle("library", 0)
            elif selected_index == 2:
                handlers["downloads"].handle("downloads", 0)
            elif selected_index == 3:
                handlers["settings"].handle("settings", 0)

        elif menu_id == "store":
            game_id = current_menu.game_ids[selected_index]
            game_data = current_menu.game_data[game_id]
            push_game_detail(game_id, game_data, "store")

        elif menu_id == "library":
            game_id = current_menu.game_ids[selected_index]
            game_data = current_menu.game_data[game_id]
            push_game_detail(game_id, game_data, "library")

        elif menu_id == "downloads":
            if hasattr(current_menu, 'task_ids') and selected_index < len(current_menu.task_ids):
                task_id = current_menu.task_ids[selected_index]
                pass
            elif hasattr(current_menu, 'lines'):
                action = current_menu.lines[selected_index]
                if "Pause All" in action:
                    for task in download_mgr.get_active_tasks():
                        task.pause()
                    show_message("All downloads paused", duration=2)
                elif "Resume All" in action:
                    for task in download_mgr.get_active_tasks():
                        task.resume()
                    show_message("All downloads resumed", duration=2)
                elif "Cancel All" in action:
                    for task in download_mgr.get_active_tasks():
                        task.cancel()
                    show_message("All downloads cancelled", duration=2)

        elif menu_id == "settings":
            if selected_index == 0:
                new_lang = switch_language()
                update_all_menus()
                show_message(get_worlds().get("language_changed", "Language changed").format(get_current_language()),
                             duration=2)
            elif selected_index == 1:
                worlds = get_worlds()
                info_file = Path(__file__).parent.parent / "info"
                if info_file.exists():
                    with open(info_file, "r", encoding="utf-8") as f:
                        info_text = f.read()
                else:
                    info_text = worlds.get("about_text",
                                           "GoydaPlay v2.0\nA modern game launcher with multi-download support.")

                show_message(info_text, duration=5)

        elif menu_id.startswith("game_detail_"):
            detail_menu = current_menu
            detail_menu.handle_selection(selected_index)

    elif r and r[0] == 'BACK':
        menu_stack.pop()
        current = menu_stack.get_current()
        if current:
            current.prev_index = None
            current.prev_lines = None
            current.display()

    elif r and r[0] == 'EXIT':
        break

    time.sleep(0.05)

logger.info("Shutting down...")
download_mgr.shutdown()
save_downloads_state({})
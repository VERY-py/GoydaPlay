import sys
import msvcrt
import os


class MenuStack:
    """Управляет стеком меню для вложенной навигации"""

    def __init__(self):
        self.stack = []
        self.running = True

    def push(self, menu):
        """Добавляет новое меню в стек"""
        self.stack.append(menu)

    def pop(self):
        """Удаляет текущее меню из стека и возвращает предыдущее"""
        if len(self.stack) > 1:
            self.stack.pop()
            return self.get_current()
        else:
            self.running = False
            return None

    def get_current(self):
        """Возвращает текущее активное меню"""
        return self.stack[-1] if self.stack else None

    def update(self):
        """Обновляет текущее меню"""
        current = self.get_current()
        if not current:
            self.running = False
            return None

        result = current.update()

        if result and result[0] == 'EXIT':
            self.running = False
            return result

        return result

    def display(self):
        """Отображает текущее меню"""
        current = self.get_current()
        if current:
            current.display()


class MenuNavigator:
    def __init__(self, lines=None, parent_stack=None, menu_id=None, show_back_option=True, title=None):
        if lines is None or not isinstance(lines, list):
            self.lines = [
                "Строка 1",
                "Строка 2",
                "Строка 3"
            ]
        else:
            self.lines = lines.copy()

        self.show_back_option = show_back_option
        if show_back_option and self.lines and self.lines[-1] != "Назад" and self.lines[-1] != "Back":
            from settings import get_worlds
            worlds = get_worlds()
            self.lines.append(worlds.get("back", "Back"))

        self.current_index = 0
        self.running = True
        self.hmlines = len(self.lines)
        self.parent_stack = parent_stack
        self.menu_id = menu_id
        self.title = title

        self.prev_index = None
        self.prev_lines = None

    def get_key(self):
        """Получение нажатой клавиши"""
        if msvcrt.kbhit():
            key = msvcrt.getch()

            if key == b'\x00' or key == b'\xe0':
                key2 = msvcrt.getch()
                if key == b'\xe0':
                    if key2 == b'H':
                        return 'UP'
                    elif key2 == b'P':
                        return 'DOWN'
                    elif key2 == b'M':
                        return 'RIGHT'
                    elif key2 == b'K':
                        return 'LEFT'
                return None

            try:
                for encoding in ['cp866', 'utf-8', 'latin-1']:
                    try:
                        return key.decode(encoding)
                    except UnicodeDecodeError:
                        continue
                return None
            except:
                return None
        return None

    def clear_console(self):
        """Очищает всю консоль"""
        os.system('cls' if os.name == 'nt' else 'clear')

    def draw_line(self, char='-', length=50):
        """Рисует линию из символов"""
        return char * length

    def draw_header(self, title):
        """Рисует заголовок с рамкой"""
        width = 50
        title_len = len(title)
        left_padding = (width - title_len - 2) // 2
        right_padding = width - title_len - 2 - left_padding

        header = f"+{self.draw_line('-', width)}+"
        title_line = f"|{' ' * left_padding}{title}{' ' * right_padding}|"

        return [header, title_line, header]

    def needs_redraw(self):
        """Проверяет, нужно ли перерисовывать меню"""
        if self.prev_index is None:
            return True

        if self.prev_index != self.current_index:
            return True

        if self.prev_lines != self.lines:
            return True

        return False

    def display(self):
        """Отображает все строки с текущим выделением (только если нужно)"""
        if not self.needs_redraw():
            return

        self.clear_console()

        title = self.get_menu_title()

        menu_lines = self.draw_menu(title, self.lines, self.current_index)

        for line in menu_lines:
            print(line)

        sys.stdout.flush()

        self.prev_index = self.current_index
        self.prev_lines = self.lines.copy()

    def draw_menu(self, title, items, selected_index):
        """Рисует меню с рамкой"""
        width = 50
        result = []

        result.append(f"╔{'═' * (width-1)}╗")

        if len(title) > width - 2:
            title = title[:width - 5] + "..."
        padding = (width - len(title) - 2) // 2
        result.append(f"║{' ' * padding}{title}{' ' * (width - len(title) - 1 - padding)}║")
        result.append(f"║{'═' * (width-1)}║")

        for i, item in enumerate(items):
            display_item = item
            if len(display_item) > width - 4:
                display_item = display_item[:width - 7] + "..."

            if i == selected_index:
                line = f"║ > {display_item:<{width - 4}}║"
            else:
                line = f"║   {display_item:<{width - 4}}║"
            result.append(line)

        result.append(f"╚{'═' * (width-1)}╝\n")

        return result

    def get_menu_title(self):
        """Возвращает заголовок для меню на основе menu_id"""
        from settings import get_worlds
        worlds = get_worlds()

        titles = {
            "main": "GOYDA PLAY",
            "store": worlds.get("store", "STORE").upper(),
            "library": worlds.get("library", "LIBRARY").upper(),
            "downloads": worlds.get("downloads", "DOWNLOADS").upper(),
            "settings": worlds.get("settings", "SETTINGS").upper(),
            "info": "INFO"
        }

        if self.title:
            return self.title
        return titles.get(self.menu_id, "MENU")

    def update(self):
        """Обновление состояния меню на основе ввода"""
        key = self.get_key()

        if not key:
            return None, self.current_index

        if key == 'UP':
            if self.current_index > 0:
                self.current_index -= 1
            return None, self.current_index

        elif key == 'DOWN':
            if self.current_index < len(self.lines) - 1:
                self.current_index += 1
            return None, self.current_index

        if key == 'LEFT' or key == '\x1b':
            return 'BACK', self.current_index

        if key == '\r' or key == 'RIGHT':
            return 'SELECT', self.current_index

        if key == 'q' or key == 'й' or key == 'Q' or key == 'Й':
            return 'EXIT', self.current_index

        return None, self.current_index
import threading
import queue
import requests
import time
import logging
import shutil
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('downloads.log'),
    ]
)
logger = logging.getLogger(__name__)


class DownloadTask:
    """Класс для представления отдельной задачи загрузки"""

    def __init__(self, task_id, game_id, game_name, url, dest_path,
                 callback_progress=None, callback_finished=None,
                 callback_error=None, callback_status=None):
        self.task_id = task_id
        self.game_id = game_id
        self.game_name = game_name
        self.url = url
        self.dest_path = Path(dest_path)
        self.callback_progress = callback_progress
        self.callback_finished = callback_finished
        self.callback_error = callback_error
        self.callback_status = callback_status

        self.thread = None
        self._lock = threading.Lock()
        self._paused = False
        self._cancelled = False
        self._pause_event = threading.Event()
        self.progress = 0
        self.total = 0
        self.status = "pending"  # pending, downloading, paused, cancelled, completed, error
        self.error_message = None
        self.start_time = None
        self.end_time = None
        self.retry_count = 0
        self.max_retries = 3
        self.session = None

    def pause(self):
        """Приостанавливает загрузку"""
        with self._lock:
            if self.status == "downloading":
                self._paused = True
                self._pause_event.set()
                self.status = "paused"
                self._update_status()
                logger.info(f"Task {self.task_id} paused")

    def resume(self):
        """Возобновляет загрузку"""
        with self._lock:
            if self.status == "paused":
                self._paused = False
                self._pause_event.clear()
                self.status = "downloading"
                self._update_status()
                logger.info(f"Task {self.task_id} resumed")

    def cancel(self):
        """Отменяет загрузку"""
        with self._lock:
            if self.status in ["downloading", "paused", "pending"]:
                self._cancelled = True
                self._pause_event.set()
                self.status = "cancelled"
                self._update_status()
                logger.info(f"Task {self.task_id} cancelled")

    def _update_status(self):
        """Обновляет статус через колбэк"""
        if self.callback_status:
            self.callback_status(self.task_id, self.status, self.progress, self.total)

    def _safe_call(self, callback_name, *args, **kwargs):
        """Безопасный вызов колбэка"""
        callback = getattr(self, f"callback_{callback_name}", None)
        if callback and callable(callback):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in callback {callback_name}: {e}")

    def _check_free_space(self):
        """Проверяет свободное место на диске"""
        try:
            usage = shutil.disk_usage(self.dest_path.parent)
            needed = self.total - self.progress
            if usage.free < needed:
                self.error_message = f"Not enough free space. Need {needed} bytes, have {usage.free} bytes"
                self.status = "error"
                self._safe_call("error", self.error_message)
                return False
            return True
        except Exception as e:
            logger.error(f"Error checking free space: {e}")
            return True

    def run(self):
        """Основной метод загрузки"""
        self.status = "downloading"
        self.start_time = datetime.now()
        self._update_status()

        try:
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })

            while self.retry_count < self.max_retries and not self._cancelled:
                try:
                    self._download_file()
                    break
                except requests.exceptions.RequestException as e:
                    self.retry_count += 1
                    if self.retry_count >= self.max_retries:
                        raise
                    wait_time = 2 ** self.retry_count
                    logger.warning(f"Download attempt {self.retry_count} failed: {e}, retrying in {wait_time}s")
                    time.sleep(wait_time)

        except Exception as e:
            self.error_message = str(e)
            self.status = "error"
            self._safe_call("error", self.error_message)
            logger.error(f"Task {self.task_id} failed: {e}")

        finally:
            if self.session:
                self.session.close()
            self.end_time = datetime.now()

    def _download_file(self):
        """Выполняет фактическую загрузку файла"""
        resume_pos = 0

        if self.dest_path.exists() and not self._cancelled:
            resume_pos = self.dest_path.stat().st_size
            headers = {'Range': f'bytes={resume_pos}-'}
            logger.info(f"Resuming download from {resume_pos} bytes")
        else:
            headers = {}

        response = self.session.get(self.url, stream=True, headers=headers, timeout=30)
        response.raise_for_status()

        if 'content-range' in response.headers:
            self.total = int(response.headers['content-range'].split('/')[1])
        else:
            self.total = int(response.headers.get('content-length', 0)) + resume_pos

        if not self._check_free_space():
            return

        if resume_pos >= self.total and self.total > 0:
            self.progress = self.total
            self.status = "completed"
            self._safe_call("finished", self.dest_path)
            self._update_status()
            return

        self.dest_path.parent.mkdir(parents=True, exist_ok=True)

        mode = 'ab' if resume_pos > 0 else 'wb'
        downloaded = resume_pos

        with open(self.dest_path, mode) as f:
            for chunk in response.iter_content(chunk_size=8192):
                if self._cancelled:
                    if self.dest_path.exists() and self.dest_path.stat().st_size == 0:
                        self.dest_path.unlink()
                    self.status = "cancelled"
                    self._update_status()
                    return

                if self._paused:
                    self._pause_event.wait()
                    if self._cancelled:
                        self.status = "cancelled"
                        self._update_status()
                        return

                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    self.progress = downloaded
                    self._safe_call("progress", self.progress, self.total)
                    self._update_status()

        self.status = "completed"
        self._safe_call("finished", self.dest_path)
        self._update_status()
        logger.info(f"Task {self.task_id} completed successfully")


class DownloadManager:
    """Менеджер загрузок с поддержкой очереди и нескольких параллельных задач"""

    def __init__(self, message_queue=None):
        self.tasks = {}  # task_id -> DownloadTask
        self.task_counter = 0
        self.message_queue = message_queue or queue.Queue()
        self.max_parallel = 1
        self.queue = []
        self._lock = threading.Lock()
        self._running = True
        self._load_state()

    def _load_state(self):
        """Загружает сохранённое состояние загрузок"""
        try:
            from settings import load_downloads_state, get_max_parallel_downloads, get_server_url
            state = load_downloads_state()
            self.max_parallel = get_max_parallel_downloads()

            for task_id, task_data in state.items():
                if task_data.get("status") in ["downloading", "paused"]:
                    self.add_task(
                        game_id=task_data["game_id"],
                        game_name=task_data["game_name"],
                        url=task_data["url"],
                        dest_path=Path(task_data["dest_path"])
                    )
        except Exception as e:
            logger.error(f"Error loading downloads state: {e}")

    def _save_state(self):
        """Сохраняет текущее состояние загрузок"""
        try:
            from settings import save_downloads_state
            state = {}
            for task_id, task in self.tasks.items():
                if task.status in ["downloading", "paused"]:
                    state[str(task_id)] = {
                        "game_id": task.game_id,
                        "game_name": task.game_name,
                        "url": task.url,
                        "dest_path": str(task.dest_path),
                        "status": task.status,
                        "progress": task.progress,
                        "total": task.total
                    }
            save_downloads_state(state)
        except Exception as e:
            logger.error(f"Error saving downloads state: {e}")

    def add_task(self, game_id, game_name, url, dest_path,
                 callback_progress=None, callback_finished=None,
                 callback_error=None, callback_status=None):
        """Добавляет задачу загрузки"""
        with self._lock:
            for task in self.tasks.values():
                if task.game_id == game_id and task.status in ["downloading", "paused", "pending"]:
                    return False

            self.task_counter += 1
            task = DownloadTask(
                task_id=self.task_counter,
                game_id=game_id,
                game_name=game_name,
                url=url,
                dest_path=dest_path,
                callback_progress=callback_progress,
                callback_finished=callback_finished,
                callback_error=callback_error,
                callback_status=callback_status
            )
            self.tasks[self.task_counter] = task

            if len([t for t in self.tasks.values() if t.status == "downloading"]) < self.max_parallel:
                self._start_task(task)
            else:
                task.status = "pending"

            self._save_state()
            return True

    def _start_task(self, task):
        """Запускает задачу в отдельном потоке"""
        task.thread = threading.Thread(target=task.run)
        task.thread.daemon = True
        task.thread.start()
        logger.info(f"Started download task {task.task_id}: {task.game_name}")

    def _process_queue(self):
        """Обрабатывает очередь задач"""
        with self._lock:
            active = len([t for t in self.tasks.values() if t.status == "downloading"])
            while self.queue and active < self.max_parallel:
                task = self.queue.pop(0)
                if task.status == "pending":
                    self._start_task(task)
                    active += 1

    def pause_task(self, task_id):
        """Приостанавливает задачу"""
        if task_id in self.tasks:
            self.tasks[task_id].pause()
            self._save_state()

    def resume_task(self, task_id):
        """Возобновляет задачу"""
        if task_id in self.tasks:
            self.tasks[task_id].resume()
            self._save_state()

    def cancel_task(self, task_id):
        """Отменяет задачу"""
        if task_id in self.tasks:
            self.tasks[task_id].cancel()
            self._save_state()

    def remove_task(self, task_id):
        """Удаляет завершённую задачу"""
        with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.status in ["completed", "cancelled", "error"]:
                    del self.tasks[task_id]
                    self._process_queue()
                    self._save_state()

    def get_active_tasks(self):
        """Возвращает список активных задач"""
        return [task for task in self.tasks.values()
                if task.status in ["downloading", "paused", "pending"]]

    def get_all_tasks(self):
        """Возвращает все задачи"""
        return list(self.tasks.values())

    def shutdown(self):
        """Завершает работу менеджера"""
        self._running = False
        for task in self.tasks.values():
            if task.status in ["downloading", "paused"]:
                task.pause()
        self._save_state()
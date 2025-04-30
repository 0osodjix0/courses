import os
import logging
import random
import psycopg2
from aiogram.exceptions import TelegramAPIError
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate
from aiogram.types import BufferedInputFile
from collections import namedtuple
from dotenv import load_dotenv
from typing import Optional
from psycopg2 import OperationalError, IntegrityError
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from urllib.parse import urlparse
from contextlib import contextmanager
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, BaseFilter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram import BaseMiddleware
from datetime import datetime
from aiogram.enums import ParseMode 
from aiogram.types import (
    Message,
    CallbackQuery,
    InputMediaPhoto,
    InputMediaDocument,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup
)
from aiogram.utils.media_group import MediaGroupBuilder

# Настройка хранилища состояний
storage = MemoryStorage()

# Конфигурация логгера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv('TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')
DATABASE_URL = os.getenv('DATABASE_URL')

# Парсинг URL базы данных
parsed_db = urlparse(DATABASE_URL)

class CleanupMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if event.text in ["❌ Отмена", "🔙 Назад"]:
            state = data.get("fsm_context")
            if state:
                await state.clear()
        return await handler(event, data)

class Database:
    def __init__(self):
        self.conn = None
        self._connect()
        self._init_tables()
        self._check_connection()

    def _check_connection(self):
        with self.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone()[0] != 1:
                raise ConnectionError("Database connection failed")
            
    def _connect(self):
        """Установка соединения с PostgreSQL"""
        try:
            self.conn = psycopg2.connect(
                dbname=parsed_db.path[1:],
                user=parsed_db.username,
                password=parsed_db.password,
                host=parsed_db.hostname,
                port=parsed_db.port,
                sslmode='require'
            )
            self.conn.autocommit = False
        except OperationalError as e:
            logger.critical(f"Ошибка подключения к базе данных: {e}")
            raise

import logging
from contextlib import contextmanager
from psycopg2 import OperationalError
from urllib.parse import urlparse
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.state import State, StatesGroup

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.conn = None
        self._connect()
        self._init_tables()
        self._check_connection()

    def _check_connection(self):
        with self.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone()[0] != 1:
                raise ConnectionError("Database connection failed")
            
    def _connect(self):
        """Установка соединения с PostgreSQL"""
        try:
            self.conn = psycopg2.connect(
                dbname=parsed_db.path[1:],
                user=parsed_db.username,
                password=parsed_db.password,
                host=parsed_db.hostname,
                port=parsed_db.port,
                sslmode='require'
            )
            self.conn.autocommit = False
        except OperationalError as e:
            logger.critical(f"Ошибка подключения к базе данных: {e}")
            raise

    def _init_tables(self):
        """Инициализация таблиц в PostgreSQL"""
        try:
            with self.conn.cursor() as cursor:
                # Создание таблиц в правильном порядке
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        full_name TEXT NOT NULL,
                        current_course INTEGER,
                        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS courses (
                        course_id SERIAL PRIMARY KEY,
                        title TEXT UNIQUE NOT NULL,
                        description TEXT,
                        media_id TEXT
                    )''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS modules (
                        module_id SERIAL PRIMARY KEY,
                        course_id INTEGER NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
                        title TEXT NOT NULL,
                        media_id TEXT
                    )''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id SERIAL PRIMARY KEY,
                        module_id INTEGER NOT NULL REFERENCES modules(module_id) ON DELETE CASCADE,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        file_id TEXT,
                        file_type VARCHAR(10)
                    )''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS final_tasks (
                        final_task_id SERIAL PRIMARY KEY,
                        course_id INTEGER NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        file_id TEXT,
                        file_type VARCHAR(10)
                    )''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS submissions (
                        submission_id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                        task_id INTEGER NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                        status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected')),
                        score INTEGER CHECK(score BETWEEN 0 AND 100),
                        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        file_id TEXT,
                        content TEXT,
                        file_type VARCHAR(10)
                    )''')

                # Создание индексов
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_submissions_status 
                    ON submissions(status)''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_submissions_user_task 
                    ON submissions(user_id, task_id)''')

                # Добавление недостающих колонок
                self._safe_add_column(cursor, 'tasks', 'file_type', 'VARCHAR(10)')
                self._safe_add_column(cursor, 'submissions', 'file_type', 'VARCHAR(10)')

                self.conn.commit()
                
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка инициализации таблиц: {e}")
            raise

    def _safe_add_column(self, cursor, table, column, col_type):
        """Безопасное добавление колонки если не существует"""
        try:
            cursor.execute(
                f"ALTER TABLE {table} "
                f"ADD COLUMN IF NOT EXISTS {column} {col_type}"
            )
        except Exception as e:
            logger.warning(f"Ошибка добавления колонки {column}: {e}")
            self.conn.rollback()
            
    def is_course_completed(self, user_id: int, course_id: int) -> bool:
        """Проверяет выполнение всех заданий курса"""
        with self.cursor() as cursor:
            cursor.execute('''
                SELECT COUNT(t.task_id) = COUNT(s.task_id)
                FROM tasks t
                LEFT JOIN modules m ON t.module_id = m.module_id
                LEFT JOIN submissions s 
                    ON t.task_id = s.task_id 
                    AND s.user_id = %s 
                    AND s.status = 'accepted'
                WHERE m.course_id = %s
            ''', (user_id, course_id))
            result = cursor.fetchone()
            return result[0] if result else False

    @contextmanager
    def cursor(self):
        """Контекстный менеджер для работы с курсором"""
        cursor = None
        try:
            cursor = self.conn.cursor()
            yield cursor
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка транзакции: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    def close(self):
        """Закрытие соединения с базой данных"""
        if self.conn and not self.conn.closed:
            self.conn.close()
            logger.info("Соединение с базой данных закрыто")
                
# Инициализация объектов
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot=bot, storage=storage)  # Передаем bot явно
db = Database()

dp.message.middleware(CleanupMiddleware())

class Form(StatesGroup):
    full_name = State()
    course_selection = State()

class AdminForm(StatesGroup):
    add_course_title = State()
    add_course_description = State()
    add_course_media = State()
    add_module_title = State()
    add_module_media = State()
    add_task_title = State()
    add_task_content = State()
    add_task_media = State()
    delete_course = State()
    add_final_task_title = State()
    add_final_task_content = State()
    add_final_task_media = State()
    review_final_task = State()
    edit_content_type = State()
    edit_course = State()
    edit_module = State()
    edit_task = State()
    edit_final_task = State()
    delete_confirmation = State()
    edit_title = State()
    edit_description = State()
    edit_media = State()
    edit_select_item = State()
    
class TaskStates(StatesGroup):
    waiting_for_solution = State()
    waiting_for_retry = State()
    waiting_for_final_solution = State()
    waiting_final_solution = State()
    
def main_menu() -> types.ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    # Для Reply-кнопок указываем только текст
    builder.button(text="📚 Выбрать курс")
    builder.button(text="🆘 Поддержка")
    # Настройка расположения кнопок (2 кнопки в ряд)
    builder.adjust(2)
    # Возвращаем клавиатуру с настройками
    return builder.as_markup(
        resize_keyboard=True,    # Автоматический размер кнопок
        one_time_keyboard=False  # Клавиатура остается открытой
    )
    
def task_keyboard(task_id: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Отправить решение", callback_data=f"submit_{task_id}")
    builder.button(text="🔄 Отправить исправление", callback_data=f"retry_{task_id}")
    builder.button(text="🔙 Назад к модулю", callback_data=f"module_from_task_{task_id}")
    builder.adjust(1)
    return builder.as_markup(
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите действие"
    )
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📋 К списку заданий", 
        callback_data=f"list_tasks_{task_data[0]}"  # передаем module_id
    )

# Обработчики для текстовых команд
@dp.message(F.text.startswith("✏️ Отправить решение"))
async def handle_submit_solution(message: Message, state: FSMContext):
    try:
        task_id = int(message.text.split()[-1])
        await message.answer("📤 Отправьте ваше решение (текст или файл):", reply_markup=ReplyKeyboardRemove())
        await state.set_state(TaskStates.waiting_for_solution)
        await state.update_data(task_id=task_id)
    except Exception as e:
        logger.error(f"Submit error: {str(e)}")
        await message.answer("❌ Ошибка отправки решения")

@dp.errors()
async def global_error_handler(update: types.Update, exception: Exception):
    logger.error(f"Critical error: {exception}", exc_info=True)
    
    try:
        error_msg = f"🚨 Error: {str(exception)[:2000]}"
        await bot.send_message(ADMIN_ID, error_msg)
        
        if update.message:
            await update.message.answer("❌ Произошла ошибка, попробуйте позже")
        elif update.callback_query:
            await update.callback_query.answer("⚠️ Ошибка обработки", show_alert=True)
            
    except Exception as e:
        logger.error(f"Error handler error: {e}")
    
    return True

# Добавляем обработчик проверки курса
@dp.callback_query(F.data.startswith("check_final_"))
async def check_final_task(callback: CallbackQuery):
    course_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    if db.is_course_completed(user_id, course_id):
        await callback.message.answer(
            "🎉 Вы выполнили все задания курса! Можете приступить к итоговому заданию:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎓 Итоговое задание",
                            callback_data=f"final_task_{course_id}"
                        )
                    ]
                ]
            )  # Закрывающая скобка для reply_markup
        )  # Закрывающая скобка для answer()
    else:
        await callback.answer("❌ Сначала завершите все задания курса!", show_alert=True)

# Модифицируем клавиатуру курса
def course_details_keyboard(course_id: int, user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # Кнопки модулей
    ...
    
    # Кнопка итогового задания
    builder.button(
        text="🎓 Итоговое задание" if db.is_course_completed(user_id, course_id) else "🔒 Итоговое (недоступно)",
        callback_data=f"check_final_{course_id}"
    )
    
    builder.button(text="🔙 Назад", callback_data="all_courses")
    builder.adjust(1)
    return builder.as_markup()

@dp.callback_query(F.data.startswith("accept_"))
async def accept_submission(callback: CallbackQuery):
    # ... предыдущая логика обработки
    
    if db.is_course_completed(user_id, course_id):
        await bot.send_message(
            user_id,
            "🎉 Вы завершили все задания курса! Теперь доступно итоговое задание.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎓 Перейти к итоговому заданию",
                            callback_data=f"final_task_{course_id}"
                        )
                    ]
                ]
            )
        )  # Закрыты 2 скобки: для reply_markup и send_message

# Обработчик итогового задания
@dp.callback_query(F.data.startswith("final_task_"))
async def show_final_task(callback: CallbackQuery, state: FSMContext):
    course_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    if not db.is_course_completed(user_id, course_id):
        await callback.answer("❌ Сначала завершите все задания курса!", show_alert=True)
        return

    # Получение данных итогового задания
    with db.cursor() as cursor:
        cursor.execute('''
            SELECT title, content, file_id, file_type 
            FROM final_tasks 
            WHERE course_id = %s
        ''', (course_id,))
        final_task = cursor.fetchone()

    if not final_task:
        await callback.answer("❌ Итоговое задание не найдено", show_alert=True)
        return
        
    title, content, file_id, file_type = final_task
    
    # Отправка задания
    ...

    await callback.message.answer("📤 Отправьте ваше решение итогового задания:")
    await state.set_state(TaskStates.waiting_final_solution)
    await state.update_data(course_id=course_id)

@dp.message(F.text.startswith("🔄 Отправить исправление"))
async def handle_retry_solution(message: Message, state: FSMContext):
    try:
        task_id = int(message.text.split()[-1])
        # Логика для повторной отправки
        await message.answer("🔄 Отправьте исправленное решение:", reply_markup=ReplyKeyboardRemove())
        await state.set_state(TaskStates.waiting_for_solution)
        await state.update_data(task_id=task_id)
    except Exception as e:
        logger.error(f"Retry error: {str(e)}")
        await message.answer("❌ Ошибка отправки исправления")

@dp.message(F.text.startswith("🔙 Назад к модулю"))
async def handle_back_to_module(message: Message):
    try:
        task_id = int(message.text.split()[-1])
        # Логика возврата к модулю
        await show_module_by_task(message, task_id)
    except Exception as e:
        logger.error(f"Back error: {str(e)}")
        await message.answer("❌ Ошибка возврата", reply_markup=ReplyKeyboardRemove())

async def show_module_by_task(message: Message, task_id: int):
    with db.cursor() as cursor:
        cursor.execute('''
            SELECT m.module_id, m.title 
            FROM tasks t
            JOIN modules m ON t.module_id = m.module_id
            WHERE t.task_id = %s
        ''', (task_id,))
        module_data = cursor.fetchone()
    
    if module_data:
        await message.answer(
            f"📦 Модуль: {module_data[1]}",
            reply_markup=module_tasks_keyboard(module_data[0])
        )
    else:
        await message.answer("❌ Модуль не найден")

def module_tasks_keyboard(module_id: int) -> types.ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    # Добавление кнопок заданий модуля
    return builder.as_markup()

def modules_kb(course_id: int) -> types.InlineKeyboardMarkup:
    """Генерирует клавиатуру с модулями курса"""
    builder = InlineKeyboardBuilder()
    
    try:
        with db.cursor() as cursor:
            # Проверяем существование курса
            cursor.execute("SELECT 1 FROM courses WHERE course_id = %s", (course_id,))
            if not cursor.fetchone():
                builder.button(text="❌ Курс не найден", callback_data="course_error")
                return builder.as_markup()

            # Получаем модули курса
            cursor.execute(
                "SELECT module_id, title FROM modules WHERE course_id = %s ORDER BY module_id",
                (course_id,)
            )
            modules = cursor.fetchall()

            if modules:
                for module_id, title in modules:
                    builder.button(
                        text=f"📦 {title}",
                        callback_data=f"module_{module_id}"
                    )
                builder.button(text="🔙 К списку курсов", callback_data="all_courses")
            else:
                builder.button(text="❌ Нет доступных модулей", callback_data="no_modules")
            
            builder.adjust(1)

    except Exception as e:
        logger.error(f"Ошибка формирования клавиатуры модулей: {e}")
        builder.button(text="⚠️ Ошибка загрузки", callback_data="error")
    
    return builder.as_markup()

# Добавляем обработчик для кнопки "Назад к модулю"
@dp.callback_query(F.data.startswith("module_from_task_"))
async def back_to_module_handler(callback: types.CallbackQuery):
    try:
        task_id = int(callback.data.split("_")[-1])
        
        with db.cursor() as cursor:
            # Получаем module_id по task_id
            cursor.execute('''
                SELECT module_id 
                FROM tasks 
                WHERE task_id = %s
            ''', (task_id,))
            result = cursor.fetchone()
            
            if not result:
                await callback.answer("❌ Модуль не найден")
                return
                
            module_id = result[0]
        
        # Вызываем обработчик модуля с полученным ID
        await handle_module_selection(callback, module_id)
        
    except Exception as e:
        logger.error(f"Ошибка возврата к модулю: {e}")
        await callback.answer("❌ Ошибка загрузки модуля")

# Модифицируем существующий обработчик модуля
async def handle_module_selection(callback: types.CallbackQuery, module_id: int):
    try:
        with db.cursor() as cursor:
            cursor.execute('''
                SELECT m.title, m.course_id, c.title 
                FROM modules m
                JOIN courses c ON m.course_id = c.course_id
                WHERE m.module_id = %s
            ''', (module_id,))
            module_data = cursor.fetchone()
            
            if not module_data:
                await callback.answer("❌ Модуль не найден")
                return

            module_title, course_id, course_title = module_data

            cursor.execute(
                "SELECT task_id, title FROM tasks WHERE module_id = %s",
                (module_id,)
            )
            tasks = cursor.fetchall()

        builder = InlineKeyboardBuilder()
        
        if tasks:
            for task_id, title in tasks:
                builder.button(
                    text=f"📝 {title}",
                    callback_data=f"task_{task_id}"
                )
            
            builder.button(
                text="🔙 К модулям курса", 
                callback_data=f"course_{course_id}"
            )
            builder.adjust(1)
            
            await callback.message.edit_text(
                f"📚 Курс: {course_title}\n📦 Модуль: {module_title}\n\nВыберите задание:",
                reply_markup=builder.as_markup()
            )
        else:
            await callback.answer("ℹ️ В этом модуле пока нет заданий")

    except Exception as e:
        logger.error(f"Ошибка загрузки модуля: {e}")
        await callback.answer("❌ Ошибка загрузки модуля")
    
def cancel_button():
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel")
    return builder.as_markup()

def support_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📨 Написать в поддержку", url=f"tg://user?id={ADMIN_ID}")
    builder.button(text="🔙 Назад", callback_data="main_menu")  # Правильный callback_data
    builder.adjust(1)
    return builder.as_markup()

@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("submit_"))
async def handle_submit_solution(callback: types.CallbackQuery, state: FSMContext):
    try:
        task_id = int(callback.data.split("_")[1])
        user_id = callback.from_user.id
        
        # Проверяем существование задания
        with db.cursor() as cursor:
            cursor.execute('''
                SELECT m.module_id, m.title, 
                (SELECT status FROM submissions 
                 WHERE user_id = %s AND task_id = %s 
                 ORDER BY submitted_at DESC LIMIT 1)
                FROM tasks t
                JOIN modules m ON t.module_id = m.module_id
                WHERE t.task_id = %s
            ''', (user_id, task_id, task_id))
            data = cursor.fetchone()
            
        if not data:
            await callback.answer("❌ Задание не найдено")
            return
            
        module_id, module_title, last_status = data

        # Если решение уже отправлено и не отклонено
        if last_status and last_status != 'rejected':
            await callback.answer("⏳ Решение уже отправлено на проверку")
            return

        # Сохраняем данные в состоянии
        await state.update_data(
            task_id=task_id,
            module_id=module_id,
            module_title=module_title,
            is_retry=last_status == 'rejected'
        )
        await callback.message.answer(
        "📤 Отправьте ваше решение:",
        reply_markup=cancel_keyboard()  
        )
        # Создаем временную клавиатуру
        builder = ReplyKeyboardBuilder()
        builder.button(text="❌ Отмена")
        
        # Редактируем сообщение вместо удаления
        await callback.message.edit_reply_markup()
        
        # Отправляем запрос на решение
        await callback.message.answer(
            f"📤 {'Исправьте' if last_status == 'rejected' else 'Отправьте'} "
            f"решение для задания из модуля '{module_title}':\n"
            "Можно отправить текст, фото или документ",
            reply_markup=builder.as_markup(
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )
        await state.set_state(TaskStates.waiting_for_solution)
        await callback.answer()

    except Exception as e:
        logger.error(f"Submit error: {str(e)}")
        await callback.answer("❌ Ошибка начала отправки решения")

@dp.message(
    TaskStates.waiting_for_solution,
    F.content_type.in_({'text', 'document', 'photo'}),
    ~F.text.in_(["❌ Отмена", "🔙 Назад"])  # Игнорируем кнопки отмены
)
async def process_solution(message: Message, state: FSMContext):
    # Получаем данные из состояния
    data = await state.get_data()
    task_id = data.get('task_id')
    
    try:
        # Обработка файла
        file_type = None
        file_id = None
        
        if message.document:
            file_type = 'document'
            file_id = message.document.file_id
        elif message.photo:
            file_type = 'photo'
            file_id = message.photo[-1].file_id

        # Сохранение в БД
        with db.cursor() as cursor:
            cursor.execute('''
                INSERT INTO submissions 
                (user_id, task_id, content, file_id, file_type)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING submission_id
            ''', (
                message.from_user.id,
                task_id,
                message.text or None,
                file_id,
                file_type
            ))
            submission_id = cursor.fetchone()[0]

        # Уведомление админа
        await notify_admin(submission_id)
        
        # Успешное завершение
        await message.answer(
            "✅ Решение успешно отправлено на проверку!",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Показ списка заданий модуля
        await show_module_tasks(message, data['module_id'], message.from_user.id)

    except Exception as e:
        logger.error(f"Solution processing error: {str(e)}")
        await message.answer(
            "❌ Ошибка при отправке решения",
            reply_markup=ReplyKeyboardRemove()
        )
    finally:
        await state.clear()

async def show_module_tasks(message: types.Message, module_id: int, user_id: int):
    """Показывает задания модуля с учетом статуса решений"""
    try:
        with db.cursor() as cursor:
            # SQL-запрос (должен включать task_id, task_title и статус)
            cursor.execute('''
                SELECT 
                    m.title AS module_title,
                    c.title AS course_title,
                    m.course_id,
                    t.task_id,
                    t.title AS task_title,
                    COALESCE(s.status, 'not_started') AS status
                FROM modules m
                JOIN courses c ON m.course_id = c.course_id
                JOIN tasks t ON m.module_id = t.module_id
                LEFT JOIN LATERAL (
                    SELECT status 
                    FROM submissions 
                    WHERE user_id = %s 
                    AND task_id = t.task_id 
                    ORDER BY submitted_at DESC 
                    LIMIT 1
                ) s ON true
                WHERE m.module_id = %s
                ORDER BY t.task_id
            ''', (user_id, module_id))
            
            results = cursor.fetchall()
            
            if not results:
                await message.answer("❌ Модуль не найден")
                return

            # Извлекаем общую информацию о модуле и курсе
            module_title = results[0][0]
            course_title = results[0][1]
            course_id = results[0][2]

            # Создаем клавиатуру
            builder = InlineKeyboardBuilder()

            # Ваш блок начинается здесь
            for row in results:
                *_, task_id, task_title, last_status = row
                
                # Определяем текущий статус
                status = last_status if last_status else 'not_started'
                
                # Формируем элементы кнопки
                status_info = {
                    'accepted': {'icon': '✅', 'text': f"{task_title} (Принято)"},
                    'rejected': {'icon': '❌', 'text': f"{task_title} (Требует правок)"},
                    'pending': {'icon': '⏳', 'text': f"{task_title} (На проверке)"},
                    'not_started': {'icon': '📝', 'text': task_title}
                }.get(status, {'icon': '📝', 'text': task_title})
                
                # Добавляем кнопку задания
                builder.button(
                    text=f"{status_info['icon']} {status_info['text']}",
                    callback_data=f"task_{task_id}" if status != 'accepted' else f"completed_{task_id}"
                )
            # Ваш блок заканчивается здесь

            # Навигационные кнопки
            nav_builder = InlineKeyboardBuilder()
            nav_builder.button(text="🔙 К курсу", callback_data=f"course_{course_id}")
            nav_builder.button(text="🏠 В главное меню", callback_data="main_menu")
            nav_builder.adjust(2)

            # Комбинируем клавиатуры
            builder.attach(nav_builder)
            builder.adjust(1, 2, 2)  # Настройка расположения

            # Отправляем сообщение
            await message.answer(
                f"📚 Курс: {course_title}\n"
                f"📦 Модуль: {module_title}\n\n"
                "Статус заданий:\n"
                "✅ - принято\n❌ - отклонено\n⏳ - на проверке\n📝 - не начато",
                reply_markup=builder.as_markup()
            )

    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        await message.answer("❌ Не удалось загрузить задания")
        
@dp.callback_query(F.data.startswith("info_"))
async def show_task_info(callback: CallbackQuery):
    task_id = int(callback.data.split('_')[1])
    await callback.answer(
        "Это задание уже проверено!\n"
        "Статус: " + ("Принято" if 'accepted' in callback.data else "На проверке"),
        show_alert=True
    )
    
@dp.callback_query(F.data.startswith("completed_"))
async def handle_completed_task(callback: types.CallbackQuery):
    task_id = callback.data.split("_")[1]
    await callback.answer(
        "✅ Это задание уже успешно выполнено!\n"
        "Вы можете переходить к следующим заданиям.",
        show_alert=True
    )
    await callback.message.delete()

@dp.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu()
    )
    await callback.answer()

# Новый обработчик для выполненных заданий
@dp.callback_query(F.data.startswith("completed_task_"))
async def handle_completed_task(callback: CallbackQuery):
    task_id = int(callback.data.split('_')[2])
    await callback.answer(
        "✅ Это задание уже успешно выполнено!\n"
        "Переходите к следующим заданиям.",
        show_alert=True
    )

@dp.callback_query(F.data.startswith("retry_"))
async def handle_retry_solution(callback: types.CallbackQuery):
    try:
        task_id = int(callback.data.split("_")[1])
        await callback.answer()
        await handle_submit_solution(callback, task_id=task_id)
    except Exception as e:
        logger.error(f"Retry error: {str(e)}")
        await callback.answer("❌ Ошибка запроса на исправление")
    
@dp.message(F.text == "🆘 Поддержка")
async def support_handler(message: Message):
    text = (
        "🛠 Техническая поддержка\n\n"
        "Если у вас возникли проблемы:\n"
        "1. Опишите подробно свой вопрос\n"
        "2. Приложите скриншоты (если нужно)\n"
        "3. Нажмите кнопку ниже для связи"
    )
    await message.answer(text, reply_markup=support_keyboard())

@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()
    
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE user_id = %s", (message.from_user.id,))
        user = cursor.fetchone()
    
    if user:
        # Пользователь уже зарегистрирован
        await message.answer(
            f"Добро пожаловать, {user[1]}!", 
            reply_markup=ReplyKeyboardRemove()
        )
        await message.answer(
            "Выберите действие:", 
            reply_markup=main_menu()
        )
    else:
        # Новый пользователь, начинаем регистрацию
        await message.answer(
            "📝 Давай познакомимся! Для начала регистрации введи свое ФИО. "
            "Это нужно, чтобы твой наставник мог оценивать задания и давать обратную связь.\n"
            "Напиши своё полное имя, фамилию и отчество:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(Form.full_name)

@dp.message(Form.full_name)
async def process_full_name(message: types.Message, state: FSMContext):
    if len(message.text.split()) < 2:
        await message.answer("❌ Введите полное ФИО (минимум 2 слова)")
        return
    
    try:
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (user_id, full_name) VALUES (%s, %s)",
                (message.from_user.id, message.text)
            )
        await message.answer("✅ Регистрация завершена!", reply_markup=main_menu())
        await state.clear()
    except IntegrityError:
        await message.answer("❌ Пользователь уже зарегистрирован")
        await state.clear()

async def handle_media(message: Message):
    if message.photo:
        return {'type': 'photo', 'file_id': message.photo[-1].file_id}
    elif message.document:
        return {'type': 'document', 'file_id': message.document.file_id}
    return None

def courses_kb() -> types.InlineKeyboardMarkup:
    """Клавиатура с курсами и кнопкой Назад"""
    builder = InlineKeyboardBuilder()
    
    with db.cursor() as cursor:
        cursor.execute("SELECT course_id, title FROM courses")
        courses = cursor.fetchall()

    for course in courses:
        builder.button(
            text=f"📘 {course[1]}", 
            callback_data=f"course_{course[0]}"
        )
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()
    
    builder.button(text="🔙 Назад", callback_data="main_menu")
    
    builder.adjust(1)
    return builder.as_markup(
        resize_keyboard=True,
        one_time_keyboard=True
    )

@dp.message(F.text == "📚 Выбрать курс")
async def show_courses(message: types.Message):
    with db.cursor() as cursor:
        cursor.execute(
            """SELECT c.title 
            FROM users u
            LEFT JOIN courses c ON u.current_course = c.course_id 
            WHERE u.user_id = %s""", 
            (message.from_user.id,)
        )
        current_course = cursor.fetchone()
    
    text = "В этом разделе ты можешь выбрать курс, в котором будут модули с заданиями. Выполняй их и отправляй на проверку! 🚀 \n\n"
    if current_course and current_course[0]:
        text += f"🎯 Текущий курс: {current_course[0]}\n\n"
    text += "👇 Выберите курс:"
    
    await message.answer(text, reply_markup=courses_kb())

# Обработчик выбора курса@dp.callback_query(F.data.startswith("course_"))
async def select_course(callback: types.CallbackQuery):
    try:
        # Формирование клавиатуры
        kb = modules_kb(course_id)
        
        # Добавляем кнопку итогового задания
        with db.cursor() as cursor:
            cursor.execute("SELECT 1 FROM final_tasks WHERE course_id = %s", (course_id,))
            if cursor.fetchone():
                builder = InlineKeyboardBuilder()
                builder.button(
                    text="🎓 Итоговое задание", 
                    callback_data=f"final_task_{course_id}"
                )
                # Добавляем к существующей клавиатуре
                kb.inline_keyboard.extend(builder.export())

        # Отправка сообщения с обновленной клавиатурой
        if media_id:
            await callback.message.delete()
            await callback.message.answer_photo(
                media_id,
                caption=response_text,
                reply_markup=kb
            )
        else:
            await callback.message.edit_text(
                text=response_text,
                reply_markup=kb
            )

        # Разбираем callback_data с защитой от переполнения
        _, *rest = callback.data.split('_', maxsplit=1)
        if not rest:
            raise ValueError("Неверный формат данных")
        
        course_part = rest[0]
        logger.debug(f"Attempting to process course: {course_part}")

        # Глубокая проверка числового формата
        if not course_part.isdecimal():
            raise ValueError(f"Некорректный формат ID: {course_part}")
            
        course_id = int(course_part)
        
        # Валидация существования курса
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS(
                    SELECT 1 
                    FROM courses 
                    WHERE course_id = %s
                )""", (course_id,))
            exists = cursor.fetchone()[0]
            
            if not exists:
                raise ValueError(f"Курс {course_id} не существует")

            # Атомарная транзакция
            cursor.execute("""
                WITH user_update AS (
                    UPDATE users 
                    SET current_course = %s 
                    WHERE user_id = %s
                    RETURNING *
                )
                SELECT 
                    c.title,
                    c.media_id
                FROM courses c
                WHERE c.course_id = %s""", 
                (course_id, callback.from_user.id, course_id))
                
            course_data = cursor.fetchone()
            
            if not course_data:
                raise RuntimeError("Данные курса не найдены")

        title, media_id = course_data
        
        # Формирование ответа
        kb = modules_kb(course_id)  # Гарантированно безопасный вызов
        response_text = f"📚 Курс: {title}\nВыберите модуль:"

        if media_id:
            await callback.message.delete()
            await callback.message.answer_photo(
                media_id,
                caption=response_text,
                reply_markup=kb
            )
        else:
            await callback.message.edit_text(
                text=response_text,
                reply_markup=kb
            )

    except ValueError as e:
        logger.warning(f"Validation error: {str(e)}")
        await callback.answer(
            "⚠️ Невозможно обработать этот курс",
            show_alert=True,
            cache_time=60
        )
    except Exception as e:
        logger.critical(
            f"Critical error in course selection: {traceback.format_exc()}"
        )
        await callback.answer(
            "⛔ Произошла критическая ошибка. Попробуйте позже.",
            show_alert=True
        )
        await bot.send_message(
            ADMIN_ID,
            f"🚨 Course selection error:\n{str(e)[:300]}"
        )
        reply_kb = ReplyKeyboardBuilder()
        reply_kb.button(text="🏠 В главное меню")
        await callback.message.answer(
            "Выберите действие:",
            reply_markup=reply_kb.as_markup(
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )

# Клавиатура модулей курса
async def modules_keyboard(course_id: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    try:
        with db.cursor() as cursor:
            # Получаем список модулей для курса
            cursor.execute(
                "SELECT module_id, title FROM modules WHERE course_id = %s ORDER BY module_id",
                (course_id,)
            )
            modules = cursor.fetchall()

            if modules:
                for module_id, title in modules:
                    builder.button(
                        text=f"📦 {title}",
                        callback_data=f"module_{module_id}"
                    )
            else:
                builder.button(
                    text="❌ Нет доступных модулей",
                    callback_data="no_modules_placeholder"
                )

    except OperationalError as e:
        logger.error(f"Database error: {str(e)}")
        builder.button(
            text="⚠️ Ошибка загрузки модулей",
            callback_data="module_load_error"
        )
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        builder.button(
            text="⚠️ Системная ошибка",
            callback_data="system_error"
        )
    finally:
        # Всегда добавляем кнопку возврата
        builder.button(
            text="🔙 К списку курсов",
            callback_data="all_courses"
        )

    builder.adjust(1)
    return builder.as_markup()

# Блок показа конкретного задания
@dp.callback_query(F.data.startswith("task_"))
async def handle_task_selection(callback: types.CallbackQuery, state: FSMContext):
    try:
        task_id = int(callback.data.split('_')[1])
        user_id = callback.from_user.id
        
        # Получаем данные задания из БД
        with db.cursor() as cursor:
            # Запрос данных задания и статуса
            cursor.execute('''
                SELECT 
                    t.module_id,
                    t.title,
                    t.content,
                    t.file_id,
                    t.file_type,
                    m.course_id,
                    s.status
                FROM tasks t
                JOIN modules m ON t.module_id = m.module_id
                LEFT JOIN (
                    SELECT task_id, status 
                    FROM submissions 
                    WHERE user_id = %s 
                    ORDER BY submitted_at DESC 
                    LIMIT 1
                ) s ON t.task_id = s.task_id
                WHERE t.task_id = %s
            ''', (user_id, task_id))
            
            task_data = cursor.fetchone()

        # Проверяем наличие задания
        if not task_data:
            await callback.answer("❌ Задание не найдено", show_alert=True)
            return

        # Распаковываем данные
        (module_id, title, content, 
         file_id, file_type, 
         course_id, status) = task_data

        # Проверяем статус задания
        if status == 'accepted':
            await callback.answer("✅ Задание уже выполнено!", show_alert=True)
            return

        # Сохраняем данные в состоянии
        await state.update_data(
            current_module=module_id,
            task_id=task_id
        )

        # Создаем клавиатуру
        inline_builder = InlineKeyboardBuilder()
        if status != 'accepted':
            inline_builder.button(
                text="✏️ Отправить решение" if status != 'rejected' else "🔄 Исправить",
                callback_data=f"submit_{task_id}"
            )
        inline_builder.button(
            text="🔙 Назад к заданиям",
            callback_data=f"module_{module_id}"
        )
        inline_builder.adjust(1)

        # Удаляем предыдущее сообщение с обработкой ошибок
        try:
            await callback.message.delete()
        except Exception as delete_error:
            logger.error(f"Ошибка удаления сообщения: {delete_error}")

        # Отправка контента
        try:
            if file_id and file_type:
                if file_type == 'photo':
                    await callback.message.answer_photo(
                        file_id,
                        caption=f"📌 {title}\n\n{content}",
                        reply_markup=inline_builder.as_markup()
                    )
                elif file_type == 'document':
                    await callback.message.answer_document(
                        file_id,
                        caption=f"📌 {title}\n\n{content}",
                        reply_markup=inline_builder.as_markup()
                    )
                else:
                    await callback.message.answer(
                        f"📌 {title}\n\n{content}\n\n⚠️ Неподдерживаемый тип файла",
                        reply_markup=inline_builder.as_markup()
                    )
            else:
                await callback.message.answer(
                    f"📌 {title}\n\n{content}",
                    reply_markup=inline_builder.as_markup()
                )
                
        except Exception as media_error:
            logger.error(f"Ошибка отправки медиа: {media_error}")
            await callback.message.answer(
                "❌ Не удалось загрузить задание",
                reply_markup=inline_builder.as_markup()
            )

    except Exception as e:
        logger.error(f"Ошибка выбора задания: {e}", exc_info=True)
        await callback.answer("❌ Ошибка загрузки задания")
        
@dp.callback_query(F.data.startswith("task_completed_"))
async def handle_completed_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split('_')[2])
    await callback.answer(
        "✅ Это задание уже выполнено!\n"
        "Переходите к следующему заданию.",
        show_alert=True
    )

@dp.message(F.text == "📋 Назад к заданиям")
async def back_to_tasks(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        module_id = data.get('current_module')
        
        if not module_id:
            raise ValueError("Текущий модуль не определен")

        # Формируем клавиатуру заданий
        keyboard = await generate_tasks_keyboard(module_id)
        
        # Удаляем предыдущую клавиатуру
        await message.answer(
            "Возвращаемся к списку заданий...",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Отправляем обновленный список
        msg = await message.answer(
            "📋 Список заданий модуля:",
            reply_markup=keyboard
        )
        # Сохраняем ID последнего сообщения
        await state.update_data(last_message_id=msg.message_id)

    except Exception as e:
        logger.error(f"Ошибка возврата: {str(e)}")
        await message.answer("❌ Не удалось загрузить задания", reply_markup=ReplyKeyboardRemove())

async def generate_tasks_keyboard(module_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    try:
        with db.cursor() as cursor:
            # Валидация модуля
            cursor.execute('SELECT 1 FROM modules WHERE module_id = %s', (module_id,))
            if not cursor.fetchone():
                raise ValueError("Модуль не существует")

            cursor.execute('''
                SELECT task_id, title 
                FROM tasks 
                WHERE module_id = %s
                ORDER BY task_id
            ''', (module_id,))
            tasks = cursor.fetchall()

            for task_id, title in tasks:
                builder.button(
                    text=f"📝 {title}",
                    callback_data=f"task_{task_id}"
                )
            
            builder.button(
                text="🔙 К модулям курса", 
                callback_data=f"course_{module_id}"
            )
            builder.adjust(1)
            
    except Exception as e:
        logger.error(f"Ошибка формирования клавиатуры: {str(e)}")
        builder.button(text="❌ Ошибка загрузки", callback_data="error")
        await message.answer("⚠️ Произошла ошибка при загрузке заданий")
    
    return builder.as_markup()

# Универсальный обработчик ошибок
@dp.errors()
async def global_error_handler(update: types.Update, exception: Exception):
    """Глобальный обработчик всех исключений"""
    logger.critical("Critical error: %s", exception, exc_info=True)
    
    try:
        if update.callback_query:
            await update.callback_query.answer("⚠️ Произошла ошибка", show_alert=True)
        elif update.message:
            await update.message.answer("🚨 Системная ошибка. Попробуйте позже.")
        
        await bot.send_message(
            ADMIN_ID,
            f"🔥 Ошибка:\n{exception}\n\nUpdate: {update.model_dump_json()}"
        )
    except Exception as e:
        logger.error("Ошибка в обработчике ошибок: %s", e)
    
    return True

@dp.message(F.text == "🏠 В главное меню")
async def handle_main_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Главное меню:",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )
    
# Унифицированный обработчик модулей
async def handle_module_selection(message: types.Message, module_id: int):
    try:
        with db.cursor() as cursor:
            # Получаем информацию о модуле и курсе
            cursor.execute('''
                SELECT m.title, m.course_id, c.title 
                FROM modules m
                JOIN courses c ON m.course_id = c.course_id
                WHERE m.module_id = %s
            ''', (module_id,))
            module_data = cursor.fetchone()
            
            if not module_data:
                await message.answer("❌ Модуль не найден")
                return

            module_title, course_id, course_title = module_data

            # Получаем список заданий
            cursor.execute('''
                SELECT task_id, title 
                FROM tasks 
                WHERE module_id = %s
            ''', (module_id,))
            tasks = cursor.fetchall()

        builder = InlineKeyboardBuilder()
        
        if tasks:
            for task_id, title in tasks:
                builder.button(
                    text=f"📝 {title}",
                    callback_data=f"task_{task_id}"
                )
            
            # Кнопка возврата к модулям курса
            builder.button(
                text="🔙 К модулям курса", 
                callback_data=f"course_{course_id}"
            )
            builder.adjust(1)
            
            # Исправлено: заменено message.message.edit_text на message.answer
            await message.answer(
                f"📚 Курс: {course_title}\n"
                f"📦 Модуль: {module_title}\n\n"
                "Выберите задание:",
                reply_markup=builder.as_markup()
            )
        else:
            await message.answer("ℹ️ В этом модуле пока нет заданий")
        
    except Exception as e:
        logger.error(f"Ошибка загрузки задания: {str(e)}")
        await message.answer("❌ Ошибка загрузки модуля")

# Обработчик кнопки возврата к модулю
@dp.callback_query(F.data.startswith("module_from_task_"))
async def back_to_module_handler(callback: types.CallbackQuery):
    try:
        task_id = int(callback.data.split("_")[-1])
        
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT module_id FROM tasks WHERE task_id = %s",
                (task_id,))
            result = cursor.fetchone()
            
            if not result:
                await callback.answer("❌ Модуль не найден")
                return
                
            module_id = result[0]
        
        await handle_module_selection(callback, module_id)
        
    except Exception as e:
        logger.error(f"Ошибка возврата к модулю: {e}")
        await callback.answer("❌ Ошибка загрузки модуля")

# Обертка для обработчика модулей
@dp.callback_query(F.data.startswith("module_"))
async def handle_module_selection(callback: types.CallbackQuery):
    try:
        module_id = int(callback.data.split('_')[1])
        
        # Удаляем предыдущее сообщение с клавиатурой
        try:
            await callback.message.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")

        # Получаем данные модуля
        with db.cursor() as cursor:
            cursor.execute('''
                SELECT m.title, c.title, m.course_id 
                FROM modules m
                JOIN courses c ON m.course_id = c.course_id
                WHERE m.module_id = %s
            ''', (module_id,))
            module_data = cursor.fetchone()

        if not module_data:
            await callback.answer("❌ Модуль не найден")
            return

        module_title, course_title, course_id = module_data

        # Получаем задания модуля
        with db.cursor() as cursor:
            cursor.execute('''
                SELECT task_id, title 
                FROM tasks 
                WHERE module_id = %s
            ''', (module_id,))
            tasks = cursor.fetchall()

        # Создаем новое сообщение вместо редактирования
        builder = InlineKeyboardBuilder()
        for task_id, title in tasks:
            builder.button(text=f"📝 {title}", callback_data=f"task_{task_id}")
        builder.button(text="🔙 К модулям", callback_data=f"course_{course_id}")
        builder.adjust(1)

        await callback.message.answer(
            f"📦 Модуль: {module_title}\nВыберите задание:",
            reply_markup=builder.as_markup()
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка обработки модуля: {e}")
        await callback.answer("❌ Ошибка загрузки модуля")

@dp.callback_query(F.data.startswith("your_pattern"))
async def handler(callback: CallbackQuery):
    try:
        # Удаляем предыдущую клавиатуру
        await callback.message.delete()
        
        # Создаем новое сообщение
        await callback.message.answer(...)
        
    except Exception as e:
        logger.error(...)
        await callback.answer(...)
        
        # Обработчик списка всех курсов
@dp.callback_query(F.data == "all_courses")
async def show_all_courses(callback: types.CallbackQuery):
    try:
        with db.cursor() as cursor:
            cursor.execute("SELECT course_id, title FROM courses")
            courses = cursor.fetchall()

        builder = InlineKeyboardBuilder()
        for course_id, title in courses:
            builder.button(
                text=f"📚 {title}", 
                callback_data=f"course_{course_id}"
            )
        
        builder.adjust(1)
        await callback.message.edit_text(
            "📚 Список доступных курсов:",
            reply_markup=builder.as_markup()
        )

    except Exception as e:
        logger.error(f"Ошибка загрузки курсов: {e}")
        await callback.answer("❌ Ошибка загрузки списка курсов")

### 2. Добавляем новый обработчик ###
@dp.callback_query(F.data.startswith("retry_"))
async def retry_submission(callback: CallbackQuery, state: FSMContext):
    try:
        task_id = int(callback.data.split("_")[1])
        user_id = callback.from_user.id
        
        with db.cursor() as cursor:
            # Проверяем наличие отклоненных решений
            cursor.execute('''
                SELECT submission_id FROM submissions
                WHERE user_id = %s AND task_id = %s AND status = 'rejected'
                ORDER BY submitted_at DESC LIMIT 1
            ''', (user_id, task_id))
            
            if not cursor.fetchone():
                await callback.answer("❌ Нет отклоненных решений для повторной отправки")
                return

            # Обновляем статус предыдущих решений
            cursor.execute('''
                UPDATE submissions 
                SET status = 'pending',
                    score = NULL,
                    submitted_at = NOW()
                WHERE user_id = %s AND task_id = %s
            ''', (user_id, task_id))
            db.conn.commit()

        await callback.message.answer("🔄 Отправьте исправленное решение:")
        await state.set_state(TaskStates.waiting_for_solution)
        await state.update_data(task_id=task_id)
        await callback.answer()

    except Exception as e:
        logger.error(f"Retry submission error: {str(e)}")
        await callback.answer("❌ Ошибка повторной отправки")

### 3. Единый обработчик отправки решений ###
# Добавить после инициализации бота:
async def notify_admin(submission_id: int):
    try:
        with db.cursor() as cursor:
            # Исправленный запрос:
            cursor.execute('''
                SELECT s.file_id, s.file_type, s.content,
                       t.title, u.full_name, t.content as task_text
                FROM submissions s
                JOIN tasks t ON s.task_id = t.task_id
                JOIN users u ON s.user_id = u.user_id
                WHERE s.submission_id = %s
            ''', (submission_id,))
            
            data = cursor.fetchone()
            if not data:
                return

            # Формирование сообщения с текстом задания
            text = (f"📬 Новое решение #{submission_id}\n"
                    f"📚 Задание: {data[3]}\n"
                    f"👤 Студент: {data[4]}\n"
                    f"📝 Текст задания:\n{data[5]}\n\n"
                    f"✏️ Решение:\n{data[2] or 'Файл во вложении'}")

            # Отправка файла
            if data[0] and data[1]:
                ...

            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Принять", callback_data=f"accept_{submission_id}")
            kb.button(text="❌ Требует правок", callback_data=f"reject_{submission_id}")
            kb.button(text="📨 Написать студенту", url=f"tg://user?id={student_id}")
            kb.adjust(2, 1)

            if file_id and file_type:
                if file_type == 'photo':
                    await bot.send_photo(
                        ADMIN_ID,
                        file_id,
                        caption=text[:1024],
                        reply_markup=kb.as_markup()
                    )
                else:
                    await bot.send_document(
                        ADMIN_ID,
                        file_id,
                        caption=text[:1024],
                        reply_markup=kb.as_markup()
                    )
            else:
                await bot.send_message(
                    ADMIN_ID,
                    text,
                    reply_markup=kb.as_markup()
                )
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {str(e)}")
        
@dp.message(TaskStates.waiting_for_solution, F.text.in_(["❌ Отмена", "🔙 Назад"]))
async def cancel_solution(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Отправка решения отменена",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer(
        "Главное меню:",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data.startswith("accept_") | F.data.startswith("reject_"))
async def handle_review(callback: CallbackQuery):
    try:
        action = callback.data.split("_")[0]
        submission_id = int(callback.data.split("_")[1])
        new_status = "accepted" if action == "accept" else "rejected"

        with db.cursor() as cursor:
            # Обновляем статус и получаем информацию о задании
            cursor.execute('''
                UPDATE submissions 
                SET status = %s 
                WHERE submission_id = %s
                RETURNING user_id, task_id
            ''', (new_status, submission_id))
            
            result = cursor.fetchone()
            if not result:
                await callback.answer("❌ Решение не найдено")
                return
                
            user_id, task_id = result

            cursor.execute('SELECT title FROM tasks WHERE task_id = %s', (task_id,))
            task_title = cursor.fetchone()[0]

        # Уведомление студента
        await bot.send_message(
            user_id,
            f"📢 Ваше решение по заданию «{task_title}» {new_status}"
        )

        # Удаление сообщения администратора
        await callback.message.delete()
        await callback.answer(f"✅ Статус обновлен: {new_status}")

    except (ValueError, IndexError) as e:
        logger.error(f"Ошибка формата данных: {str(e)}")
        await callback.answer("❌ Некорректный запрос", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка обработки: {str(e)}")
        await callback.answer("⚠️ Произошла ошибка", show_alert=True)

        await send_user_notification(
            user_id, 
            f"📢 Ваше решение по заданию «{task_title}» {new_status}"
        )

    except Exception as e:
        logger.error(f"Ошибка обработки: {str(e)}")
        await callback.answer("⚠️ Произошла ошибка", show_alert=True)
def main_menu() -> types.ReplyKeyboardMarkup:
    """Клавиатура главного меню для пользователей"""
    builder = ReplyKeyboardBuilder()
    buttons = [
        ("📚 Выбрать курс", None),
        ("🆘 Поддержка", None)
    ]
    
    for text, _ in buttons:
        builder.button(text=text)
    
    builder.adjust(2)
    return builder.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False
    )

def admin_menu() -> types.ReplyKeyboardMarkup:
    """Клавиатура админ-панели"""
    builder = ReplyKeyboardBuilder()
    buttons = [
        "📊 Статистика",
        "📝 Добавить курс",
        "🔄 Непроверенные задания",
        "🗑 Удалить курс",
        "➕ Добавить модуль",
        "📌 Добавить задание",
        "🎓 Добавить итоговое задание",
        "✏️ Управление контентом", 
        "👥 Пользователи",
        "🔙 Назад"
    ]
    
    for text in buttons:
        builder.button(text=text)
    
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False
    )

# 3. Обработчик кнопки "Назад" в админ-меню
@dp.message(F.text == "Назад")
async def back_handler(message: types.Message):
    await message.delete()
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    await state.clear()
    await message.answer("Админ-меню:", reply_markup=admin_menu())
    
    builder = ReplyKeyboardBuilder()
    for text, _ in commands:
        builder.button(text=text)
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)

@dp.message(Command("admin"))
async def admin_command(message: types.Message):
    if str(message.from_user.id) != ADMIN_ID:
        await message.answer("⛔ Доступ запрещен!")
        return
    
    try:
        await message.answer("🛠 Панель администратора:", reply_markup=admin_menu())
    except OperationalError as e:
        logger.error(f"Database error: {e}")
        await message.answer("❌ Ошибка подключения к базе данных")

@dp.message(F.text == "🔄 Непроверенные задания")
async def show_pending_tasks(message: Message):
    try:
        with db.cursor() as cursor:
            cursor.execute('''
                SELECT 
                    s.submission_id,
                    t.title AS task_title,
                    u.full_name,
                    s.submitted_at
                FROM submissions s
                JOIN tasks t ON s.task_id = t.task_id
                JOIN users u ON s.user_id = u.user_id
                WHERE s.status = 'pending'
                ORDER BY s.submitted_at DESC
            ''')
            pending_tasks = cursor.fetchall()

        if not pending_tasks:
            await message.answer("🎉 Нет заданий на проверке!")
            return

        builder = InlineKeyboardBuilder()
        for task in pending_tasks:
            submission_id, title, student, date = task
            builder.button(
                text=f"📝 {title} ({student})",
                callback_data=f"view_sub_{submission_id}"
            )
        
        builder.adjust(1)
        await message.answer(
            "📥 Задания на проверке:",
            reply_markup=builder.as_markup()
        )

    except Exception as e:
        logger.error("Ошибка показа заданий: %s", e)
        await message.answer("❌ Ошибка загрузки заданий")
        

@dp.callback_query(F.data.startswith("view_sub_"))
async def view_submission(callback: CallbackQuery):
    try:
        submission_id = int(callback.data.split("_")[2])
        
        with db.cursor() as cursor:
            cursor.execute('''
                SELECT s.content, s.file_id, s.file_type,
                       t.title, u.full_name, t.content
                FROM submissions s
                JOIN tasks t ON s.task_id = t.task_id
                JOIN users u ON s.user_id = u.user_id
                WHERE s.submission_id = %s
            ''', (submission_id,))
            data = cursor.fetchone()

        if not data:
            await callback.answer("❌ Задание не найдено")
            return

        content, file_id, file_type, title, student, task_text = data
        text = (f"📚 Задание: {title}\n"
                f"👤 Студент: {student}\n"
                f"📝 Текст задания:\n{task_text}\n\n"
                f"✏️ Решение:\n{content or 'Приложен файл'}")

        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Принять", callback_data=f"accept_{submission_id}")
        kb.button(text="❌ Отклонить", callback_data=f"reject_{submission_id}")
        
        if file_id and file_type:
            if file_type == 'photo':
                await callback.message.answer_photo(
                    file_id,
                    caption=text,
                    reply_markup=kb.as_markup()
                )
            else:
                await callback.message.answer_document(
                    file_id,
                    caption=text,
                    reply_markup=kb.as_markup()
                )
        else:
            await callback.message.answer(
                text,
                reply_markup=kb.as_markup()
            )
            
        await callback.answer()
        
    except Exception as e:
        logger.error("Ошибка просмотра задания: %s", e)
        await callback.answer("❌ Ошибка загрузки")
        
@dp.callback_query(F.data.startswith("accept_"))
async def accept_submission(callback: CallbackQuery):
    submission_id = int(callback.data.split("_")[1])
    
    with db.cursor() as cursor:
        cursor.execute('''
            UPDATE submissions 
            SET status = 'accepted', 
                score = 100 
            WHERE submission_id = %s
            RETURNING user_id, task_id
        ''', (submission_id,))
        user_id, task_id = cursor.fetchone()
        
        cursor.execute('SELECT title FROM tasks WHERE task_id = %s', (task_id,))
        task_title = cursor.fetchone()[0]

    await bot.send_message(
        user_id,
        f"✅ Ваше решение по заданию «{task_title}» принято!"
    )
    await callback.message.edit_reply_markup()
    await callback.answer("Решение принято!")

@dp.callback_query(F.data.startswith("reject_"))
async def reject_submission(callback: CallbackQuery):
    submission_id = int(callback.data.split("_")[1])
    
    with db.cursor() as cursor:
        cursor.execute('''
            UPDATE submissions 
            SET status = 'rejected'
            WHERE submission_id = %s
            RETURNING user_id, task_id
        ''', (submission_id,))
        user_id, task_id = cursor.fetchone()
        
        cursor.execute('SELECT title FROM tasks WHERE task_id = %s', (task_id,))
        task_title = cursor.fetchone()[0]

    await bot.send_message(
        user_id,
        f"❌ Ваше решение по заданию «{task_title}» требует доработок."
    )
    await callback.message.edit_reply_markup()
    await callback.answer("Решение отклонено")
    
@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    try:
        with db.cursor() as cursor:
            cursor.execute('''
                SELECT 
                    c.title,
                    COUNT(DISTINCT m.module_id) as modules,
                    COUNT(DISTINCT t.task_id) as tasks,
                    COUNT(s.submission_id) as submissions
                FROM courses c
                LEFT JOIN modules m ON c.course_id = m.course_id
                LEFT JOIN tasks t ON m.module_id = t.module_id
                LEFT JOIN submissions s ON t.task_id = s.task_id
                GROUP BY c.course_id
            ''')
            stats = cursor.fetchall()
        
        response = "📈 Статистика по курсам:\n\n"
        for stat in stats:
            response += (
                f"📚 {stat[0]}\n"
                f"Модулей: {stat[1]}\n"
                f"Заданий: {stat[2]}\n"
                f"Решений: {stat[3]}\n\n"
            )
        
        await message.answer(response)
    
    except Exception as e:
        logger.error(f"Ошибка статистики: {e}")
        await message.answer("❌ Ошибка получения статистики")

@dp.message(F.text == "👥 Пользователи")
async def list_users(message: types.Message):
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    try:
        with db.cursor() as cursor:
            cursor.execute('''
                SELECT 
                    u.user_id,
                    u.full_name,
                    c.title,
                    COUNT(s.submission_id) as submissions
                FROM users u
                LEFT JOIN courses c ON u.current_course = c.course_id
                LEFT JOIN submissions s ON u.user_id = s.user_id
                GROUP BY u.user_id, c.title
            ''')
            users = cursor.fetchall()
        
        response = "👥 Список пользователей:\n\n"
        for user in users:
            response += (
                f"👤 {user[1]} (ID: {user[0]})\n"
                f"Курс: {user[2] or 'не выбран'}\n"
                f"Решений: {user[3]}\n\n"
            )
        
        await message.answer(response)
    
    except Exception as e:
        logger.error(f"Ошибка списка пользователей: {e}")
        await message.answer("❌ Ошибка получения списка пользователей")

### BLOCK 5: COURSE MANAGEMENT ###

def courses_kb_admin():
    with db.cursor() as cursor:
        cursor.execute("SELECT course_id, title FROM courses")
        courses = cursor.fetchall()
    
    builder = InlineKeyboardBuilder()
    for course in courses:
        builder.button(text=course[1], callback_data=f"admin_course_{course[0]}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

@dp.message(F.text == "🗑 Удалить курс")
async def delete_course_start(message: Message):
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    await message.answer("Выберите курс для удаления:", reply_markup=courses_kb_admin())

@dp.callback_query(F.data.startswith("admin_course_"))
async def confirm_course_delete(callback: CallbackQuery):
    course_id = int(callback.data.split("_")[2])
    
    with db.cursor() as cursor:
        cursor.execute("SELECT title FROM courses WHERE course_id = %s", (course_id,))
        title = cursor.fetchone()[0]
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"confirm_delete_{course_id}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    
    await callback.message.edit_text(
        f"🚨 Вы уверены, что хотите удалить курс?\n{title}",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("confirm_delete_"))
async def execute_course_delete(callback: CallbackQuery):
    course_id = int(callback.data.split("_")[2])
    
    try:
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM courses WHERE course_id = %s", (course_id,))
            await callback.answer("✅ Курс успешно удален!")
    except Exception as e:
        logger.error(f"Ошибка удаления курса: {e}")
        await callback.answer("❌ Ошибка удаления курса")
    
    await callback.message.edit_text("Курс удален", reply_markup=None)

### BLOCK 6: CONTENT CREATION ###

@dp.callback_query(F.data.startswith("course_"))
async def select_course_handler(callback: types.CallbackQuery):
    try:
        course_id = int(callback.data.split('_')[1])
        
        with db.cursor() as cursor:
            # Обновляем курс пользователя
            cursor.execute("""
                UPDATE users 
                SET current_course = %s 
                WHERE user_id = %s
            """, (course_id, callback.from_user.id))
            
            # Получаем информацию о курсе
            cursor.execute("""
                SELECT title, media_id 
                FROM courses 
                WHERE course_id = %s
            """, (course_id,))
            course_data = cursor.fetchone()

            if not course_data:
                await callback.answer("❌ Курс не найден")
                return

            title, media_id = course_data
            keyboard = modules_kb(course_id)  # Используем нашу функцию
            
            if media_id:
                await callback.message.delete()
                await callback.message.answer_photo(
                    media_id,
                    caption=f"📚 Курс: {title}\nВыберите модуль:",
                    reply_markup=keyboard
                )
            else:
                await callback.message.edit_text(
                    text=f"📚 Курс: {title}\nВыберите модуль:",
                    reply_markup=keyboard
                )

    except Exception as e:
        logger.error(f"Ошибка выбора курса: {e}")
        await callback.answer("❌ Ошибка загрузки курса")

@dp.message(F.text == "📝 Добавить курс")
async def add_course_start(message: Message, state: FSMContext):
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    await message.answer("Введите название курса:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminForm.add_course_title)

@dp.message(AdminForm.add_course_title)
async def process_course_title(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer("Действие отменено", reply_markup=admin_menu())
        return
    
    await state.update_data(title=message.text)
    await message.answer("Введите описание курса:")
    await state.set_state(AdminForm.add_course_description)

@dp.message(AdminForm.add_course_description)
async def process_course_desc(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer("Действие отменено", reply_markup=admin_menu())
        return
    
    await state.update_data(description=message.text)
    await message.answer("Отправьте обложку курса (фото/документ) или /skip")
    await state.set_state(AdminForm.add_course_media)

@dp.message(AdminForm.add_course_media, F.content_type.in_({'photo', 'document'}))
async def process_course_media(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer("Действие отменено", reply_markup=admin_menu())
        return
    media_id = await handle_media(message, state)
    data = await state.get_data()
    
    try:
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO courses (title, description, media_id) VALUES (%s, %s, %s)",
                (data['title'], data['description'], media_id)
            )
        await message.answer("✅ Курс успешно создан!", reply_markup=admin_menu())
    except IntegrityError:
        await message.answer("❌ Курс с таким названием уже существует!")
    
    await state.clear()

@dp.message(AdminForm.add_course_media, Command('skip'))
async def process_course_media(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer("Действие отменено", reply_markup=admin_menu())
        return
    
    if message.text == "/skip":
        data = await state.get_data()
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO courses (title, description) VALUES (%s, %s)",
                    (data['title'], data['description'])
                )
            await message.answer("✅ Курс создан без медиа!", reply_markup=admin_menu())
        except IntegrityError:
            await message.answer("❌ Курс с таким названием уже существует!", reply_markup=admin_menu())
        await state.clear()
        return

    media = await handle_media(message)
    if media:
        data = await state.get_data()
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO courses (title, description, media_id) VALUES (%s, %s, %s)",
                    (data['title'], data['description'], media['file_id'])
                )
            await message.answer("✅ Курс успешно создан!", reply_markup=admin_menu())
        except IntegrityError:
            await message.answer("❌ Курс с таким названием уже существует!", reply_markup=admin_menu())
        await state.clear()
    else:
        await message.answer("❌ Отправьте фото или документ для обложки курса")

### BLOCK 7: MODULE AND TASK CREATION ###

def courses_for_modules():
    with db.cursor() as cursor:
        cursor.execute("SELECT course_id, title FROM courses")
        return cursor.fetchall()

@dp.message(F.text == "➕ Добавить модуль")
async def add_module_start(message: Message, state: FSMContext):
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    builder = InlineKeyboardBuilder()
    for course in courses_for_modules():
        builder.button(text=course[1], callback_data=f"add_module_{course[0]}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    
    await message.answer("Выберите курс для модуля:", reply_markup=builder.as_markup())

@dp.message(Command("cancel"))
@dp.message(F.text.lower() == "отмена")
async def cancel_action(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    
    await state.clear()
    await message.answer(
        "Действие отменено",
        reply_markup=admin_menu() if str(message.from_user.id) == ADMIN_ID else main_menu()
    )
    
@dp.callback_query(F.data.startswith("add_module_"))
async def select_course_for_module(callback: CallbackQuery, state: FSMContext):
    course_id = int(callback.data.split("_")[2])
    await state.update_data(course_id=course_id)
    await callback.message.answer("Введите название модуля:")
    await state.set_state(AdminForm.add_module_title)

# Обработчик кнопки "Отмена"
@dp.message(F.text.in_(["❌ Отмена", "🔙 Назад"]))
async def global_cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer("Действие отменено", reply_markup=main_menu())
    
    # Удаляем предыдущие сообщения с клавиатурами
    await message.answer(
        "Действие отменено",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Возвращаем в главное меню
    await message.answer(
        "Главное меню:",
        reply_markup=main_menu()
    )

# Обработчик кнопки "Назад"
@dp.message(F.text.lower() == "🔙 назад")
async def back_handler(message: Message):
    await message.answer(
        "Возврат в предыдущее меню",
        reply_markup=ReplyKeyboardRemove()
    )
    # Добавьте логику возврата

# Фильтр для игнорирования кнопок в других обработчиках
class NotButtonFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.text not in ["❌ Отмена", "🔙 Назад"]
        
@dp.message(AdminForm.add_module_title)
async def process_module_title(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer("Действие отменено", reply_markup=admin_menu())
        return
    
    await state.update_data(title=message.text)
    await message.answer("Отправьте медиа для модуля или /skip")
    await state.set_state(AdminForm.add_module_media)


@dp.message(AdminForm.add_module_media)
async def process_module_media(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer("Действие отменено", reply_markup=admin_menu())
        return
    
    data = await state.get_data()
    if message.text == "/skip":
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO modules (course_id, title) VALUES (%s, %s)",
                    (data['course_id'], data['title'])
                )
            await message.answer("✅ Модуль создан!", reply_markup=admin_menu())
        except Exception as e:
            logger.error(f"Ошибка создания модуля: {e}")
            await message.answer("❌ Ошибка создания модуля")
        await state.clear()
        return

    media = await handle_media(message)
    if media:
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO modules (course_id, title, media_id) VALUES (%s, %s, %s)",
                    (data['course_id'], data['title'], media['file_id'])
                )
            await message.answer("✅ Модуль создан с медиа!", reply_markup=admin_menu())
        except Exception as e:
            logger.error(f"Ошибка создания модуля: {e}")
            await message.answer("❌ Ошибка создания модуля")
        await state.clear()
    else:
        await message.answer("❌ Отправьте фото или документ для модуля")

@dp.message(AdminForm.add_module_media, Command('skip'))
async def skip_module_media(message: Message, state: FSMContext):
    data = await state.get_data()
    
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO modules (course_id, title) VALUES (%s, %s)",
            (data['course_id'], data['title'])
        )
    
    await message.answer("✅ Модуль создан без медиа!", reply_markup=admin_menu())
    await state.clear()

### BLOCK 8: TASK CREATION ###

@dp.message(F.text == "📌 Добавить задание")
async def add_task_start(message: Message):
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    builder = InlineKeyboardBuilder()
    for course in courses_for_modules():
        builder.button(text=course[1], callback_data=f"select_course_{course[0]}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    
    await message.answer("Выберите курс:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("select_course_"))
async def select_course_task(callback: CallbackQuery, state: FSMContext):
    course_id = int(callback.data.split("_")[2])
    
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT module_id, title FROM modules WHERE course_id = %s",
            (course_id,)
        )
        modules = cursor.fetchall()
    
    builder = InlineKeyboardBuilder()
    for module in modules:
        builder.button(text=module[1], callback_data=f"select_module_{module[0]}")
    builder.button(text="🔙 Назад", callback_data="cancel")
    
    await callback.message.edit_text("Выберите модуль:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("select_module_"))
async def select_module_task(callback: CallbackQuery, state: FSMContext):
    module_id = int(callback.data.split("_")[2])
    await state.update_data(module_id=module_id)
    await callback.message.answer("Введите название задания:")
    await state.set_state(AdminForm.add_task_title)

@dp.message(AdminForm.add_task_title)
async def process_task_title(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer("Действие отменено", reply_markup=admin_menu())
        return
    
    await state.update_data(title=message.text)
    await message.answer("Введите описание задания:")
    await state.set_state(AdminForm.add_task_content)

@dp.message(AdminForm.add_task_content)
async def process_task_content(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer("Действие отменено", reply_markup=admin_menu())
        return
    
    await state.update_data(content=message.text)
    await message.answer("Отправьте файл задания или /skip")
    await state.set_state(AdminForm.add_task_media)

@dp.message(F.text == "✏️ Управление контентом")
async def content_management(message: Message):
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Курсы", callback_data="edit_content_courses")
    builder.button(text="📦 Модули", callback_data="edit_content_modules")
    builder.button(text="📝 Задания", callback_data="edit_content_tasks")
    builder.button(text="🎓 Итоговые задания", callback_data="edit_content_final")
    builder.adjust(1)
    
    await message.answer("Выберите тип контента:", reply_markup=builder.as_markup())

# Общий обработчик выбора типа контента
@dp.callback_query(F.data.startswith("edit_content_"))
async def select_content_type(callback: CallbackQuery, state: FSMContext):
    content_type = callback.data.split("_")[2]
    await state.update_data(content_type=content_type)
    
    # Получаем список элементов
    with db.cursor() as cursor:
        if content_type == "courses":
            cursor.execute("SELECT course_id, title FROM courses")
        elif content_type == "modules":
            cursor.execute("SELECT module_id, title FROM modules")
        elif content_type == "tasks":
            cursor.execute("SELECT task_id, title FROM tasks")
        elif content_type == "final":
            cursor.execute("SELECT final_task_id, title FROM final_tasks")
        
        items = cursor.fetchall()

    builder = InlineKeyboardBuilder()
    for item_id, title in items:
        builder.button(
            text=title,
            callback_data=f"edit_select_{item_id}"
        )
    builder.button(text="🔙 Назад", callback_data="edit_content_menu")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "Выберите элемент для редактирования:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminForm.edit_select_item)

@dp.callback_query(F.data.startswith("edit_select_"))
async def select_item(callback: CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split("_")[2])
    await state.update_data(item_id=item_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Название", callback_data="edit_title")
    builder.button(text="📝 Описание", callback_data="edit_description")
    builder.button(text="🖼 Медиа", callback_data="edit_media")
    builder.button(text="🔙 Назад", callback_data="edit_content_type")
    builder.adjust(2, 1)
    
    await callback.message.edit_text(
        "Выберите что хотите изменить:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "edit_title")
async def start_edit_title(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите новое название:")
    await state.set_state(AdminForm.edit_title)

@dp.message(AdminForm.edit_title)
async def process_edit_title(message: Message, state: FSMContext):
    data = await state.get_data()
    content_type = data['content_type']
    item_id = data['item_id']
    
    try:
        with db.cursor() as cursor:
            if content_type == "courses":
                cursor.execute("UPDATE courses SET title = %s WHERE course_id = %s", 
                             (message.text, item_id))
            elif content_type == "modules":
                cursor.execute("UPDATE modules SET title = %s WHERE module_id = %s", 
                             (message.text, item_id))
            # Аналогично для других типов
            
        await message.answer("✅ Название успешно обновлено!")
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.callback_query(F.data == "edit_description")
async def start_edit_description(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите новое описание:")
    await state.set_state(AdminForm.edit_description)

@dp.message(AdminForm.edit_description)
async def process_edit_description(message: Message, state: FSMContext):
    data = await state.get_data()
    content_type = data['content_type']
    item_id = data['item_id']
    
    try:
        with db.cursor() as cursor:
            if content_type == "courses":
                cursor.execute("UPDATE courses SET description = %s WHERE course_id = %s", 
                             (message.text, item_id))
            # Аналогично для других типов
            
        await message.answer("✅ Описание успешно обновлено!")
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

# 6. Обработчик медиа
@dp.callback_query(F.data == "edit_media")
async def start_edit_media(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Отправьте новое медиа (фото/документ) или:\n"
        "/keep - оставить текущее\n"
        "/remove - удалить медиа"
    )
    await state.set_state(AdminForm.edit_media)

@dp.message(AdminForm.edit_media)
async def process_edit_media(message: Message, state: FSMContext):
    data = await state.get_data()
    content_type = data['content_type']
    item_id = data['item_id']
    
    media_id = None
    media_type = None
    
    if message.text == "/keep":
        # Оставляем текущее медиа без изменений
        await message.answer("🔄 Медиа остается без изменений")
        return
    elif message.text == "/remove":
        media_id = None
        media_type = None
    elif message.content_type in ['photo', 'document']:
        if message.photo:
            media_id = message.photo[-1].file_id
            media_type = 'photo'
        else:
            media_id = message.document.file_id
            media_type = 'document'
    else:
        await message.answer("❌ Неподдерживаемый тип медиа")
        return
    
    try:
        with db.cursor() as cursor:
            if content_type == "courses":
                cursor.execute(
                    "UPDATE courses SET media_id = %s WHERE course_id = %s",
                    (media_id, item_id)
                )
            # Аналогично для других типов
            
        await message.answer("✅ Медиа успешно обновлено!")
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

# 7. Обработчик возвратов
@dp.callback_query(F.data == "edit_content_menu")
async def back_to_edit_menu(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Курсы", callback_data="edit_content_courses")
    builder.button(text="📦 Модули", callback_data="edit_content_modules")
    builder.button(text="📝 Задания", callback_data="edit_content_tasks")
    builder.button(text="🎓 Итоговые", callback_data="edit_content_final")
    builder.button(text="🔙 В админ-меню", callback_data="admin_menu")
    builder.adjust(2, 2)
    
    await callback.message.edit_text(
        "Выберите тип контента:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "edit_content_type")
async def back_to_content_type(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await select_content_type(callback, state)

@dp.callback_query(F.data.startswith("select_"))
async def select_item(callback: CallbackQuery, state: FSMContext):
    data = callback.data.split("_")
    content_type = data[1]
    item_id = data[2]
    
    await state.update_data(
        content_type=content_type,
        item_id=item_id
    )
    
    # Клавиатура действий
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Редактировать", callback_data="edit_action")
    builder.button(text="🗑️ Удалить", callback_data="delete_action")
    builder.button(text="🔙 Назад", callback_data=f"edit_content_{content_type}")  # Возврат к списку
    
    await callback.message.edit_text(
        f"Выберите действие для элемента:",
        reply_markup=builder.as_markup()
    )

# Обработчик выбора действия
@dp.callback_query(F.data.in_(["edit_action", "delete_action"]))
async def handle_content_action(callback: CallbackQuery, state: FSMContext):
    action = callback.data
    data = await state.get_data()
    content_type = data['content_type']
    
    try:
        if action == "edit_action":
            states = {
                "courses": AdminForm.edit_course,
                "modules": AdminForm.edit_module,
                "tasks": AdminForm.edit_task,
                "final": AdminForm.edit_final_task
            }
            await state.set_state(states[content_type])
            await callback.message.answer(
                "Введите новые данные (формат: Название|Описание|file_id)\n"
                "Пример: Новое название|Новое описание|AgAC..."
            )
        
        elif action == "delete_action":
            await state.set_state(AdminForm.delete_confirmation)
            await callback.message.edit_text(
                "❌ Вы уверены что хотите удалить?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Да", callback_data="confirm_delete"),
                        InlineKeyboardButton(text="❌ Нет", callback_data="cancel_delete")
                    ]
                ])
            )
    
    except Exception as e:
        logger.error(f"Error in handle_content_action: {e}")
        await callback.answer("❌ Произошла ошибка")

# Обработчик редактирования курса
@dp.message(AdminForm.edit_course)
async def process_edit_course(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        if '|' not in message.text:
            raise ValueError("Некорректный формат данных")
            
        parts = message.text.split('|', 2)
        title = parts[0].strip()
        description = parts[1].strip() if len(parts) > 1 else ""
        file_id = parts[2].strip() if len(parts) > 2 else None
        
        with db.cursor() as cursor:
            cursor.execute('''
                UPDATE courses 
                SET title = %s, 
                    description = COALESCE(%s, description), 
                    media_id = COALESCE(%s, media_id) 
                WHERE course_id = %s
            ''', (title, description, file_id, data['item_id']))
            
        await message.answer("✅ Курс успешно обновлен!")
        await show_content_management(message)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}\nПопробуйте снова:")
    finally:
        await state.clear()
        

# Обработчик подтверждения удаления
@dp.callback_query(F.data == "confirm_delete")
async def confirm_delete(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    try:
        with db.cursor() as cursor:
            content_type = data['content_type']
            item_id = data['item_id']
            
            tables = {
                "courses": ("courses", "course_id"),
                "modules": ("modules", "module_id"),
                "tasks": ("tasks", "task_id"),
                "final": ("final_tasks", "final_task_id")
            }
            
            table, column = tables[content_type]
            cursor.execute(f"DELETE FROM {table} WHERE {column} = %s", (item_id,))
            
            await callback.message.edit_text(f"✅ {content_type[:-1].capitalize()} успешно удален!")
            
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка удаления: {str(e)}")
    finally:
        await state.clear()
        
@dp.callback_query(F.data == "edit_content_menu")
async def edit_content_menu(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Курсы", callback_data="edit_content_courses")
    builder.button(text="📦 Модули", callback_data="edit_content_modules")
    builder.button(text="📝 Задания", callback_data="edit_content_tasks")
    builder.button(text="🎓 Итоговые", callback_data="edit_content_final")
    builder.button(text="🔙 В админ-меню", callback_data="admin_menu")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "Выберите тип контента для редактирования:",
        reply_markup=builder.as_markup()
    )
    
@dp.message(AdminForm.add_task_media, F.content_type.in_({'document', 'photo'}))
async def process_task_media(message: Message, state: FSMContext):
    media = await handle_media(message)
    data = await state.get_data()
    
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tasks (module_id, title, content, file_type, file_id) VALUES (%s, %s, %s, %s, %s)",
            (data['module_id'], data['title'], data['content'], media['type'], media['file_id'])
        )
    
    await message.answer("✅ Задание создано!", reply_markup=admin_menu())
    await state.clear()

@dp.message(F.text == "🎓 Добавить итоговое задание")
async def add_final_task_start(message: Message):
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    builder = InlineKeyboardBuilder()
    for course in courses_for_modules():
        builder.button(text=course[1], callback_data=f"add_final_{course[0]}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    
    await message.answer("Выберите курс:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("add_final_"))
async def process_final_task_course(callback: CallbackQuery, state: FSMContext):
    course_id = int(callback.data.split("_")[2])
    await state.update_data(course_id=course_id)
    await callback.message.answer("Введите название итогового задания:")
    await state.set_state(AdminForm.add_final_task_title)

@dp.message(AdminForm.add_final_task_title)
async def process_final_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Введите описание задания:")
    await state.set_state(AdminForm.add_final_task_content)

@dp.message(AdminForm.add_final_task_content)
async def process_final_content(message: Message, state: FSMContext):
    await state.update_data(content=message.text)
    await message.answer("Отправьте файл задания или /skip")
    await state.set_state(AdminForm.add_final_task_media)

# Обработка медиа для итогового задания
@dp.message(AdminForm.add_final_task_media)
async def process_final_media(message: Message, state: FSMContext):
    data = await state.get_data()
    media = await handle_media(message)
    
    try:
        with db.cursor() as cursor:
            cursor.execute('''
                INSERT INTO final_tasks 
                (course_id, title, content, file_id, file_type)
                VALUES (%s, %s, %s, %s, %s)
            ''', (
                data['course_id'],
                data['title'],
                data['content'],
                media['file_id'] if media else None,
                media['type'] if media else None
            ))
        await message.answer("✅ Итоговое задание добавлено!", reply_markup=admin_menu())
    except Exception as e:
        logger.error(f"Ошибка добавления итогового задания: {e}")
        await message.answer("❌ Ошибка добавления задания")
    
    await state.clear()

# Генерация PDF сертификата
def generate_certificate(name: str, course: str) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    style = ParagraphStyle(
        name='Center',
        parent=styles['Normal'],
        alignment=1,
        fontSize=20,
        leading=24
    )
    
    content = []
    content.append(Paragraph("СЕРТИФИКАТ", style))
    content.append(Paragraph(f"Выдан: {name}", style))
    content.append(Paragraph(f"За успешное прохождение курса: {course}", style))
    
    doc.build(content)
    buffer.seek(0)
    return buffer

# Обработчик для итогового задания у пользователя
@dp.callback_query(F.data.startswith("final_task_"))
async def handle_final_task(callback: CallbackQuery, state: FSMContext):
    course_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    # Проверка выполнения всех заданий
    with db.cursor() as cursor:
        cursor.execute('''
            SELECT COUNT(t.task_id) = COUNT(s.task_id)
            FROM tasks t
            LEFT JOIN modules m ON t.module_id = m.module_id
            LEFT JOIN submissions s ON t.task_id = s.task_id 
                AND s.user_id = %s 
                AND s.status = 'accepted'
            WHERE m.course_id = %s
        ''', (user_id, course_id))
        all_completed = cursor.fetchone()[0]
        
        if not all_completed:
            await callback.answer("❌ Сначала завершите все задания курса!", show_alert=True)
            return
        
        cursor.execute('''
            SELECT title, content, file_id, file_type 
            FROM final_tasks 
            WHERE course_id = %s
        ''', (course_id,))
        final_task = cursor.fetchone()
        
    if not final_task:
        await callback.answer("❌ Итоговое задание не найдено", show_alert=True)
        return
        
    title, content, file_id, file_type = final_task
    
    # Отправка задания пользователю
    if file_id and file_type:
        if file_type == 'photo':
            await callback.message.answer_photo(
                file_id,
                caption=f"🎓 Итоговое задание: {title}\n\n{content}"
            )
        else:
            await callback.message.answer_document(
                file_id,
                caption=f"🎓 Итоговое задание: {title}\n\n{content}"
            )
    else:
        await callback.message.answer(
            f"🎓 Итоговое задание: {title}\n\n{content}"
        )
    
    await callback.message.answer("Отправьте ваше решение:")
    await state.set_state(TaskStates.waiting_for_final_solution)
    await state.update_data(course_id=course_id)

# Обработка решения итогового задания
@dp.message(TaskStates.waiting_for_final_solution)
async def process_final_solution(message: Message, state: FSMContext):
    data = await state.get_data()
    course_id = data['course_id']
    user_id = message.from_user.id
    
    # Сохранение решения
    file_type = None
    file_id = None
    content = None
    
    if message.document:
        file_type = 'document'
        file_id = message.document.file_id
    elif message.photo:
        file_type = 'photo'
        file_id = message.photo[-1].file_id
    else:
        content = message.text
    
    # Отправка админу
    with db.cursor() as cursor:
        cursor.execute('''
            INSERT INTO final_submissions 
            (user_id, course_id, content, file_id, file_type)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING final_submission_id
        ''', (user_id, course_id, content, file_id, file_type))
        submission_id = cursor.fetchone()[0]
    
    # Уведомление админа
    await notify_admin_final(submission_id)
    await message.answer("✅ Решение отправлено на проверку!")
    await state.clear()

async def notify_admin_final(submission_id: int):
    with db.cursor() as cursor:
        cursor.execute('''
            SELECT fs.content, fs.file_id, fs.file_type,
                   u.full_name, c.title
            FROM final_submissions fs
            JOIN users u ON fs.user_id = u.user_id
            JOIN courses c ON fs.course_id = c.course_id
            WHERE fs.final_submission_id = %s
        ''', (submission_id,))
        data = cursor.fetchone()
        
    text = (f"🎓 Итоговое задание #{submission_id}\n"
            f"👤 Студент: {data[3]}\n"
            f"📚 Курс: {data[4]}\n"
            f"📝 Решение: {data[0] or 'Приложен файл'}")
    
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Выдать сертификат", callback_data=f"cert_yes_{submission_id}")
    kb.button(text="❌ Отклонить", callback_data=f"cert_no_{submission_id}")
    
    if data[2] and data[1]:
        if data[2] == 'photo':
            await bot.send_photo(
                ADMIN_ID,
                data[1],
                caption=text,
                reply_markup=kb.as_markup()
            )
        else:
            await bot.send_document(
                ADMIN_ID,
                data[1],
                caption=text,
                reply_markup=kb.as_markup()
            )
    else:
        await bot.send_message(ADMIN_ID, text, reply_markup=kb.as_markup())

# Обработка решения админа
@dp.callback_query(F.data.startswith("cert_"))
async def handle_cert_decision(callback: CallbackQuery):
    action, submission_id = callback.data.split("_")[1], int(callback.data.split("_")[2])
    
    with db.cursor() as cursor:
        cursor.execute('''
            SELECT user_id, course_id 
            FROM final_submissions 
            WHERE final_submission_id = %s
        ''', (submission_id,))
        user_id, course_id = cursor.fetchone()
        
        cursor.execute('SELECT title FROM courses WHERE course_id = %s', (course_id,))
        course_title = cursor.fetchone()[0]
        
    if action == 'yes':
        # Генерация сертификата
        cert_buffer = generate_certificate(
            name=callback.from_user.full_name,
            course=course_title
        )
        cert_file = BufferedInputFile(cert_buffer.getvalue(), filename="certificate.pdf")
        
        # Отправка пользователю
        await bot.send_document(
            user_id,
            cert_file,
            caption=f"🎉 Поздравляем! Вы успешно прошли курс {course_title}!"
        )
        await callback.answer("✅ Сертификат отправлен!")
    else:
        await bot.send_message(
            user_id,
            f"❌ Ваше итоговое задание по курсу {course_title} требует доработок."
        )
        await callback.answer("❌ Решение отклонено")
    
    await callback.message.delete()

@dp.message(AdminForm.add_task_media, Command('skip'))
async def process_task_media(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer("Действие отменено", reply_markup=admin_menu())
        return
    
    data = await state.get_data()
    if message.text == "/skip":
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tasks (module_id, title, content) VALUES (%s, %s, %s)",
                    (data['module_id'], data['title'], data['content'])
                )
            await message.answer("✅ Задание создано!", reply_markup=admin_menu())
        except Exception as e:
            logger.error(f"Ошибка создания задания: {e}")
            await message.answer("❌ Ошибка создания задания")
        await state.clear()
        return

    media = await handle_media(message)
    if media:
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tasks (module_id, title, content, file_id, file_type) VALUES (%s, %s, %s, %s, %s)",
                    (data['module_id'], data['title'], data['content'], media['file_id'], media['type'])
                )
            await message.answer("✅ Задание создано с файлом!", reply_markup=admin_menu())
        except Exception as e:
            logger.error(f"Ошибка создания задания: {e}")
            await message.answer("❌ Ошибка создания задания")
        await state.clear()
    else:
        await message.answer("❌ Отправьте файл задания или /skip")
### BLOCK 9: UTILITY HANDLERS ###

@dp.callback_query(F.data == "cancel")
async def cancel_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Действие отменено")
    if str(callback.from_user.id) == ADMIN_ID:
        await callback.message.answer("Админ-меню:", reply_markup=admin_menu())
    else:
        await callback.message.answer("Главное меню:", reply_markup=main_menu())

@dp.callback_query(F.data.startswith("reject_"))
async def handle_reject(callback: types.CallbackQuery):
    try:
        # Полная реализация аналогично обработчику accept_
        data = callback.data.split('_')
        if len(data) != 3:
            raise ValueError(f"Invalid callback data: {callback.data}")
            
        _, submission_id_str, user_id_str = data
        
        submission_id = int(submission_id_str)
        student_id = int(user_id_str)
        
        with db.cursor() as cursor:
            cursor.execute('''
                UPDATE submissions 
                SET status = 'rejected'
                WHERE submission_id = %s
                RETURNING task_id
            ''', (submission_id,))
            
            result = cursor.fetchone()
            if not result:
                await callback.answer("❌ Решение не найдено")
                return
                
            task_id = result[0]

            cursor.execute('SELECT title FROM tasks WHERE task_id = %s', (task_id,))
            task_title = cursor.fetchone()[0]
            db.conn.commit()

        await bot.send_message(
            student_id,
            f"📢 Ваше решение по заданию «{task_title}» отклонено ❌"
        )
        await callback.message.delete()
        await callback.answer("✅ Статус обновлен!")

    except (ValueError, IndexError) as e:
        logger.error(f"Ошибка данных: {str(e)}")
        await callback.answer("❌ Ошибка формата данных", show_alert=True)
        
    except psycopg2.Error as e:
        logger.error(f"Ошибка БД: {str(e)}")
        await callback.answer("⚠️ Ошибка базы данных", show_alert=True)
        db.conn.rollback()
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}", exc_info=True)
        await callback.answer("⚠️ Системная ошибка", show_alert=True)

@dp.message(TaskStates.waiting_final_solution)
async def process_final_solution(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        data = await state.get_data()
        course_id = data.get('course_id')

        # Проверяем выполнение всех заданий
        if not db.is_course_completed(user_id, course_id):
            await message.answer("❌ Вы не завершили все задания курса!")
            await state.clear()
            return
            
        # Сохраняем решение
        file_id = None
        file_type = None
        content = message.text

        if message.document:
            file_id = message.document.file_id
            file_type = 'document'
        elif message.photo:
            file_id = message.photo[-1].file_id
            file_type = 'photo'

        with db.cursor() as cursor:
            cursor.execute('''
                INSERT INTO final_submissions 
                (user_id, course_id, content, file_id, file_type)
                VALUES (%s, %s, %s, %s, %s)
            ''', (user_id, course_id, content, file_id, file_type))

        # Уведомляем админа
        await notify_admin_final_submission(user_id, course_id)
        
        await message.answer("✅ Решение итогового задания отправлено на проверку!")
        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка обработки итогового задания: {e}")
        await message.answer("❌ Ошибка отправки решения")

@dp.message(F.text == "🔙 В главное меню")
async def back_to_main(message: Message):
    await message.answer("Главное меню:", reply_markup=main_menu())
    await message.delete()

async def on_startup():
    logger.info("✅ Бот запущен")
    await bot.send_message(ADMIN_ID, "Бот активен")

async def on_shutdown():
    logger.info("🛑 Бот остановлен")
    await bot.send_message(ADMIN_ID, "Бот выключен")
    db.close()
    await bot.session.close()

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

import os
import logging
import random
import psycopg2
from psycopg2 import OperationalError, IntegrityError
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from urllib.parse import urlparse
from contextlib import contextmanager
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from datetime import datetime
from aiogram.enums import ParseMode 
from aiogram.types import (
    Message, 
    CallbackQuery, 
    ReplyKeyboardRemove,
    InlineKeyboardMarkup  # Добавить эту строку
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

class Database:
    def __init__(self):
        self.conn = None
        self._connect()
        self._init_tables()
        
    def _connect(self):
        """Установка соединения с PostgreSQL"""
        self.conn = psycopg2.connect(
            dbname=parsed_db.path[1:],
            user=parsed_db.username,
            password=parsed_db.password,
            host=parsed_db.hostname,
            port=parsed_db.port,
            sslmode='require'
        )
        self.conn.autocommit = False

    def _init_tables(self):
        """Инициализация таблиц в PostgreSQL"""
        with self.conn.cursor() as cursor:
            try:
                # Создание основных таблиц
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
                    CREATE TABLE IF NOT EXISTS submissions (
                        submission_id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                        task_id INTEGER NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                        status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected')),
                        score INTEGER CHECK(score BETWEEN 0 AND 100),
                        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        file_id TEXT,
                        content TEXT
                    )''')

                # Добавляем новые колонки при необходимости
                cursor.execute('''
                    ALTER TABLE tasks 
                    ADD COLUMN IF NOT EXISTS file_type VARCHAR(10)
                ''')

                self.conn.commit()
                
            except Exception as e:
                self.conn.rollback()
                logger.error(f"Ошибка инициализации таблиц: {e}")
                raise

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

# Инициализация объектов
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)
db = Database()

class Form(StatesGroup):
    full_name = State()
    course_selection = State()
    waiting_for_solution = State()

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
    
def task_keyboard(task_id: int) -> types.ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=f"✏️ Отправить решение {task_id}")
    builder.button(text=f"🔄 Отправить исправление {task_id}")
    builder.button(text=f"🔙 Назад к модулю {task_id}")
    builder.adjust(1)
    return builder.as_markup(
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите действие"
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
async def handle_submit_solution(callback: CallbackQuery, state: FSMContext):
    try:
        task_id = int(callback.data.split("_")[1])
        await callback.message.answer("📤 Отправьте ваше решение (текст или файл):")
        await state.set_state(TaskStates.waiting_for_solution)
        await state.update_data(task_id=task_id)
        await callback.answer()
    except Exception as e:
        logger.error(f"Submit error: {str(e)}")
        await callback.answer("❌ Ошибка отправки решения")
        
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

def courses_kb():
    with db.cursor() as cursor:
        cursor.execute("SELECT course_id, title FROM courses")
        courses = cursor.fetchall()
    
    builder = InlineKeyboardBuilder()
    for course in courses:
        builder.button(
            text=f"📘 {course[1]}", 
            callback_data=f"course_{course[0]}"
        )
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

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

# Обработчик выбора курса
@dp.callback_query(F.data.startswith("course_"))
async def select_course(callback: types.CallbackQuery):
    try:
        course_id = int(callback.data.split("_")[1])
        user_id = callback.from_user.id
        
        with db.cursor() as cursor:
            # Обновляем текущий курс пользователя
            cursor.execute(
                "UPDATE users SET current_course = %s WHERE user_id = %s",  # Исправлено здесь
                (course_id, user_id)  # Добавлена закрывающая скобка
            )
            
            # Получаем данные курса
            cursor.execute(
                "SELECT title, media_id FROM courses WHERE course_id = %s",
                (course_id,)
            )
            course = cursor.fetchone()
        
        text = f"✅ Вы выбрали курс: {course[0]}\nВыберите модуль:"
        kb = modules_kb(course_id)
        
        if course[1]:
            await callback.message.delete()
            await callback.message.answer_photo(
                course[1], 
                caption=text, 
                reply_markup=kb
            )
        else:
            await callback.message.edit_text(text, reply_markup=kb)
            
    except Exception as e:
        logger.error(f"Ошибка выбора курса: {e}")
        await callback.answer("❌ Ошибка при выборе курса")
        
# Клавиатура модулей курса
def modules_kb(course_id: int) -> types.InlineKeyboardMarkup:
    try:
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT module_id, title FROM modules WHERE course_id = %s",
                (course_id,))
            modules = cursor.fetchall()
        
        builder = InlineKeyboardBuilder()
        
        if modules:
            for module_id, title in modules:
                builder.button(
                    text=f"📂 {title}",
                    callback_data=f"module_{module_id}"
                )
        else:
            builder.button(
                text="❌ Нет доступных модулей", 
                callback_data="no_modules"
            )
            
        builder.button(
            text="🔙 Назад к курсам", 
            callback_data="all_courses"
        )
        builder.adjust(1)
        
        return builder.as_markup()
        
    except Exception as e:
        logger.error(f"Ошибка формирования клавиатуры: {e}")
        return InlineKeyboardBuilder().as_markup()

# Обработчик выбора задания
@dp.callback_query(F.data.startswith("task_"))
async def task_selected_handler(callback: types.CallbackQuery):
    try:
        task_id = int(callback.data.split("_")[1])
        user_id = callback.from_user.id
        
        with db.cursor() as cursor:
            # Получаем данные задания и статус решения
            cursor.execute('''
                SELECT 
                    t.title, 
                    t.content, 
                    t.file_id,
                    t.file_type,
                    COALESCE(s.status, 'not_attempted') as status,
                    s.score
                FROM tasks t
                LEFT JOIN submissions s 
                    ON s.task_id = t.task_id 
                    AND s.user_id = %s
                WHERE t.task_id = %s
                ORDER BY s.submitted_at DESC
                LIMIT 1
            ''', (user_id, task_id))
            task_data = cursor.fetchone()

        if not task_data:
            await callback.answer("❌ Задание не найдено")
            return

        title, content, file_id, file_type, status, score = task_data
        
        # Формируем текст сообщения
        text = f"📝 <b>{title}</b>\n\n{content}"
        status_map = {
            'pending': "⏳ На проверке",
            'accepted': "✅ Принято",
            'rejected': "❌ Требует доработки",
            'not_attempted': "🚫 Не начато"
        }
        
        if status in status_map:
            text += f"\n\nСтатус: {status_map[status]}"
            if score is not None:
                text += f"\nОценка: {score}/100"

        # Отправка медиа контента
        try:
            if file_id and file_type:
                if file_type == 'photo':
                    await callback.message.answer_photo(
                        file_id, 
                        caption=text,
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await callback.message.answer_document(
                        file_id,
                        caption=text,
                        parse_mode=ParseMode.HTML
                    )
            else:
                await callback.message.answer(
                    text, 
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.error(f"Ошибка отправки медиа: {e}")
            await callback.message.answer(
                "⚠️ Не удалось загрузить вложение задания",
                parse_mode=ParseMode.HTML
            )

        # Обновление клавиатуры
        await callback.message.edit_reply_markup(
            reply_markup=task_keyboard(task_id)
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка загрузки задания: {str(e)}")
        await callback.answer("❌ Ошибка загрузки задания")

# Унифицированный обработчик модулей
async def handle_module_selection(callback: types.CallbackQuery, module_id: int):
    try:
        with db.cursor() as cursor:
            # Получаем данные модуля
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

            # Получаем задания модуля
            cursor.execute(
                "SELECT task_id, title FROM tasks WHERE module_id = %s",
                (module_id,))
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
async def handle_module_selection_wrapper(callback: types.CallbackQuery):
    module_id = int(callback.data.split("_")[1])
    await handle_module_selection(callback, module_id)
    
async def handle_module_selection(callback: types.CallbackQuery):
    try:
        module_id = int(callback.data.split("_")[1])
        
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
                await callback.answer("❌ Модуль не найден")
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
            
            await callback.message.edit_text(
                f"📚 Курс: {course_title}\n"
                f"📦 Модуль: {module_title}\n\n"
                "Выберите задание:",
                reply_markup=builder.as_markup()
            )
        else:
            await callback.answer("ℹ️ В этом модуле пока нет заданий")

    except Exception as e:
        logger.error(f"Ошибка загрузки модуля: {e}")
        await callback.answer("❌ Ошибка загрузки модуля")

# Обработчик возврата к списку модулей курса
@dp.callback_query(F.data.startswith("course_"))
async def show_course_modules(callback: types.CallbackQuery):
    try:
        course_id = int(callback.data.split("_")[1])
        
        with db.cursor() as cursor:
            # Информация о курсе
            cursor.execute(
                "SELECT title FROM courses WHERE course_id = %s",
                (course_id,)
            )
            course_title = cursor.fetchone()[0]

            # Получаем модули курса
            cursor.execute('''
                SELECT module_id, title 
                FROM modules 
                WHERE course_id = %s
            ''', (course_id,))
            modules = cursor.fetchall()

        builder = InlineKeyboardBuilder()
        
        for module_id, title in modules:
            builder.button(
                text=f"📦 {title}", 
                callback_data=f"module_{module_id}"
            )
        
        # Кнопка возврата к списку курсов
        builder.button(
            text="🔙 К списку курсов", 
            callback_data="all_courses"
        )
        builder.adjust(1)

        await callback.message.edit_text(
            f"📚 Курс: {course_title}\nВыберите модуль:",
            reply_markup=builder.as_markup()
        )

    except Exception as e:
        logger.error(f"Ошибка загрузки курса: {e}")
        await callback.answer("❌ Ошибка загрузки курса")

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

class TaskStates(StatesGroup):
    waiting_for_solution = State()

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
@dp.message(TaskStates.waiting_for_solution, F.content_type.in_({'text', 'document', 'photo'}))
async def process_solution(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get('task_id')
    user_id = message.from_user.id
    
    if not task_id:
        await message.answer("❌ Ошибка: задача не определена")
        await state.clear()
        return

    try:
        file_ids = []
        content = None
        
        # Обработка контента
        if message.content_type == 'text':
            content = message.html_text
        elif message.photo:
            file_ids = [f"photo:{message.photo[-1].file_id}"]
        elif message.document:
            file_ids = [f"doc:{message.document.file_id}"]

        if not content and not file_ids:
            await message.answer("❌ Решение должно содержать текст или файл")
            return

        with db.cursor() as cursor:
            # Вставляем новое решение
            cursor.execute('''
                INSERT INTO submissions 
                (user_id, task_id, content, file_id, status, submitted_at) 
                VALUES (%s, %s, %s, %s, 'pending', NOW())
                RETURNING submission_id
            ''', (
                user_id,
                task_id,
                content,
                ",".join(file_ids) if file_ids else None
            ))
            
            submission_id = cursor.fetchone()[0]
            db.conn.commit()

        await message.answer("✅ Решение отправлено на проверку!")
        await notify_admin(submission_id)  # Исправленный вызов

    except psycopg2.Error as e:
        logger.error(f"Database error: {str(e)}")
        await message.answer("❌ Ошибка базы данных")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await message.answer("⚠️ Произошла ошибка")
    finally:
        await state.clear()

async def send_media_with_caption(file_type: str, file_id: str, caption: str, keyboard: InlineKeyboardMarkup):
    try:
        if file_type == "doc":
            await bot.send_document(
                ADMIN_ID,
                document=file_id,
                caption=caption,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await bot.send_photo(
                ADMIN_ID,
                photo=file_id,
                caption=caption,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        logger.error(f"Error sending media: {e}")

async def notify_admin(submission_id: int):
    """Уведомление администратора о новом решении"""
    try:
        with db.cursor() as cursor:
            cursor.execute('''
                SELECT s.content, s.file_id, u.full_name, t.title, s.user_id
                FROM submissions s
                JOIN users u ON s.user_id = u.user_id
                JOIN tasks t ON s.task_id = t.task_id
                WHERE s.submission_id = %s
            ''', (submission_id,))
            
            submission_data = cursor.fetchone()
            if not submission_data:
                return

            content, file_id, full_name, title, student_user_id = submission_data

            text = (
                f"📬 Новое решение (#{submission_id})\n"
                f"👤 Студент: {full_name}\n"
                f"📚 Задание: {title}\n"
                f"📅 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )

            admin_kb = InlineKeyboardBuilder()
            admin_kb.button(
                text="✅ Принять", 
                callback_data=f"accept_{submission_id}_{student_user_id}"
            )
            admin_kb.button(
                text="❌ Требует правок", 
                callback_data=f"reject_{submission_id}_{student_user_id}"
            )
            admin_kb.button(
                text="📨 Написать студенту", 
                url=f"tg://user?id={student_user_id}"
            )
            admin_kb.adjust(2, 1)

            # Отправка медиафайлов
            if file_id:
                file_type, fid = file_id.split(":", 1)
                await send_media_with_caption(
                    file_type, 
                    fid, 
                    text, 
                    admin_kb.as_markup()
                )
            else:
                await bot.send_message(
                    ADMIN_ID,
                    text=text,
                    reply_markup=admin_kb.as_markup()
                )

    except Exception as e:
        logger.error(f"Notification error: {e}")
        await bot.send_message(
            ADMIN_ID,
            f"⚠️ Ошибка уведомления\nID решения: {submission_id}\nОшибка: {str(e)[:200]}"
        )
        
@dp.callback_query(F.data.startswith("accept_") | F.data.startswith("reject_"))
async def handle_submission_review(callback: types.CallbackQuery):
    try:
        data_parts = callback.data.split('_')
        if len(data_parts) != 3:
            raise ValueError("Некорректный формат данных")
            
        action, submission_id_str, user_id_str = data_parts
        submission_id = int(submission_id_str)
        student_user_id = int(user_id_str)  # Переименовали для ясности

        with db.cursor() as cursor:
            cursor.execute('''
                UPDATE submissions 
                SET status = %s 
                WHERE submission_id = %s
                RETURNING task_id
            ''', ("accepted" if action == "accept" else "rejected", submission_id))
            
            task_id = cursor.fetchone()[0]
            
            cursor.execute('SELECT title FROM tasks WHERE task_id = %s', (task_id,))
            task_title = cursor.fetchone()[0]
            db.conn.commit()

        status_text = "принято ✅" if action == "accept" else "отклонено ❌"
        await bot.send_message(
            student_user_id,  # Используем ID из callback_data
            f"📢 Ваше решение по заданию \"{task_title}\" {status_text}."
        )

        await callback.answer("✅ Статус обновлен!")
        await callback.message.delete()

    except (ValueError, IndexError) as e:
        logger.error(f"Ошибка данных: {e}")
        await callback.answer("❌ Ошибка формата данных")
    except psycopg2.Error as e:
        logger.error(f"Ошибка БД: {e}")
        await callback.answer("❌ Ошибка базы данных")
    except Exception as e:
        logger.error(f"Общая ошибка: {e}", exc_info=True)
        await callback.answer("⚠️ Произошла ошибка")
        
def main_menu() -> types.ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    
    # Добавляем кнопки без callback_data
    builder.button(text="📚 Выбрать курс")
    builder.button(text="🆘 Поддержка")
    
    # Настройка расположения (2 кнопки в ряд)
    builder.adjust(2)
    
    return builder.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False
    )

def admin_menu() -> types.ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    
    admin_buttons = [
        "📊 Статистика",
        "📝 Добавить курс",
        "🗑 Удалить курс",
        "➕ Добавить модуль",
        "📌 Добавить задание",
        "👥 Пользователи",
        "🔙 Назад"
    ]
    
    # Добавляем все кнопки
    for button_text in admin_buttons:
        builder.button(text=button_text)
    
    # Настройка расположения:
    # Первые 2 ряда по 2 кнопки, затем 2 кнопки, затем 1
    builder.adjust(2, 2, 2, 1)
    
    return builder.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False
    )

# 3. Обработчик кнопки "Назад" в админ-меню
@dp.message(F.text == "🔙 Назад")
async def admin_back_handler(message: Message, state: FSMContext):
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

### BLOCK 1: BASE SETUP ###
import random 
import os
import logging
import sqlite3
logging.basicConfig()
logger = logging.getLogger('sqlalchemy.engine')
logger.setLevel(logging.INFO)
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from dotenv import load_dotenv
from datetime import datetime
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.utils.media_group import MediaGroupBuilder

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv('TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')
DATABASE_NAME = os.getenv('DATABASE_NAME', 'bot.db')

# Инициализация бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def adapt_datetime(dt):
    return dt.isoformat()

def convert_datimestamp(b):
    return datetime.fromisoformat(b.decode())

sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("timestamp", convert_datimestamp)

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(
            DATABASE_NAME,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        with self.conn:
            # Users table
            self.conn.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                current_course INTEGER,
                registered_at timestamp DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(current_course) REFERENCES courses(course_id) ON DELETE SET NULL
            )''')

            # Courses table
            self.conn.execute('''CREATE TABLE IF NOT EXISTS courses (
                course_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT UNIQUE NOT NULL,
                description TEXT,
                media_id TEXT
            )''')

            # Modules table
            self.conn.execute('''CREATE TABLE IF NOT EXISTS modules (
                module_id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                media_id TEXT,
                FOREIGN KEY(course_id) REFERENCES courses(course_id) ON DELETE CASCADE
            )''')

            # Tasks table
            self.conn.execute('''CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                file_id TEXT,
                FOREIGN KEY(module_id) REFERENCES modules(module_id) ON DELETE CASCADE
            )''')

            # Submissions table с улучшенными ограничениями
            self.conn.execute('''CREATE TABLE IF NOT EXISTS submissions (
                submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected')),
                score INTEGER CHECK(score BETWEEN 0 AND 100),
                submitted_at timestamp DEFAULT CURRENT_TIMESTAMP,
                file_id TEXT,
                content TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            )''')

    def __enter__(self):
        return self.conn.cursor()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()

def init_db():
    # Инициализация уже выполнена в конструкторе Database
    pass

### BLOCK 3: STATES AND KEYBOARDS ###
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

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📚 Выбрать курс")
    builder.button(text="🆘 Поддержка")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def cancel_button():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])


### BLOCK 4: USER HANDLERS (FIXED) ###
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    with Database() as cursor:
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (message.from_user.id,))
        user = cursor.fetchone()
    
    if user:
        await message.answer(f"Добро пожаловать, {user[1]}!", reply_markup=main_menu())
    else:
        await message.answer("📝 Давай познакомимся! Для начала регистрации введи свое ФИО. Это нужно, чтобы твой наставник мог оценивать задания и давать обратную связь. Напиши своё полное имя, фамилию и отчество::", reply_markup=types.ReplyKeyboardRemove())
        await state.set_state(Form.full_name)

@dp.message(Form.full_name)
async def process_full_name(message: types.Message, state: FSMContext):
    if len(message.text.split()) < 2:
        await message.answer("❌ Введите полное ФИО (минимум 2 слова)")
        return
    
    try:
        with Database() as cursor:
            cursor.execute(
                "INSERT INTO users (user_id, full_name) VALUES (?, ?)",
                (message.from_user.id, message.text)
            )
        await message.answer("✅ Регистрация успешно завершена!", reply_markup=main_menu())
        await state.clear()
    except sqlite3.IntegrityError:
        await message.answer("❌ Этот пользователь уже зарегистрирован")
        await state.clear()

### BLOCK 4.1: MEDIA HANDLERS ###
async def handle_media(message: Message, state: FSMContext):
    media_id = None
    if message.photo:
        media_id = message.photo[-1].file_id
    elif message.document:
        media_id = message.document.file_id
    
    if media_id:
        await state.update_data(media_id=media_id)
    return media_id

### BLOCK 5: COURSE HANDLERS (FIXED) ###
def courses_kb():
    with Database() as cursor:
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

@dp.message(F.text == ("📚 Выбрать курс"))
async def show_courses(message: types.Message):
    with Database() as cursor:
        cursor.execute(
            "SELECT courses.title FROM users "
            "LEFT JOIN courses ON users.current_course = courses.course_id "
            "WHERE users.user_id = ?", 
            (message.from_user.id,)
        )
        current_course = cursor.fetchone()
    
    text = "В этом разделе ты можешь выбрать курс, в котором будут модули с заданиями. Выполняй их и отправляй админу на проверку! 🚀 \n\n"
    if current_course and current_course[0]:
        text += f"🎯 Текущий курс: {current_course[0]}\n\n"
    text += "👇 Выбери свой:"
    
    await message.answer(
        text,
        reply_markup=
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Выбрать курс", callback_data="select_course")]]
        )
    )

@dp.callback_query(F.data == ("select_course"))
async def select_course_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📚 Доступные курсы:",
        reply_markup=courses_kb()
    )

### BLOCK 6: NAVIGATION AND CANCEL ###
@dp.callback_query(F.data == "cancel")
async def cancel_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()  # Очищаем состояние
    
    # Проверяем, является ли пользователь администратором
    if str(callback.from_user.id) == ADMIN_ID:
        # Для админа возвращаемся в админ-меню
        await callback.message.edit_text("❌ Действие отменено")
        await callback.message.answer(
            "Админ-меню:",
            reply_markup=admin_menu()
        )
    else:
        # Для обычных пользователей возвращаемся в главное меню
        await callback.message.edit_text("❌ Действие отменено")
        await callback.message.answer(
            "Главное меню:",
            reply_markup=main_menu()
        )
### BLOCK 5.1: COURSE SELECTION FIX ###
@dp.callback_query(F.data.startswith("course_"))
async def select_course(callback: types.CallbackQuery):
    try:
        course_id = int(callback.data.split("_")[1])
        user_id = callback.from_user.id
        
        with Database() as cursor:
            # Обновляем выбранный курс у пользователя
            cursor.execute(
                "UPDATE users SET current_course = ? WHERE user_id = ?",
                (course_id, user_id)
            )
            
            # Получаем данные курса
            cursor.execute(
                "SELECT title, media_id FROM courses WHERE course_id = ?",
                (course_id,)
            )
            course = cursor.fetchone()
        
        if not course:
            raise ValueError("Курс не найден")
        
        text = f"✅ Вы выбрали курс: {course[0]}\nВыберите модуль для решения заданий:"
        kb = modules_kb(course_id)
        
        if course[1]:  # Если есть медиа
            await callback.message.delete()
            await callback.message.answer_photo(
                course[1],
                caption=text,
                reply_markup=kb
            )
        else:
            await callback.message.edit_text(
                text,
                reply_markup=kb
            )
            
    except Exception as e:
        logger.error(f"Error in select_course: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при выборе курса",
            reply_markup=main_menu()
        )

    ### BLOCK 6: COURSE SELECTION HANDLERS ###
@dp.callback_query(F.data == "select_course")
async def select_course_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📚 Доступные курсы:",
        reply_markup=courses_kb()
    )

@dp.callback_query(F.data.startswith("course_"))
async def select_course(callback: types.CallbackQuery):
    try:
        course_id = int(callback.data.split("_")[1])
        user_id = callback.from_user.id
        
        with Database() as cursor:
            cursor.execute(
                "UPDATE users SET current_course = ? WHERE user_id = ?",
                (course_id, user_id)
            )
            cursor.execute(
                "SELECT title, media_id FROM courses WHERE course_id = ?",
                (course_id,)
            )
            course = cursor.fetchone()
        
        text = f"✅ Вы выбрали курс: {course[0]}\nВыберите модуль:"
        kb = modules_kb(course_id)
        
        if course[1]:  # Если есть медиа
            await callback.message.delete()
            await callback.message.answer_photo(
                course[1],
                caption=text,
                reply_markup=kb
            )
        else:
            await callback.message.edit_text(
                text,
                reply_markup=kb
            )
            
    except Exception as e:
        logger.error(f"Error in select_course: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при выборе курса",
            reply_markup=main_menu()
        )

### BLOCK 6: MODULE SYSTEM FIX ###
@dp.callback_query(F.data.startswith("module_"))
async def module_selected(callback: types.CallbackQuery):
    try:
        # Исправленный парсинг module_id
        module_id = int(callback.data.split("_")[1])
        
        with Database() as cursor:
            # Получаем курс для модуля с проверкой существования
            cursor.execute("SELECT course_id FROM modules WHERE module_id = ?", (module_id,))
            course_data = cursor.fetchone()
            
            if not course_data:
                await callback.answer("❌ Модуль не найден")
                return
                
            course_id = course_data[0]
            
            # Получаем название модуля с проверкой
            cursor.execute("SELECT title FROM modules WHERE module_id = ?", (module_id,))
            module_data = cursor.fetchone()
            
            if not module_data:
                await callback.answer("❌ Название модуля не найдено")
                return
                
            module_title = module_data[0]
            
            # Получаем задания с проверкой
            cursor.execute("SELECT task_id, title FROM tasks WHERE module_id = ?", (module_id,))
            tasks = cursor.fetchall()

        # Создаем уникальный идентификатор для callback
        unique_id = random.randint(1000, 9999)
        builder = InlineKeyboardBuilder()
        
        if tasks:
            for task in tasks:
                builder.button(
                    text=f"📝 {task[1]}", 
                    callback_data=f"task_{task[0]}"
                )
        else:
            await callback.answer("ℹ️ В этом модуле пока нет заданий")
            return
            
        builder.button(
            text="🔙 Назад к модулям", 
            callback_data=f"back_to_modules_{course_id}_{unique_id}"
        )
        builder.adjust(1)

        # Редактируем сообщение с проверкой медиа
        try:
            await callback.message.edit_text(
                f"📂 Модуль: {module_title}\nВыберите задание:",
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            logger.error(f"Message edit error: {str(e)}")
            await callback.answer("⚠️ Ошибка отображения заданий")

    except Exception as e:
        logger.error(f"Module error: {str(e)}", exc_info=True)
        await callback.answer("❌ Ошибка загрузки модуля")

### BLOCK 6.1: BACK TO MODULES FIX ###
@dp.callback_query(F.data.startswith("back_to_modules_"))
async def back_to_modules(callback: CallbackQuery):
    try:
        # Исправленный парсинг course_id
        parts = callback.data.split("_")
        course_id = int(parts[3])  # Новый корректный индекс
        
        with Database() as cursor:
            cursor.execute(
                "SELECT title FROM courses WHERE course_id = ?", 
                (course_id,)
            )
            course_data = cursor.fetchone()
            
            if not course_data:
                await callback.answer("❌ Курс не найден")
                return
                
            course_title = course_data[0]

        # Получаем актуальную клавиатуру модулей
        kb = modules_kb(course_id)
        
        try:
            await callback.message.edit_text(
                f"📚 Курс: {course_title}\nВыберите модуль:",
                reply_markup=kb
            )
        except TelegramBadRequest:
            await callback.answer("Список модулей актуален")
            
    except Exception as e:
        logger.error(f"Back to modules error: {str(e)}", exc_info=True)
        await callback.answer("⚠️ Произошла ошибка при загрузке")

### BLOCK 6.2: MODULES KEYBOARD FIX ###
def modules_kb(course_id: int):
    try:
        with Database() as cursor:
            cursor.execute(
                "SELECT module_id, title FROM modules WHERE course_id = ?",
                (course_id,)
            )
            modules = cursor.fetchall()
        
        builder = InlineKeyboardBuilder()
        
        if modules:
            for module in modules:
                builder.button(
                    text=f"📂 {module[1]}",
                    callback_data=f"module_{module[0]}"
                )
        else:
            # Возвращаем пустую клавиатуру если модулей нет
            builder.button(
                text="❌ Нет доступных модулей", 
                callback_data="no_modules"
            )
            
        builder.button(
            text="🔙 Назад к курсам", 
            callback_data="back_to_courses"
        )
        builder.adjust(1)
        
        return builder.as_markup()
        
    except Exception as e:
        logger.error(f"Modules keyboard error: {str(e)}")
        return InlineKeyboardBuilder().as_markup()

### BLOCK 8.1: SUPPORT SYSTEM ###
@dp.message(F.text == ("🆘 Поддержка"))
async def support_request(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="Написать сообщение", url=f"tg://user?id={ADMIN_ID}")
    await message.answer(
        "📞 Свяжитесь с администратором:",
        reply_markup=builder.as_markup()
    )

### BLOCK 9: TASK SUBMISSION SYSTEM FIX (ИСПРАВЛЕННАЯ ВЕРСИЯ) ###
class TaskStates(StatesGroup):
    waiting_for_solution = State()

@dp.callback_query(F.data.startswith("task_"))
async def task_selected(callback: types.CallbackQuery, state: FSMContext):
    try:
        task_id = int(callback.data.split("_")[1])
        
        with Database() as cursor:
            # Получаем данные задания
            cursor.execute(
                "SELECT title, content, file_id FROM tasks WHERE task_id = ?",
                (task_id,)
            )
            task = cursor.fetchone()
            
            if not task:
                await callback.answer("❌ Задание не найдено")
                return

            # Проверяем предыдущие решения
            cursor.execute(
                "SELECT status, score FROM submissions "
                "WHERE user_id = ? AND task_id = ?",
                (callback.from_user.id, task_id)
            )
            submission = cursor.fetchone()

        text = f"📝 Задание: {task['title']}\n\n{task['content']}"
        
        # Отправляем файл задания, если есть
        if task['file_id']:
            try:
                await callback.message.answer_document(task['file_id'])
            except Exception as e:
                logger.error(f"Ошибка отправки файла задания: {e}")
        
        # Показываем статус решения
        if submission:
            text += f"\n\nСтатус: {submission['status']}\nОценка: {submission['score'] or 'нет'}"
            await callback.message.answer(text)
        else:
            await callback.message.answer(
                text + "\n\nОтправьте ваше решение:",
                reply_markup=cancel_button()
            )
            await state.set_state(TaskStates.waiting_for_solution)
            await state.update_data(task_id=task_id)

    except Exception as e:
        logger.error(f"Ошибка выбора задания: {str(e)}", exc_info=True)
        await callback.answer("❌ Ошибка загрузки задания")

@dp.message(TaskStates.waiting_for_solution, F.content_type.in_({'text', 'document', 'photo'}))
async def process_solution(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data['task_id']
    user_id = message.from_user.id
    
    try:
        file_ids = []
        content = None
        
        # Обрабатываем разные типы контента
        if message.content_type == 'text':
            content = message.text
        elif message.document:
            file_ids.append(f"doc:{message.document.file_id}")
        elif message.photo:
            file_ids.append(f"photo:{message.photo[-1].file_id}")

        # Сохраняем решение в БД
        with Database() as cursor:
            cursor.execute("BEGIN TRANSACTION")
            
            # Проверка на существующее решение
            cursor.execute(
                "SELECT 1 FROM submissions WHERE user_id = ? AND task_id = ?",
                (user_id, task_id)
            )
            if cursor.fetchone():
                await message.answer("❌ Вы уже отправляли решение для этого задания!")
                cursor.execute("ROLLBACK")
                return

            # Вставляем новую запись
            cursor.execute(
                """INSERT INTO submissions 
                (user_id, task_id, submitted_at, file_id, content)
                VALUES (?, ?, ?, ?, ?)""",
                (user_id, task_id, datetime.now().isoformat(), ",".join(file_ids), content)
            )
            cursor.execute("COMMIT")
        
        await message.answer("✅ Решение отправлено на проверку!")
        await notify_admin(task_id, user_id)

    except sqlite3.IntegrityError as e:
        logger.error(f"Ошибка целостности данных: {str(e)}")
        await message.answer("❌ Ошибка: Недействительные данные")
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}", exc_info=True)
        await message.answer("⚠️ Произошла системная ошибка")
    finally:
        await state.clear()

async def notify_admin(task_id: int, user_id: int):
    try:
        if not ADMIN_ID:
            logger.error("ADMIN_ID не установлен!")
            return

        with Database() as cursor:
            # Получаем данные для уведомления
            cursor.execute(
                """SELECT s.content, s.file_id, u.full_name, t.title 
                FROM submissions s
                JOIN users u ON s.user_id = u.user_id
                JOIN tasks t ON s.task_id = t.task_id
                WHERE s.task_id = ? AND s.user_id = ?""",
                (task_id, user_id)
            )
            submission = cursor.fetchone()

            if not submission:
                logger.error(f"Данные не найдены: task_id={task_id}, user_id={user_id}")
                return

            text = (f"📬 Новое решение!\n\n"
                    f"Студент: {submission['full_name']}\n"
                    f"Задание: {submission['title']}\n\n"
                    f"Текст: {submission['content'] or 'Отсутствует'}")

            admin_kb = InlineKeyboardBuilder()
            admin_kb.button(text="✅ Принять", callback_data=f"accept_{task_id}_{user_id}")
            admin_kb.button(text="❌ Вернуть", callback_data=f"reject_{task_id}_{user_id}")

            # Обработка файлов
            if submission['file_id']:
                files = submission['file_id'].split(',')
                media = MediaGroupBuilder()
                
                for idx, file in enumerate(files):
                    file_type, file_id = file.split(":", 1)
                    if idx == 0:  # Первый файл с кнопками
                        if file_type == "doc":
                            await bot.send_document(
                                ADMIN_ID, 
                                document=file_id, 
                                caption=text,
                                reply_markup=admin_kb.as_markup()
                            )
                        elif file_type == "photo":
                            await bot.send_photo(
                                ADMIN_ID,
                                photo=file_id,
                                caption=text,
                                reply_markup=admin_kb.as_markup()
                            )
                    else:  # Остальные файлы в медиагруппе
                        if file_type == "doc":
                            media.add_document(document=file_id)
                        elif file_type == "photo":
                            media.add_photo(photo=file_id)
                
                if len(files) > 1:
                    await bot.send_media_group(ADMIN_ID, media=media.build())
            else:
                await bot.send_message(
                    ADMIN_ID,
                    text,
                    reply_markup=admin_kb.as_markup()
                )

    except Exception as e:
        logger.error(f"Ошибка уведомления: {str(e)}", exc_info=True)
        await bot.send_message(
            ADMIN_ID,
            f"⚠️ Ошибка обработки решения\nTask: {task_id}\nUser: {user_id}"
        )

@dp.callback_query(F.data.startswith("accept_") | F.data.startswith("reject_"))
async def handle_submission_review(callback: types.CallbackQuery):
    try:
        parts = callback.data.split('_')
        if len(parts) != 3:
            await callback.answer("❌ Неверный формат данных")
            return
            
        action, task_id_str, user_id_str = parts
        
        try:
            task_id = int(task_id_str)
            user_id = int(user_id_str)
        except ValueError:
            await callback.answer("❌ Ошибка в данных")
            return

        new_status = "accepted" if action == "accept" else "rejected"

        with Database() as cursor:
            # Обновляем статус решения
            cursor.execute(
                "UPDATE submissions SET status = ? WHERE task_id = ? AND user_id = ?",
                (new_status, task_id, user_id)
            )
            
            # Получаем данные для уведомления
            cursor.execute(
                "SELECT title FROM tasks WHERE task_id = ?",
                (task_id,)
            )
            task_title = cursor.fetchone()['title']

        # Уведомляем пользователя
        user_message = (
            f"📢 Ваше решение по заданию \"{task_title}\" "
            f"{'принято ✅' if action == 'accept' else 'отклонено ❌'}."
        )
        try:
            await bot.send_message(user_id, user_message)
        except exceptions.TelegramForbiddenError:
            logger.error(f"Пользователь {user_id} заблокировал бота")
        except Exception as e:
            logger.error(f"Ошибка уведомления: {e}")

        await callback.answer("✅ Статус обновлен!")
        await callback.message.edit_reply_markup(reply_markup=None)

    except Exception as e:
        logger.error(f"Ошибка обработки решения: {str(e)}", exc_info=True)
        await callback.answer("❌ Ошибка обновления статуса")

### BLOCK 10: ADMIN TASK REVIEW ###
@dp.callback_query(F.data.startswith("accept_"))
async def accept_solution(callback: types.CallbackQuery):
    _, task_id, user_id = map(int, callback.data.split("_"))
    
    with Database() as cursor:
        cursor.execute(
            "UPDATE submissions SET status = 'accepted', score = 5 "
            "WHERE task_id = ? AND user_id = ?",
            (task_id, user_id)
        )
    
    await callback.message.edit_text("✅ Решение принято")
    await bot.send_message(
        user_id,
        "🎉 Ваше решение принято! Оценка: 5/5\nМожете переходить к следующему заданию!"
    )

@dp.callback_query(F.data.startswith("reject_"))
async def reject_solution(callback: types.CallbackQuery):
    _, task_id, user_id = map(int, callback.data.split("_"))
    
    with Database() as cursor:
        cursor.execute(
            "UPDATE submissions SET status = 'rejected' "
            "WHERE task_id = ? AND user_id = ?",
            (task_id, user_id)
        )
    
    await callback.message.edit_text("🔄 Решение возвращено")
    await bot.send_message(
        user_id,
        "⚠️ Решение требует доработки. Пожалуйста, пересмотрите задание."
    )

        ### BLOCK 10: ADMIN TASK REVIEW ###
@dp.callback_query(F.data.startswith("accept_"))
async def accept_solution(callback: types.CallbackQuery):
    _, task_id, user_id = callback.data.split("_")
    
    with Database() as cursor:
        cursor.execute(
            "UPDATE submissions SET status = 'accepted', score = 5 "
            "WHERE task_id = ? AND user_id = ?",
            (int(task_id), int(user_id))
        )
    
    await callback.message.edit_text("✅ Решение принято")
    await bot.send_message(
        user_id,
        "🎉 Ваше решение принято! Оценка: 5/5\n"
        "Можете переходить к следующему заданию!"
    )

@dp.callback_query(F.data.startswith("reject_"))
async def reject_solution(callback: types.CallbackQuery):
    _, task_id, user_id = callback.data.split("_")
    
    with Database() as cursor:
        cursor.execute(
            "UPDATE submissions SET status = 'rejected' "
            "WHERE task_id = ? AND user_id = ?",
            (int(task_id), int(user_id))
        )
    
    await callback.message.edit_text("🔄 Решение возвращено на доработку")
    await bot.send_message(
        user_id,
        "⚠️ Решение требует доработки. Пожалуйста, пересмотрите задание и отправьте снова."
    )

    ### BLOCK 11: ADMIN PANEL ###
ADMIN_COMMANDS = [
    ("📊 Статистика", "stats"),
    ("📝 Добавить курс", "add_course"),
    ("🗑 Удалить курс", "delete_course"),
    ("➕ Добавить модуль", "add_module"),
    ("📌 Добавить задание", "add_task"),
    ("👥 Пользователи", "list_users"),
    ("🔙 В главное меню", "main_menu")
]


### BLOCK 11: ADMIN PANEL ###
def admin_menu():
    builder = ReplyKeyboardBuilder()
    for text, _ in ADMIN_COMMANDS:
        builder.button(text=text)
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)

@dp.callback_query(F.data == "cancel")
async def admin_cancel_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Действие отменено")
    await callback.message.answer(
        "Админ-меню:",
        reply_markup=admin_menu()
    )

@dp.message(F.text == "🔙 В главное меню")
async def back_to_main_menu(message: types.Message):
    await message.answer(
        "Главное меню:",
        reply_markup=main_menu()
    )

@dp.message(F.text == "👥 Пользователи")
async def list_users(message: types.Message):
    if message.from_user.id != int(ADMIN_ID):
        return
    
    with Database() as cursor:
        cursor.execute('''
            SELECT u.user_id, u.full_name, c.title, COUNT(s.task_id) 
            FROM users u
            LEFT JOIN courses c ON u.current_course = c.course_id
            LEFT JOIN submissions s ON u.user_id = s.user_id
            GROUP BY u.user_id
        ''')
        users = cursor.fetchall()
    
    response = "📊 Список пользователей:\n\n"
    for user in users:
        response += f"👤 {user[1]} ({user[0]})\n"
        response += f"Курс: {user[2] or 'не выбран'}\n"
        response += f"Решено заданий: {user[3]}\n\n"
    
    await message.answer(response)

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.from_user.id != int(ADMIN_ID):
        return
    
    with Database() as cursor:
        cursor.execute('''
            SELECT c.title, COUNT(DISTINCT m.module_id), COUNT(DISTINCT t.task_id), COUNT(s.submission_id)
            FROM courses c
            LEFT JOIN modules m ON c.course_id = m.course_id
            LEFT JOIN tasks t ON m.module_id = t.module_id
            LEFT JOIN submissions s ON t.task_id = s.task_id
            GROUP BY c.course_id
        ''')
        stats = cursor.fetchall()
    
    response = "📈 Статистика по курсам:\n\n"
    for stat in stats:
        response += f"📚 {stat[0]}\n"
        response += f"Модулей: {stat[1]}\n"
        response += f"Заданий: {stat[2]}\n"
        response += f"Решений: {stat[3]}\n\n"
    
    await message.answer(response)

@dp.message(Command("admin"))
async def admin_command(message: types.Message):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("⛔ Доступ запрещен!")
        return
    
    try:
        with Database() as cursor:
            cursor.execute("SELECT 1 FROM courses LIMIT 1")
            
        await message.answer(
            "🛠 Панель администратора:",
            reply_markup=admin_menu()
        )
    except sqlite3.OperationalError as e:
        logger.error(f"Database error: {e}")
        await message.answer("❌ Ошибка подключения к базе данных")
    except Exception as e:
        logger.error(f"Admin panel error: {e}")
        await message.answer("❌ Не удалось загрузить админ-панель")

    ### BLOCK 12: COURSE CREATION ###
@dp.message(F.text == "📝 Добавить курс")
async def add_course_start(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        return
    
    await message.answer(
        "Введите название нового курса:",
        reply_markup=cancel_button()
    )
    await state.set_state(AdminForm.add_course_title)

@dp.message(AdminForm.add_course_title)
async def process_course_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Введите описание курса:")
    await state.set_state(AdminForm.add_course_description)

@dp.message(AdminForm.add_course_description)
async def process_course_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Отправьте медиа для курса (фото/документ) или нажмите /skip")
    await state.set_state(AdminForm.add_course_media)

@dp.message(AdminForm.add_course_media, F.content_type.in_({'photo', 'document'}))
async def process_course_media(message: types.Message, state: FSMContext):
    media_id = await handle_media(message, state)
    data = await state.get_data()
    
    try:
        with Database() as cursor:
            cursor.execute(
                "INSERT INTO courses (title, description, media_id) VALUES (?, ?, ?)",
                (data['title'], data['description'], media_id)
            )
        
        await message.answer(
            f"✅ Курс '{data['title']}' успешно создан!",
            reply_markup=admin_menu()
        )
    
    except sqlite3.IntegrityError:
        await message.answer("❌ Курс с таким названием уже существует!")
    
    await state.clear()

@dp.message(AdminForm.add_course_media, Command('skip'))
async def skip_course_media(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    with Database() as cursor:
        cursor.execute(
            "INSERT INTO courses (title, description) VALUES (?, ?)",
            (data['title'], data['description'])
        )
    
    await message.answer(
        f"✅ Курс '{data['title']}' создан без медиа!",
        reply_markup=admin_menu()
    )
    await state.clear()

### BLOCK 11.1: COURSE DELETION SYSTEM ###
def delete_courses_kb():
    with Database() as cursor:
        cursor.execute("SELECT course_id, title FROM courses")
        courses = cursor.fetchall()
    
    builder = InlineKeyboardBuilder()
    for course in courses:
        builder.button(
            text=f"❌ {course['title']}",
            callback_data=f"delete_course_{course['course_id']}"
        )
    builder.button(text="🔙 Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

@dp.message(F.text == "🗑 Удалить курс")
async def delete_course_start(message: Message):
    if message.from_user.id != int(ADMIN_ID):
        return
    
    with Database() as cursor:
        cursor.execute("SELECT COUNT(*) FROM courses")
        if cursor.fetchone()[0] == 0:
            return await message.answer("❌ Нет доступных курсов для удаления")
    
    await message.answer(
        "📛 Выберите курс для удаления:",
        reply_markup=delete_courses_kb()
    )

@dp.callback_query(F.data.startswith("delete_course_"))
async def confirm_course_deletion(callback: CallbackQuery, state: FSMContext):
    course_id = int(callback.data.split("_")[2])
    
    with Database() as cursor:
        cursor.execute(
            "SELECT title FROM courses WHERE course_id = ?",
            (course_id,)
        )
        course_title = cursor.fetchone()[0]
    
    await state.update_data(course_id=course_id)
    
    confirm_kb = InlineKeyboardBuilder()
    confirm_kb.button(text="⚠️ УДАЛИТЬ", callback_data=f"confirm_delete_{course_id}")
    confirm_kb.button(text="❌ Отмена", callback_data="cancel")
    
    await callback.message.edit_text(
        f"🚨 Вы уверены что хотите удалить курс?\n"
        f"📛 Название: {course_title}\n"
        f"❗️Это действие нельзя отменить!",
        reply_markup=confirm_kb.as_markup()
    )
    await state.set_state(AdminForm.delete_course)

@dp.callback_query(F.data.startswith("confirm_delete_"))
async def execute_course_deletion(callback: CallbackQuery, state: FSMContext):
    course_id = int(callback.data.split("_")[2])
    
    try:
        with Database() as cursor:
            # Получаем название перед удалением для отчета
            cursor.execute(
                "SELECT title FROM courses WHERE course_id = ?",
                (course_id,)
            )
            course_title = cursor.fetchone()[0]
            
            # Удаляем курс
            cursor.execute(
                "DELETE FROM courses WHERE course_id = ?",
                (course_id,)
            )
        
        # Очищаем состояние
        await state.clear()
        
        # Отправляем подтверждение
        await callback.message.edit_text(
            f"✅ Курс '{course_title}' успешно удален!\n"
            f"Все связанные модули и задания также были удалены."
        )
        
        # Уведомляем пользователей
        with Database() as cursor:
            cursor.execute(
                "SELECT user_id FROM users WHERE current_course = ?",
                (course_id,)
            )
            users = cursor.fetchall()
            
            for user in users:
                try:
                    await bot.send_message(
                        user['user_id'],
                        f"📢 Курс '{course_title}' был удален администратором. "
                        f"Пожалуйста, выберите новый курс."
                    )
                except Exception as e:
                    logger.error(f"Ошибка уведомления пользователя {user['user_id']}: {e}")

    except Exception as e:
        logger.error(f"Ошибка удаления курса: {str(e)}")
        await callback.message.answer("❌ Произошла ошибка при удалении курса")
    finally:
        await state.clear()

    ### BLOCK 13: MODULE MANAGEMENT ###
def courses_for_modules_kb():
    with Database() as cursor:
        cursor.execute("SELECT course_id, title FROM courses")
        courses = cursor.fetchall()
    
    builder = InlineKeyboardBuilder()
    for course in courses:
        builder.button(
            text=course[1],
            callback_data=f"addmod_{course[0]}"
        )
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

@dp.message(F.text == "➕ Добавить модуль")
async def add_module_start(message: types.Message, state: FSMContext):
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    await message.answer(
        "Выберите курс для модуля:",
        reply_markup=courses_for_modules_kb()
    )

@dp.callback_query(F.data.startswith("addmod_"))
async def select_course_for_module(callback: types.CallbackQuery, state: FSMContext):
    course_id = int(callback.data.split("_")[1])
    await state.update_data(course_id=course_id)
    await callback.message.answer("Введите название модуля:")
    await state.set_state(AdminForm.add_module_title)

@dp.message(AdminForm.add_module_title)
async def process_module_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    try:
        with Database() as cursor:
            cursor.execute(
                "INSERT INTO modules (course_id, title) VALUES (?, ?)",
                (data['course_id'], message.text)
            )
        
        await message.answer(
            f"✅ Модуль '{message.text}' успешно добавлен!",
            reply_markup=admin_menu()
        )
    
    except Exception as e:
        logger.error(f"Module creation error: {e}")
        await message.answer("❌ Ошибка при создании модуля!")
    
    await state.clear()

def courses_for_tasks_kb():
    with Database() as cursor:
        cursor.execute("SELECT course_id, title FROM courses")
        courses = cursor.fetchall()
    
    builder = InlineKeyboardBuilder()
    for course in courses:
        builder.button(
            text=course[1],
            callback_data=f"addtask_{course[0]}"
        )
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def modules_for_tasks_kb(course_id: int):
    with Database() as cursor:
        cursor.execute(
            "SELECT module_id, title FROM modules WHERE course_id = ?",
            (course_id,)
        )
        modules = cursor.fetchall()
    
    builder = InlineKeyboardBuilder()
    for module in modules:
        builder.button(
            text=module[1],
            callback_data=f"adm_mod_{module[0]}"  # Changed prefix
        )
    builder.button(text="🔙 Назад", callback_data="back_to_tasks_menu")
    builder.adjust(1)
    return builder.as_markup()

@dp.message(F.text == "📌 Добавить задание")
async def add_task_start(message: Message):
    if message.from_user.id != int(ADMIN_ID):
        return
    await message.answer(
        "Выберите курс для задания:",
        reply_markup=courses_for_tasks_kb()
    )

@dp.callback_query(F.data.startswith("addtask_"))
async def select_course_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != int(ADMIN_ID):
        return
    
    try:
        course_id = int(callback.data.split("_")[1])
        await state.update_data(course_id=course_id)
        
        # Проверка наличия модулей
        with Database() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM modules WHERE course_id = ?",
                (course_id,)
            )
            if cursor.fetchone()[0] == 0:
                await callback.answer("❌ В курсе нет модулей!")
                return await callback.message.answer("Сначала создайте модуль в этом курсе")

        await callback.message.edit_text(
            "Выберите модуль:",
            reply_markup=modules_for_tasks_kb(course_id)
        )
        
    except Exception as e:
        logger.error(f"Course select error: {str(e)}")
        await callback.answer("⚠️ Ошибка выбора курса")

@dp.callback_query(F.data.startswith("adm_mod_"))
async def select_module_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != int(ADMIN_ID):
        return
    
    try:
        module_id = int(callback.data.split("_")[2])  # New index
        await state.update_data(module_id=module_id)
        
        with Database() as cursor:
            cursor.execute(
                "SELECT title FROM modules WHERE module_id = ?",
                (module_id,)
            )
            module_title = cursor.fetchone()[0]

        await callback.message.answer(
            f"📌 Создание задания для модуля: {module_title}\n"
            "Введите название задания:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(AdminForm.add_task_title)
        
    except Exception as e:
        logger.error(f"Module select error: {str(e)}")
        await callback.answer("⚠️ Ошибка выбора модуля")

@dp.callback_query(F.data == "back_to_tasks_menu")
async def back_to_tasks_handler(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            "Выберите курс:",
            reply_markup=courses_for_tasks_kb()
        )
    except TelegramBadRequest:
        await callback.answer("Список курсов не изменился")

@dp.callback_query(F.data.startswith("admin_module_"))
async def select_module_for_task(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != int(ADMIN_ID):
        return
    module_id = int(callback.data.split("_")[-1])
    await state.update_data(module_id=module_id)
    await callback.message.answer("Введите название задания:")
    await state.set_state(AdminForm.add_task_title)

@dp.message(AdminForm.add_task_title)
async def process_task_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Введите описание задания:")
    await state.set_state(AdminForm.add_task_content)

@dp.message(AdminForm.add_task_content)
async def process_task_content(message: Message, state: FSMContext):
    await state.update_data(content=message.text)
    await message.answer("Отправьте медиа для задания или /skip")
    await state.set_state(AdminForm.add_task_media)

@dp.message(AdminForm.add_task_media, F.content_type.in_({'photo', 'document'}))
async def process_task_media(message: Message, state: FSMContext):
    file_id = message.document.file_id if message.document else message.photo[-1].file_id
    await state.update_data(file_id=file_id)
    await finalize_task(message, state)

@dp.message(AdminForm.add_task_media, Command("skip"))
async def skip_task_media(message: Message, state: FSMContext):
    await state.update_data(file_id=None)
    await finalize_task(message, state)

async def finalize_task(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        with Database() as cursor:
            cursor.execute(
                "INSERT INTO tasks (module_id, title, content, file_id) VALUES (?, ?, ?, ?)",
                (data['module_id'], data['title'], data['content'], data.get('file_id')))
        await message.answer("✅ Задание создано!", reply_markup=admin_menu())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    await state.clear()

   ### BLOCK 15 (UPDATED): STARTUP ###
if __name__ == '__main__':
    logger.info("Бот запускается...")
    try:
        dp.run_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
    finally:

        pass  # Соединение закрывается автоматически через контекстный менеджер

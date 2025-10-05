import os
import logging
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, PreCheckoutQueryHandler
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
import io
import asyncio
from datetime import datetime

# Хостинг бота начало
from flask import Flask
import threading

# Создаем Flask приложение для веб-сервера
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# Запускаем Flask в отдельном потоке
flask_thread = threading.Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()

# конец хостинг бота


# === НАСТРОЙКИ БОТА - ЗАМЕНИТЕ ЭТИ ЗНАЧЕНИЯ ===
BOT_TOKEN = "8346872542:AAGlnx0UaOZ0g6fmQDZLc9FL57fBeoiORTE"  # Ваш токен от @BotFather
BOT_OWNER_ID = 6523647184  # Ваш Telegram ID (узнать через @userinfobot)
PAYMENT_PROVIDER_TOKEN = "7490307358:TEST:CquDfTkRqNzVGqXS"  # Можно оставить пустым
PROCESSING_COST = 35 # Стоимость обработки в звездах
# === КОНЕЦ НАСТРОЕК ===

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class PaymentSystem:
    def __init__(self):
        self.users_file = "users.json"
        self.load_users()

    def load_users(self):
        """Загрузка данных пользователей из файла"""
        try:
            with open(self.users_file, 'r', encoding='utf-8') as f:
                self.users = json.load(f)
        except FileNotFoundError:
            self.users = {}

    def save_users(self):
        """Сохранение данных пользователей в файл"""
        with open(self.users_file, 'w', encoding='utf-8') as f:
            json.dump(self.users, f, ensure_ascii=False, indent=2)

    def is_owner(self, user_id):
        """Проверка, является ли пользователь владельцем"""
        return user_id == BOT_OWNER_ID

    def can_process_free(self, user_id):
        """Может ли пользователь обрабатывать бесплатно"""
        return self.is_owner(user_id)

    def get_user_balance(self, user_id):
        """Получение баланса пользователя"""
        user_id_str = str(user_id)
        if user_id_str not in self.users:
            self.users[user_id_str] = {
                'balance': 0,
                'processed_count': 0,
                'first_seen': datetime.now().isoformat()
            }
            self.save_users()
        return self.users[user_id_str]['balance']

    def update_balance(self, user_id, amount):
        """Обновление баланса пользователя"""
        user_id_str = str(user_id)
        if user_id_str not in self.users:
            self.users[user_id_str] = {
                'balance': 0,
                'processed_count': 0,
                'first_seen': datetime.now().isoformat()
            }

        self.users[user_id_str]['balance'] += amount
        self.users[user_id_str]['last_activity'] = datetime.now().isoformat()
        self.save_users()

    def increment_processed_count(self, user_id):
        """Увеличение счетчика обработанных изображений"""
        user_id_str = str(user_id)
        if user_id_str not in self.users:
            self.users[user_id_str] = {
                'balance': 0,
                'processed_count': 0,
                'first_seen': datetime.now().isoformat()
            }

        self.users[user_id_str]['processed_count'] += 1
        self.users[user_id_str]['last_activity'] = datetime.now().isoformat()
        self.save_users()


class ImageProcessor:
    def __init__(self):
        self.output_width = 1080
        self.output_height = 1920
        self.cropped_width = 1080
        self.cropped_height = 1325

    def enhance_image_quality(self, image):
        """Улучшение качества изображения"""
        # Легкое размытие для уменьшения шума
        image = image.filter(ImageFilter.GaussianBlur(0.3))

        # Увеличение резкости
        image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3))

        # Увеличение контрастности
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(1.1)

        # Увеличение насыщенности
        enhancer = ImageEnhance.Color(image)
        image = enhancer.enhance(1.05)

        return image

    def process_single_cell(self, original_image, rows, cols, cell_index):
        """Обработка одной ячейки изображения"""
        # Вычисляем размеры ячеек в оригинальном изображении
        cell_width = original_image.width // cols
        cell_height = original_image.height // rows

        # Определяем выбранную ячейку
        row = cell_index // cols
        col = cell_index % cols

        # Координаты выбранной области
        src_x = col * cell_width
        src_y = row * cell_height

        # Вырезаем выбранную ячейку
        cropped_cell = original_image.crop((src_x, src_y, src_x + cell_width, src_y + cell_height))

        # Масштабируем до нужного размера с высоким качеством
        cropped_cell = cropped_cell.resize(
            (self.cropped_width, self.cropped_height),
            Image.Resampling.LANCZOS
        )

        # Улучшаем качество
        cropped_cell = self.enhance_image_quality(cropped_cell)

        # Создаем новое изображение с черным фоном
        result_image = Image.new('RGB', (self.output_width, self.output_height), 'black')

        # Позиционируем по центру
        x_position = (self.output_width - self.cropped_width) // 2
        y_position = (self.output_height - self.cropped_height) // 2

        # Вставляем обработанное изображение
        result_image.paste(cropped_cell, (x_position, y_position))

        return result_image

    def process_all_cells(self, image_path, rows=3, cols=3):
        """Обработка всех ячеек изображения"""
        try:
            # Открываем изображение
            original_image = Image.open(image_path)

            total_cells = rows * cols
            processed_images = []

            # Обрабатываем каждую ячейку
            for cell_index in range(total_cells):
                result_image = self.process_single_cell(original_image, rows, cols, cell_index)
                processed_images.append(result_image)

            return processed_images

        except Exception as e:
            logger.error(f"Error processing image: {e}")
            raise

    def create_grid_preview(self, image_path, rows=3, cols=3):
        """Создание превью с сеткой"""
        try:
            image = Image.open(image_path)
            draw = ImageDraw.Draw(image)

            cell_width = image.width // cols
            cell_height = image.height // rows

            # Рисуем сетку
            for i in range(1, cols):
                x = i * cell_width
                draw.line([(x, 0), (x, image.height)], fill='red', width=2)

            for i in range(1, rows):
                y = i * cell_height
                draw.line([(0, y), (image.width, y)], fill='red', width=2)

            # Нумеруем ячейки
            for row in range(rows):
                for col in range(cols):
                    cell_num = row * cols + col
                    x = col * cell_width + 10
                    y = row * cell_height + 10
                    draw.text((x, y), str(cell_num + 1), fill='red', stroke_width=2)

            return image

        except Exception as e:
            logger.error(f"Error creating grid preview: {e}")
            raise


class TelegramBot:
    def __init__(self):
        self.token = BOT_TOKEN
        self.processor = ImageProcessor()
        self.payment_system = PaymentSystem()
        self.user_data = {}

    def create_main_keyboard(self):
        """Создание основной клавиатуры"""
        keyboard = [
            [InlineKeyboardButton("💰 Баланс", callback_data="balance"),
             InlineKeyboardButton("💎 Пополнить", callback_data="buy")],
            [InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
             InlineKeyboardButton("📖 Помощь", callback_data="help")],
            [InlineKeyboardButton("📸 Обработать фото", callback_data="process_image")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def create_buy_keyboard(self):
        """Создание клавиатуры для пополнения"""
        keyboard = [
            [InlineKeyboardButton("⭐ 35 звезд (1 фото)", callback_data="buy_35")],
            [InlineKeyboardButton("⭐⭐ 70 звезд (2 фото)", callback_data="buy_70")],
            [InlineKeyboardButton("⭐⭐⭐ 105 звезд (3 фото)", callback_data="buy_105")],
            [InlineKeyboardButton("💫 Своя сумма", callback_data="buy_custom")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def create_settings_keyboard(self):
        """Создание клавиатуры настроек"""
        keyboard = [
            [InlineKeyboardButton("3×3 (9 фото)", callback_data="grid_3_3")],
            [InlineKeyboardButton("4×3 (12 фото)", callback_data="grid_4_3")],
            [InlineKeyboardButton("4×4 (16 фото)", callback_data="grid_4_4")],
            [InlineKeyboardButton("5×5 (25 фото)", callback_data="grid_5_5")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def create_back_keyboard(self):
        """Клавиатура с кнопкой назад"""
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        user_id = user.id

        # Получаем баланс пользователя
        balance = self.payment_system.get_user_balance(user_id)

        welcome_text = f"""
👋 Привет, {user.first_name}!

🤖 Я бот для обработки изображений с улучшением качества.

💎 **Система оплаты:**
• Обработка 1 фото: {PROCESSING_COST} звезд
• Вы получаете ВСЕ обработанные изображения сетки
• Владелец бота обрабатывает бесплатно

💰 Ваш баланс: {balance} звезд

📸 **Как использовать:**
1. Нажмите "📸 Обработать фото"
2. Отправьте изображение
3. Получите все обработанные картинки

Используйте кнопки ниже для навигации:
        """

        if update.message:
            await update.message.reply_text(welcome_text, reply_markup=self.create_main_keyboard())
        elif update.callback_query:
            await update.callback_query.message.edit_text(welcome_text, reply_markup=self.create_main_keyboard())

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий на кнопки"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        callback_data = query.data

        if callback_data == "main_menu":
            await self.start(update, context)

        elif callback_data == "balance":
            await self.show_balance(query)

        elif callback_data == "buy":
            await self.show_buy_options(query)

        elif callback_data.startswith("buy_"):
            if callback_data == "buy_custom":
                await self.ask_custom_amount(query)
            else:
                await self.handle_buy_selection(query, callback_data)

        elif callback_data == "settings":
            await self.show_settings(query)

        elif callback_data.startswith("grid_"):
            await self.handle_grid_selection(query, callback_data)

        elif callback_data == "help":
            await self.show_help(query)

        elif callback_data == "process_image":
            await self.request_image(query)

    async def show_balance(self, query):
        """Показать баланс"""
        user_id = query.from_user.id
        balance = self.payment_system.get_user_balance(user_id)
        processed_count = self.payment_system.users.get(str(user_id), {}).get('processed_count', 0)
        is_owner = self.payment_system.is_owner(user_id)

        balance_text = f"""
💰 **Ваш баланс:**

💎 Звезд: {balance}
📊 Обработано фото: {processed_count}
💵 Стоимость обработки: {PROCESSING_COST} звезд

{'🎉 Вы владелец бота! Обработка бесплатна!' if is_owner else f'Для обработки нужно: {PROCESSING_COST} звезд'}
        """

        keyboard = [
            [InlineKeyboardButton("💎 Пополнить баланс", callback_data="buy")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]

        await query.message.edit_text(balance_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def show_buy_options(self, query):
        """Показать варианты пополнения"""
        buy_text = f"""
💎 **Пополнение баланса**

Выберите сумму для пополнения:

• ⭐ 35 звезд - обработка 35 фото
• ⭐⭐ 70 звезд - обработка 70 фото  
• ⭐⭐⭐ 105 звезд - обработка 105 фото
• 💫 Своя сумма - любое количество

После выбора откроется окно оплаты Telegram Stars!
        """

        await query.message.edit_text(buy_text, reply_markup=self.create_buy_keyboard(), parse_mode='Markdown')

    async def handle_buy_selection(self, query, callback_data):
        """Обработка выбора суммы пополнения"""
        amounts = {
            "buy_35": 35,
            "buy_70": 70,
            "buy_105": 105
        }

        amount = amounts.get(callback_data, 35)
        await self.send_stars_invoice(query, amount)

    async def send_stars_invoice(self, query, amount):
        """Отправка инвойса для оплаты звездами"""
        user_id = query.from_user.id

        # Создаем описание платежа
        title = f"Пополнение баланса на {amount} звезд"
        description = f"""
💎 Пополнение баланса бота

После оплаты вы получите:
• {amount} звезд на балансе
• Возможность обработать {amount} фото
• Доступ ко всем функциям бота

Спасибо за использование нашего бота!
        """

        # Для звезд используем сумму как есть (без умножения)
        prices = [LabeledPrice("Звезды", amount)]

        # Параметры для платежа звездами
        payload = f"stars_payment_{user_id}_{amount}"

        # Валюта для звезд
        currency = "XTR"

        try:
            await query.message.reply_invoice(
                title=title,
                description=description,
                payload=payload,
                provider_token=PAYMENT_PROVIDER_TOKEN,
                currency=currency,
                prices=prices,
                need_name=False,
                need_phone_number=False,
                need_email=False,
                need_shipping_address=False,
                is_flexible=False,
                max_tip_amount=0
            )
        except Exception as e:
            logger.error(f"Error sending invoice: {e}")
            # Если платежи не настроены, показываем альтернативу
            await query.message.reply_text(
                f"❌ Платежная система временно недоступна\n\n"
                f"Для пополнения на {amount} звезд:\n"
                f"1. Нажмите на скрепку 📎\n"
                f"2. Выберите 'Денежный перевод'\n"
                f"3. Отправьте {amount} звезд\n"
                f"4. Баланс обновится автоматически",
                reply_markup=self.create_back_keyboard()
            )

    async def ask_custom_amount(self, query):
        """Запрос пользовательской суммы"""
        custom_text = """
💫 **Укажите свою сумму**

Введите количество звезд для пополнения (минимум 35):

Просто отправьте число в чат:
▫️ 35 - для 35 фото
▫️ 70 - для 70 фото  
▫️ 100 - для 100 фото
▫️ Или любое другое число

После ввода откроется окно оплаты.
        """

        await query.message.edit_text(custom_text, reply_markup=self.create_back_keyboard(), parse_mode='Markdown')

        # Сохраняем состояние для обработки пользовательского ввода
        self.user_data[query.from_user.id] = {'waiting_for_amount': True}

    async def handle_custom_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка пользовательской суммы пополнения"""
        user_id = update.effective_user.id

        # Проверяем, ожидаем ли мы сумму от пользователя
        if (user_id not in self.user_data or
                not self.user_data[user_id].get('waiting_for_amount')):
            return

        try:
            amount = int(update.message.text.strip())

            if amount < 35:
                await update.message.reply_text(
                    "❌ Минимальная сумма пополнения: 35 звезд\n"
                    "Пожалуйста, введите число 35 или больше:",
                    reply_markup=self.create_back_keyboard()
                )
                return

            # Отправляем инвойс для пользовательской суммы
            await self.send_stars_invoice_custom(update, amount)

            # Сбрасываем состояние
            self.user_data[user_id]['waiting_for_amount'] = False

        except ValueError:
            await update.message.reply_text(
                "❌ Пожалуйста, введите число:\n"
                "Например: 35, 100, 200",
                reply_markup=self.create_back_keyboard()
            )

    async def send_stars_invoice_custom(self, update: Update, amount: int):
        """Отправка инвойса для пользовательской суммы"""
        user_id = update.effective_user.id

        title = f"Пополнение баланса на {amount} звезд"
        description = f"""
💎 Пополнение баланса на {amount} звезд

После оплата вы получите:
• {amount} звезд на балансе
• Возможность обрабатывать {amount} фото
• Доступ ко всем функциям бота

Спасибо за использование нашего бота!
        """

        # Для звезд используем сумму как есть (без умножения)
        prices = [LabeledPrice("Звезды", amount)]
        payload = f"stars_payment_custom_{user_id}_{amount}"
        currency = "XTR"

        try:
            await update.message.reply_invoice(
                title=title,
                description=description,
                payload=payload,
                provider_token=PAYMENT_PROVIDER_TOKEN,
                currency=currency,
                prices=prices,
                need_name=False,
                need_phone_number=False,
                need_email=False,
                need_shipping_address=False,
                is_flexible=False,
                max_tip_amount=0
            )
        except Exception as e:
            logger.error(f"Error sending custom invoice: {e}")
            await update.message.reply_text(
                f"❌ Платежная система временно недоступна\n\n"
                f"Для пополнения на {amount} звезд:\n"
                f"1. Нажмите на скрепку 📎\n"
                f"2. Выберите 'Денежный перевод'\n"
                f"3. Отправьте {amount} звезд\n"
                f"4. Баланс обновится автоматически",
                reply_markup=self.create_back_keyboard()
            )

    async def precheckout_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка предварительной проверки платежа"""
        query = update.pre_checkout_query
        await query.answer(ok=True)

    async def successful_payment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка успешного платежа"""
        try:
            user_id = update.effective_user.id
            payment_info = update.message.successful_payment

            # Для звезд сумма приходит как есть (без деления)
            stars_amount = payment_info.total_amount

            # Зачисляем звезды на баланс
            self.payment_system.update_balance(user_id, stars_amount)
            new_balance = self.payment_system.get_user_balance(user_id)

            success_text = f"""
💫 **Оплата прошла успешно!**

✅ Получено: {stars_amount} звезд
💰 Новый баланс: {new_balance} звезд
📸 Можно обработать: {new_balance // PROCESSING_COST} фото

Спасибо за пополнение! Теперь вы можете обрабатывать изображения.
            """

            await update.message.reply_text(
                success_text,
                reply_markup=self.create_main_keyboard(),
                parse_mode='Markdown'
            )

            # Логируем успешный платеж
            logger.info(f"User {user_id} successfully paid {stars_amount} stars")

        except Exception as e:
            logger.error(f"Payment processing error: {e}")
            await update.message.reply_text(
                "❌ Ошибка при обработке платежа. Обратитесь к администратору.",
                reply_markup=self.create_main_keyboard()
            )

    async def show_settings(self, query):
        """Показать настройки сетки"""
        user_id = query.from_user.id
        is_owner = self.payment_system.is_owner(user_id)
        cost_text = "💰 Бесплатно (владелец)" if is_owner else f"💎 {PROCESSING_COST} звезд"

        settings_text = f"""
⚙️ **Настройки сетки**

Выберите размер сетки:

• 3×3 - 9 изображений
• 4×3 - 12 изображений  
• 4×4 - 16 изображений
• 5×5 - 25 изображений

Текущая стоимость: {cost_text}
        """

        await query.message.edit_text(settings_text, reply_markup=self.create_settings_keyboard(),
                                      parse_mode='Markdown')

    async def handle_grid_selection(self, query, callback_data):
        """Обработка выбора сетки"""
        grid_sizes = {
            "grid_3_3": (3, 3),
            "grid_4_3": (4, 3),
            "grid_4_4": (4, 4),
            "grid_5_5": (5, 5)
        }

        cols, rows = grid_sizes.get(callback_data, (3, 3))

        # Сохраняем настройки пользователя
        user_id = query.from_user.id
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        self.user_data[user_id]['grid'] = {'cols': cols, 'rows': rows}

        total_images = cols * rows
        is_owner = self.payment_system.is_owner(user_id)
        cost_text = "бесплатно" if is_owner else f"{PROCESSING_COST} звезд"

        success_text = f"""
✅ Настройки сохранены!

📐 Сетка: {cols}×{rows}
📦 Будет создано: {total_images} изображений
💎 Стоимость: {cost_text}

Теперь нажмите "📸 Обработать фото" для начала работы!
        """

        keyboard = [
            [InlineKeyboardButton("📸 Обработать фото", callback_data="process_image")],
            [InlineKeyboardButton("🔙 Назад", callback_data="settings")]
        ]

        await query.message.edit_text(success_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def show_help(self, query):
        """Показать справку"""
        help_text = f"""
📖 **Как использовать бота:**

1. 💎 Пополните баланс (если нужно)
2. ⚙️ Выберите размер сетки
3. 📸 Отправьте изображение
4. ⚡ Получите все обработанные картинки

💎 **Система оплаты:**
• Обработка 1 фото: {PROCESSING_COST} звезд
• Владелец бота: бесплатно
• Баланс обновляется автоматически

📐 **Формат результата:**
• Размер: 1080×1920 пикселей
• Обрезанная часть: 1080×1325 пикселей
• Позиция: по центру
• Качество: улучшенное
        """

        await query.message.edit_text(help_text, reply_markup=self.create_back_keyboard(), parse_mode='Markdown')

    async def request_image(self, query):
        """Запрос изображения для обработки"""
        user_id = query.from_user.id
        user_balance = self.payment_system.get_user_balance(user_id)
        is_owner = self.payment_system.is_owner(user_id)

        # Получаем настройки сетки
        if user_id in self.user_data and 'grid' in self.user_data[user_id]:
            grid_settings = self.user_data[user_id]['grid']
            cols = grid_settings['cols']
            rows = grid_settings['rows']
            total_images = cols * rows
        else:
            cols, rows = 3, 3
            total_images = 9

        # Проверяем баланс (кроме владельца)
        if not is_owner and user_balance < PROCESSING_COST:
            error_text = f"""
❌ Недостаточно звезд!

💰 Ваш баланс: {user_balance} звезд
💎 Требуется: {PROCESSING_COST} звезд

Пополните баланс чтобы продолжить.
            """

            keyboard = [
                [InlineKeyboardButton("💎 Пополнить баланс", callback_data="buy")],
                [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
            ]

            await query.message.edit_text(error_text, reply_markup=InlineKeyboardMarkup(keyboard),
                                          parse_mode='Markdown')
            return

        request_text = f"""
📸 **Готов к обработке!**

📐 Сетка: {cols}×{rows}
📦 Будет создано: {total_images} изображений
{'🎉 Бесплатно (владелец бота)' if is_owner else f'💎 Стоимость: {PROCESSING_COST} звезд'}

Просто отправьте изображение в этот чат!
        """

        await query.message.edit_text(request_text, reply_markup=self.create_back_keyboard(), parse_mode='Markdown')

    async def handle_image(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка полученного изображения"""
        try:
            user_id = update.effective_user.id
            user_balance = self.payment_system.get_user_balance(user_id)
            is_owner = self.payment_system.is_owner(user_id)

            # Проверяем баланс (кроме владельца)
            if not is_owner and user_balance < PROCESSING_COST:
                await update.message.reply_text(
                    f"❌ Недостаточно звезд!\n\n"
                    f"💰 Ваш баланс: {user_balance} звезд\n"
                    f"💎 Требуется: {PROCESSING_COST} звезд\n\n"
                    f"Пополните баланс чтобы продолжить.",
                    reply_markup=self.create_main_keyboard()
                )
                return

            # Получаем настройки пользователя или используем по умолчанию
            if user_id in self.user_data and 'grid' in self.user_data[user_id]:
                grid_settings = self.user_data[user_id]['grid']
                cols = grid_settings['cols']
                rows = grid_settings['rows']
            else:
                cols, rows = 3, 3

            total_images = cols * rows

            # Подтверждение оплаты (кроме владельца)
            if not is_owner:
                # Списываем стоимость обработки
                self.payment_system.update_balance(user_id, -PROCESSING_COST)
                new_balance = self.payment_system.get_user_balance(user_id)

                await update.message.reply_text(
                    f"💎 Списано {PROCESSING_COST} звезд за обработку\n"
                    f"💰 Остаток на балансе: {new_balance} звезд\n\n"
                    f"🔄 Начинаю обработку..."
                )
            else:
                await update.message.reply_text("🎉 Обработка бесплатно (владелец бота)!")

            # Предупреждение для больших сеток
            if total_images > 9:
                await update.message.reply_text(
                    f"⚠️ Сетка {cols}×{rows} создаст {total_images} изображений\n"
                    f"⏳ Обработка может занять некоторое время..."
                )

            # Скачиваем изображение
            photo_file = await update.message.photo[-1].get_file()
            image_bytes = await photo_file.download_as_bytearray()

            # Сохраняем временное изображение
            temp_input = f"temp_input_{user_id}.jpg"
            with open(temp_input, 'wb') as f:
                f.write(image_bytes)

            # Создаем превью с сеткой
            await update.message.reply_text("🔄 Создаю превью с сеткой...")
            grid_preview = self.processor.create_grid_preview(temp_input, rows, cols)

            # Сохраняем превью
            temp_preview = f"temp_preview_{user_id}.jpg"
            grid_preview.save(temp_preview, 'JPEG', quality=85)

            # Отправляем превью
            with open(temp_preview, 'rb') as photo:
                cost_text = "бесплатно" if is_owner else f"оплачено {PROCESSING_COST} звезд"
                await update.message.reply_photo(
                    photo=photo,
                    caption=f"📐 Сетка: {cols}×{rows}\n"
                            f"📦 Создаю {total_images} изображений...\n"
                            f"💎 {cost_text}\n"
                            f"⏳ Пожалуйста, подождите"
                )

            # Удаляем временный файл превью
            os.remove(temp_preview)

            # Немедленно начинаем обработку всех изображений
            await self.process_all_images(update, user_id, temp_input, cols, rows, total_images)

        except Exception as e:
            logger.error(f"Image handling error: {e}")
            await update.message.reply_text(
                "❌ Ошибка при обработке изображения",
                reply_markup=self.create_main_keyboard()
            )

    async def process_all_images(self, update: Update, user_id: int, image_path: str, cols: int, rows: int, total_images: int):
        """Обработка всех изображений сетки"""
        try:
            # Обрабатываем все изображения
            processed_images = self.processor.process_all_cells(image_path, rows, cols)

            # Отправляем прогресс
            progress_msg = await update.message.reply_text(f"📤 Отправляю 0/{total_images}...")

            # Отправляем все изображения
            sent_count = 0
            for i, image in enumerate(processed_images):
                # Сохраняем временный файл
                temp_output = f"temp_output_{user_id}_{i}.jpg"
                image.save(temp_output, 'JPEG', quality=95)

                # Отправляем изображение
                with open(temp_output, 'rb') as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption=f"🖼️ Ячейка {i + 1}/{total_images}\n"
                                f"📐 1080×1920 | 🎯 1080×1325\n"
                                f"⭐ Улучшенное качество"
                    )

                # Удаляем временный файл
                os.remove(temp_output)

                sent_count += 1

                # Обновляем прогресс каждые 5 изображений или в конце
                if sent_count % 5 == 0 or sent_count == total_images:
                    await progress_msg.edit_text(f"📤 Отправлено {sent_count}/{total_images}...")

                # Небольшая задержка чтобы не превысить лимиты Telegram
                if sent_count % 3 == 0:
                    await asyncio.sleep(1)

            # Увеличиваем счетчик обработанных изображений
            self.payment_system.increment_processed_count(user_id)

            # Финальное сообщение
            user_balance = self.payment_system.get_user_balance(user_id)
            is_owner = self.payment_system.is_owner(user_id)

            final_text = (
                f"✅ Готово! Обработано {total_images} изображений\n"
                f"💾 Все файлы сохранены в максимальном качестве\n"
            )

            if not is_owner:
                final_text += f"💰 Ваш баланс: {user_balance} звезд\n"

            final_text += "📸 Отправьте новое изображение для продолжения"

            await progress_msg.edit_text(final_text, reply_markup=self.create_main_keyboard())

            # Очищаем временные данные
            os.remove(image_path)

        except Exception as e:
            logger.error(f"Processing all images error: {e}")
            await update.message.reply_text(
                "❌ Ошибка при обработке изображений",
                reply_markup=self.create_main_keyboard()
            )

            # Очистка в случае ошибки
            try:
                os.remove(image_path)
            except:
                pass

    def run(self):
        """Запуск бота"""
        application = Application.builder().token(self.token).build()

        # Добавляем обработчики
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CallbackQueryHandler(self.handle_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_custom_amount))
        application.add_handler(MessageHandler(filters.PHOTO, self.handle_image))

        # Обработчики для платежей
        application.add_handler(PreCheckoutQueryHandler(self.precheckout_callback))
        application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, self.successful_payment_callback))

        # Запускаем бота
        print("🤖 Бот запущен...")
        print(f"💎 Стоимость обработки: {PROCESSING_COST} звезд")
        print(f"👑 Владелец бота (ID: {BOT_OWNER_ID}) обрабатывает бесплатно")
        print("📸 Отправьте /start в Telegram чтобы начать!")

        try:
            application.run_polling()
        except Exception as e:
            logger.error(f"Bot error: {e}")
            print(f"❌ Ошибка запуска бота: {e}")


# Этот код должен быть ПОСЛЕ класса TelegramBot
if __name__ == "__main__":
    print("✅ Все настройки корректны, запускаю бота...")
    try:
        bot = TelegramBot()

        # Запускаем бота в основном потоке
        bot.run()

    except Exception as e:

        print(f"❌ Ошибка запуска: {e}")

import os
import json
from datetime import datetime
from dotenv import load_dotenv
import asyncio
from telethon import TelegramClient
from telethon import types
from motor.motor_asyncio import AsyncIOMotorClient
import pytz

load_dotenv()

# Настройки сессии из .env
api_id = int(os.getenv('API_ID'))
api_hash = os.getenv('API_HASH')
phone = os.getenv('PHONE')
session_name = os.getenv('SESSION_NAME')
mongodb_uri = os.getenv('MONGODB_URI')
download_media_enabled = os.getenv('DOWNLOAD_MEDIA_ENABLED', 'False').lower() in ['true', '1', 'yes']
download_media_path = os.getenv('DOWNLOAD_MEDIA_PATH', './media')

client = TelegramClient(session_name, api_id, api_hash)

# Класс для работы с MongoDB
class MongoDBProvider:
    def __init__(self, mongodb_uri):
        print("Инициализация MongoDB клиента...")
        self.client = AsyncIOMotorClient(mongodb_uri)
        self.db = self.client['telegram_db']
        self.messages_collection = self.db['messages']
        self.last_ids_collection = self.db['last_ids']
        self.chats_collection = self.db['chats']

    async def save_messages(self, messages, chat_id):
        print(f"Сохраняем {len(messages)} новых сообщений в базу для чата {chat_id}...")
        for message in messages:
            message_parts = message.split('|')
            message_id = int(message_parts[0])
            message_date = message_parts[1]
            sender_id = int(message_parts[2]) if message_parts[2] != 'None' else None
            text = message_parts[3] if len(message_parts) > 3 else 'No Text'
            media_path = message_parts[4] if len(message_parts) > 4 else None

            existing_message = await self.messages_collection.find_one({'chat_id': chat_id, 'id': message_id})
            if not existing_message:
                await self.messages_collection.insert_one({
                    'chat_id': chat_id,
                    'id': message_id,
                    'date': message_date,
                    'sender_id': sender_id,
                    'text': text,
                    'media_path': media_path
                })

    async def get_last_message_id(self, chat_id):
        last_id_entry = await self.last_ids_collection.find_one({'chat_id': chat_id})
        return last_id_entry['last_message_id'] if last_id_entry else 0

    async def save_last_message_id(self, chat_id, message_id):
        await self.last_ids_collection.update_one(
            {'chat_id': chat_id},
            {'$set': {'last_message_id': message_id}},
            upsert=True
        )

    async def save_chat_info(self, chat_id, title, active):
        await self.chats_collection.update_one(
            {'chat_id': chat_id},
            {'$set': {'title': title}, '$setOnInsert': {'active': active}},
            upsert=True
        )

    async def get_active_chats(self):
        active_chats = await self.chats_collection.find({'active': True}).to_list(length=None)
        return [chat['chat_id'] for chat in active_chats]

    async def load_all_chats(self):
        print("Загружаем все чаты из Telegram...")
        async for dialog in client.iter_dialogs():
            await self.save_chat_info(dialog.id, dialog.title, active=False)
        print("Чаты загружены.")

# Загрузка конфигурации из filters.json
def load_filters():
    filters = {}
    try:
        with open('filters.json', 'r') as f:
            filters = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("Файл filters.json не найден или поврежден, работаем без фильтров.")
        return {
            "filter_message_types": [],
            "filter_keywords": [],
            "filter_hashtags": [],
            "filter_date_from": None,
            "filter_date_to": None,
            "filter_sender_ids": [],
            "filter_max_file_size": 0,
            "chats": []
        }

    # Проверяем и обрабатываем даты
    moscow_tz = pytz.timezone('Europe/Moscow')  # Часовой пояс Москвы (UTC+3)

    if "filter_date_from" in filters and filters["filter_date_from"]:
        try:
            # Парсим дату как местное время (московское)
            dt = datetime.strptime(filters["filter_date_from"], '%Y-%m-%d %H:%M:%S')
            dt = moscow_tz.localize(dt)  # Привязываем к московскому времени
            filters["filter_date_from"] = dt.astimezone(pytz.UTC)  # Преобразуем в UTC
        except ValueError:
            print("Неверный формат даты в filter_date_from, игнорируем фильтр.")
            filters["filter_date_from"] = None

    if "filter_date_to" in filters and filters["filter_date_to"]:
        try:
            # Парсим дату как местное время (московское)
            dt = datetime.strptime(filters["filter_date_to"], '%Y-%m-%d %H:%M:%S')
            dt = moscow_tz.localize(dt)  # Привязываем к московскому времени
            filters["filter_date_to"] = dt.astimezone(pytz.UTC)  # Преобразуем в UTC
        except ValueError:
            print("Неверный формат даты в filter_date_to, игнорируем фильтр.")
            filters["filter_date_to"] = None

    # Устанавливаем пустые значения для отсутствующих ключей
    filters.setdefault("filter_message_types", [])
    filters.setdefault("filter_keywords", [])
    filters.setdefault("filter_hashtags", [])
    filters.setdefault("filter_date_from", None)
    filters.setdefault("filter_date_to", None)
    filters.setdefault("filter_sender_ids", [])
    filters.setdefault("filter_max_file_size", 0)
    filters.setdefault("chats", [])

    return filters

# Функция для выгрузки сообщений из чата
async def fetch_chat_messages(chat_id, filters, batch_size=50):
    storage_provider = MongoDBProvider(mongodb_uri)

    try:
        chat = await client.get_entity(chat_id)
    except ValueError as e:
        print(f"Ошибка: Не удалось найти чат с ID {chat_id}. Причина: {e}")
        return  # Пропускаем этот чат и продолжаем работу
    except Exception as e:
        print(f"Неизвестная ошибка при получении чата с ID {chat_id}: {e}")
        return  # Пропускаем этот чат и продолжаем работу

    # Проверяем тип сущности и выбираем подходящее поле для названия
    if isinstance(chat, (types.Chat, types.Channel)):
        title = chat.title
    elif isinstance(chat, types.User):
        title = chat.username or chat.first_name or 'Unnamed User'
    else:
        title = 'Unknown Chat'
    await storage_provider.save_chat_info(chat.id, title, active=False)

    last_fetched_id = await storage_provider.get_last_message_id(chat_id)
    new_messages = []
    processed_grouped_ids = set()  # Храним обработанные grouped_id, чтобы избежать дублирования

    async for message in client.iter_messages(chat_id, min_id=last_fetched_id, reverse=True):
        if message.id <= last_fetched_id:
            continue

        # Проверяем, является ли сообщение частью альбома
        if message.grouped_id and message.grouped_id not in processed_grouped_ids:
            # Это альбом, получаем все сообщения из группы
            group_messages = []
            async for msg in client.iter_messages(chat_id, limit=100):  # Ограничиваем поиск, чтобы не сканировать весь чат
                if msg.grouped_id == message.grouped_id:
                    group_messages.append(msg)

            print(f"Обнаружен альбом с grouped_id {message.grouped_id}, найдено {len(group_messages)} медиафайлов")
            processed_grouped_ids.add(message.grouped_id)  # Отмечаем альбом как обработанный

            # Используем текст первого сообщения альбома для всех сообщений группы
            album_text = group_messages[0].text if group_messages and group_messages[0].text else 'No Text'

            # Обрабатываем каждое сообщение из группы
            for group_msg in group_messages:
                # Проверяем, проходит ли альбом фильтры, используя текст первого сообщения
                modified_msg = group_msg
                modified_msg.text = album_text  # Присваиваем текст альбома для проверки фильтров

                if not should_process_message(modified_msg, filters):
                    continue

                text = album_text.replace('|', ', ')  # Используем текст альбома для записи
                media_path = None
                if download_media_enabled and should_download_media(modified_msg, filters):
                    media_path = await group_msg.download_media(file=download_media_path)
                    if media_path and not is_valid_media_extension(media_path, filters):
                        os.remove(media_path)
                        media_path = None

                sender_id = str(group_msg.sender_id) if group_msg.sender_id else 'None'
                new_messages.append(f"{group_msg.id}|{group_msg.date}|{sender_id}|{text}|{media_path}")

        elif not message.grouped_id:
            # Это одиночное сообщение
            if not should_process_message(message, filters):
                continue

            text = message.text.replace('|', ', ') if message.text else 'No Text'
            media_path = None
            if download_media_enabled and should_download_media(message, filters):
                media_path = await message.download_media(file=download_media_path)
                if media_path and not is_valid_media_extension(media_path, filters):
                    os.remove(media_path)
                    media_path = None

            sender_id = str(message.sender_id) if message.sender_id else 'None'
            new_messages.append(f"{message.id}|{message.date}|{sender_id}|{text}|{media_path}")

        if len(new_messages) >= batch_size:
            await storage_provider.save_messages(new_messages, chat_id)
            new_messages = []

        last_fetched_id = message.id

    if new_messages:
        await storage_provider.save_messages(new_messages, chat_id)

    if last_fetched_id:
        await storage_provider.save_last_message_id(chat_id, last_fetched_id)

# Функции фильтрации
def should_process_message(message, filters):
    # Если фильтров нет, обрабатываем все сообщения
    if not filters["filter_message_types"]:
        return True

    # Фильтр по датам
    if filters["filter_date_from"]:
        # Игнорируем микросекунды для корректного сравнения
        message_date = message.date.replace(microsecond=0)
        filter_date_from = filters["filter_date_from"].replace(microsecond=0)
        if message_date < filter_date_from:
            return False

    if filters["filter_date_to"]:
        # Игнорируем микросекунды для корректного сравнения
        message_date = message.date.replace(microsecond=0)
        filter_date_to = filters["filter_date_to"].replace(microsecond=0)
        if message_date > filter_date_to:
            return False

    # Фильтр по отправителям
    if filters["filter_sender_ids"] and message.sender_id not in filters["filter_sender_ids"]:
        return False

    # Проверяем хэштеги для всех сообщений, у которых есть текст
    if filters["filter_hashtags"] and message.text:
        if not any(hashtag in message.text for hashtag in filters["filter_hashtags"]):
            return False

    # Проверяем ключевые слова для всех сообщений, у которых есть текст
    if filters["filter_keywords"] and message.text:
        if not any(keyword.lower() in message.text.lower() for keyword in filters["filter_keywords"]):
            return False

    # Проверяем тип сообщения
    if "text" in filters["filter_message_types"] and message.text:
        return True

    if "photo" in filters["filter_message_types"] and isinstance(message.media, types.MessageMediaPhoto):
        # Если хэштеги или ключевые слова указаны, но у фото нет текста, исключаем его
        if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
            return False
        return True

    if "video" in filters["filter_message_types"] and isinstance(message.media, types.MessageMediaDocument) and message.media.document.mime_type.startswith('video'):
        # Если хэштеги или ключевые слова указаны, но у видео нет текста, исключаем его
        if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
            return False
        return True

    if "document" in filters["filter_message_types"] and isinstance(message.media, types.MessageMediaDocument) and not message.media.document.mime_type.startswith('video'):
        # Если хэштеги или ключевые слова указаны, но у документа нет текста, исключаем его
        if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
            return False
        return True

    # Проверяем конкретные форматы
    if message.media:
        if isinstance(message.media, types.MessageMediaPhoto):
            for ext in filters["filter_message_types"]:
                if ext in ["jpg", "jpeg", "png", "gif"] and ext in message.media.photo.mime_type.lower():
                    # Если хэштеги или ключевые слова указаны, но у фото нет текста, исключаем его
                    if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
                        return False
                    return True
        elif isinstance(message.media, types.MessageMediaDocument):
            for ext in filters["filter_message_types"]:
                if message.media.document.mime_type.startswith('video') and ext in ["mp4", "mov", "avi"]:
                    # Если хэштеги или ключевые слова указаны, но у видео нет текста, исключаем его
                    if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
                        return False
                    return True
                if not message.media.document.mime_type.startswith('video') and ext in ["pdf", "doc", "docx", "txt"]:
                    # Если хэштеги или ключевые слова указаны, но у документа нет текста, исключаем его
                    if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
                        return False
                    return True

    return False


def should_download_media(message, filters):
    if not message.media:
        return False

    # Проверяем хэштеги и ключевые слова, если они указаны
    if filters["filter_hashtags"] and message.text:
        if not any(hashtag in message.text for hashtag in filters["filter_hashtags"]):
            return False

    if filters["filter_keywords"] and message.text:
        if not any(keyword.lower() in message.text.lower() for keyword in filters["filter_keywords"]):
            return False

    # Если фильтров нет, скачиваем все медиа
    if not filters["filter_message_types"]:
        return filters["filter_max_file_size"] == 0 or message.media.document.size <= filters["filter_max_file_size"] if isinstance(message.media, types.MessageMediaDocument) else True

    # Проверяем типы медиа
    if "photo" in filters["filter_message_types"] and isinstance(message.media, types.MessageMediaPhoto):
        # Если хэштеги или ключевые слова указаны, но у фото нет текста, не скачиваем
        if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
            return False
        return True

    if "video" in filters["filter_message_types"] and isinstance(message.media, types.MessageMediaDocument) and message.media.document.mime_type.startswith('video'):
        # Если хэштеги или ключевые слова указаны, но у видео нет текста, не скачиваем
        if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
            return False
        return filters["filter_max_file_size"] == 0 or message.media.document.size <= filters["filter_max_file_size"]

    if "document" in filters["filter_message_types"] and isinstance(message.media, types.MessageMediaDocument) and not message.media.document.mime_type.startswith('video'):
        # Если хэштеги или ключевые слова указаны, но у документа нет текста, не скачиваем
        if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
            return False
        return filters["filter_max_file_size"] == 0 or message.media.document.size <= filters["filter_max_file_size"]

    # Проверяем конкретные форматы
    if isinstance(message.media, types.MessageMediaPhoto):
        for ext in filters["filter_message_types"]:
            if ext in ["jpg", "jpeg", "png", "gif"] and ext in message.media.photo.mime_type.lower():
                # Если хэштеги или ключевые слова указаны, но у фото нет текста, не скачиваем
                if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
                    return False
                return True
    elif isinstance(message.media, types.MessageMediaDocument):
        for ext in filters["filter_message_types"]:
            if message.media.document.mime_type.startswith('video') and ext in ["mp4", "mov", "avi"]:
                # Если хэштеги или ключевые слова указаны, но у видео нет текста, не скачиваем
                if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
                    return False
                return filters["filter_max_file_size"] == 0 or message.media.document.size <= filters["filter_max_file_size"]
            if not message.media.document.mime_type.startswith('video') and ext in ["pdf", "doc", "docx", "txt"]:
                # Если хэштеги или ключевые слова указаны, но у документа нет текста, не скачиваем
                if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
                    return False
                return filters["filter_max_file_size"] == 0 or message.media.document.size <= filters["filter_max_file_size"]

    return False

def is_valid_media_extension(media_path, filters):
    if not media_path:
        return True  # Если фильтров нет, разрешаем все

    # Если фильтров нет, разрешаем все расширения
    if not filters["filter_message_types"]:
        return True

    # Проверяем, есть ли конкретные форматы
    for ext in filters["filter_message_types"]:
        if ext in ["jpg", "jpeg", "png", "gif", "mp4", "mov", "avi", "pdf", "doc", "docx", "txt"] and media_path.endswith(ext):
            return True

    # Если указаны только общие типы (photo, video, document), разрешаем все соответствующие форматы
    if "photo" in filters["filter_message_types"] and media_path.endswith(("jpg", "jpeg", "png", "gif")):
        return True
    if "video" in filters["filter_message_types"] and media_path.endswith(("mp4", "mov", "avi")):
        return True
    if "document" in filters["filter_message_types"] and media_path.endswith(("pdf", "doc", "docx", "txt")):
        return True

    return False

# Главная функция
async def main():
    if not await client.is_user_authorized():
        print("Клиент не авторизован, запускаем процесс авторизации...")
        await client.start(phone)
    else:
        print("Клиент уже авторизован.")

    storage_provider = MongoDBProvider(mongodb_uri)
    print("Инициализация MongoDB клиента...")

    await storage_provider.load_all_chats()
    print("Чаты загружены.")

    filters = load_filters()
    print(f"Загруженные фильтры: {filters}")

    # Преобразуем chat_id из строк в целые числа
    chat_ids = []
    try:
        chat_ids = [int(chat_id) for chat_id in filters["chats"]] if filters["chats"] else await storage_provider.get_active_chats()
    except ValueError as e:
        print(f"Ошибка при преобразовании chat_id в число: {e}")
        print("Пропускаем некорректные chat_id и пытаемся взять активные чаты из MongoDB...")
        chat_ids = await storage_provider.get_active_chats()

    print(f"Чаты для парсинга: {chat_ids}")

    if not chat_ids:
        print("Нет чатов для парсинга. Проверьте filters.json или наличие активных чатов в MongoDB.")
        return

    for chat_id in chat_ids:
        print(f"Парсим чат: {chat_id}")
        await fetch_chat_messages(chat_id, filters)

    print("Парсинг завершен.")

if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())

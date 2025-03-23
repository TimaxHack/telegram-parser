import os
import json
from datetime import datetime
from dotenv import load_dotenv
import asyncio
from telethon import TelegramClient
from telethon import types
from motor.motor_asyncio import AsyncIOMotorClient
import pytz
from tzlocal import get_localzone

load_dotenv()

# Настройки сессии из .env
api_id = int(os.getenv('API_ID'))
api_hash = os.getenv('API_HASH')
phone = os.getenv('PHONE')
session_name = os.getenv('SESSION_NAME')
mongodb_uri = os.getenv('MONGODB_URI')
download_media_enabled = os.getenv('DOWNLOAD_MEDIA_ENABLED', 'False').lower() in ['true', '1', 'yes']
download_media_path = os.getenv('DOWNLOAD_MEDIA_PATH', './media')

# Создаем папку для медиа, если она не существует
if download_media_enabled and not os.path.exists(download_media_path):
    os.makedirs(download_media_path)

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

    # Получаем локальный часовой пояс с помощью tzlocal
    local_tz = get_localzone()
    # Если local_tz — это ZoneInfo, преобразуем его в pytz-совместимый часовой пояс
    if not hasattr(local_tz, 'localize'):
        try:
            local_tz = pytz.timezone(str(local_tz))
        except pytz.exceptions.UnknownTimeZoneError:
            print(f"Не удалось определить часовой пояс, используем UTC по умолчанию.")
            local_tz = pytz.UTC
    print(f"Используемый часовой пояс: {local_tz}")

    # Логируем текущее время системы для проверки
    current_time_local = datetime.now(local_tz)
    current_time_utc = current_time_local.astimezone(pytz.UTC)
    print(f"Текущее время системы (местное, {local_tz}): {current_time_local}")
    print(f"Текущее время системы (UTC): {current_time_utc}")

    if "filter_date_from" in filters and filters["filter_date_from"]:
        try:
            dt = datetime.strptime(filters["filter_date_from"], '%Y-%m-%d %H:%M:%S')
            print(f"filter_date_from (исходное, местное время): {dt}")
            dt = local_tz.localize(dt)  # Привязываем к локальному часовому поясу
            print(f"filter_date_from (после привязки к {local_tz}): {dt}")
            filters["filter_date_from"] = dt.astimezone(pytz.UTC)  # Преобразуем в UTC
            print(f"filter_date_from (в UTC): {filters['filter_date_from']}")
        except ValueError:
            print("Неверный формат даты в filter_date_from, игнорируем фильтр.")
            filters["filter_date_from"] = None

    if "filter_date_to" in filters and filters["filter_date_to"]:
        try:
            dt = datetime.strptime(filters["filter_date_to"], '%Y-%m-%d %H:%M:%S')
            print(f"filter_date_to (исходное, местное время): {dt}")
            dt = local_tz.localize(dt)  # Привязываем к локальному часовому поясу
            print(f"filter_date_to (после привязки к {local_tz}): {dt}")
            filters["filter_date_to"] = dt.astimezone(pytz.UTC)  # Преобразуем в UTC
            print(f"filter_date_to (в UTC): {filters['filter_date_to']}")
        except ValueError:
            print("Неверный формат даты в filter_date_to, игнорируем фильтр.")
            filters["filter_date_to"] = None

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
        return
    except Exception as e:
        print(f"Неизвестная ошибка при получении чата с ID {chat_id}: {e}")
        return

    if isinstance(chat, (types.Chat, types.Channel)):
        title = chat.title
    elif isinstance(chat, types.User):
        title = chat.username or chat.first_name or 'Unnamed User'
    else:
        title = 'Unknown Chat'
    await storage_provider.save_chat_info(chat.id, title, active=False)

    last_fetched_id = await storage_provider.get_last_message_id(chat_id)
    new_messages = []
    processed_grouped_ids = set()

    async for message in client.iter_messages(chat_id, min_id=last_fetched_id, reverse=True):
        if message.id <= last_fetched_id:
            continue

        if not should_process_message(message, filters):
            print(f"Сообщение {message.id} отфильтровано: date={message.date}, text={message.text}")
            continue

        if message.grouped_id and message.grouped_id not in processed_grouped_ids:
            group_messages = []
            async for msg in client.iter_messages(chat_id, limit=100):
                if msg.grouped_id == message.grouped_id:
                    group_messages.append(msg)

            print(f"Обнаружен альбом с grouped_id {message.grouped_id}, найдено {len(group_messages)} медиафайлов")
            processed_grouped_ids.add(message.grouped_id)

            album_text = group_messages[0].text if group_messages and group_messages[0].text else 'No Text'
            for group_msg in group_messages:
                if not should_process_message(group_msg, filters):
                    continue

                text = album_text.replace('|', ', ')
                media_path = None
                if download_media_enabled and should_download_media(group_msg, filters):
                    media_path = await group_msg.download_media(file=download_media_path)
                    if media_path:
                        print(f"Скачан медиафайл: {media_path}")
                    else:
                        print(f"Не удалось скачать медиа для сообщения {group_msg.id}")
                    if media_path and not is_valid_media_extension(media_path, filters):
                        print(f"Медиафайл {media_path} удален: неподдерживаемое расширение")
                        os.remove(media_path)
                        media_path = None

                sender_id = str(group_msg.sender_id) if group_msg.sender_id else 'None'
                message_entry = f"{group_msg.id}|{group_msg.date}|{sender_id}|{text}|{media_path}"
                print(f"Сообщение прошло фильтр: {message_entry}")
                new_messages.append(message_entry)

        elif not message.grouped_id:
            text = message.text.replace('|', ', ') if message.text else 'No Text'
            media_path = None
            if download_media_enabled and should_download_media(message, filters):
                media_path = await message.download_media(file=download_media_path)
                if media_path:
                    print(f"Скачан медиафайл: {media_path}")
                else:
                    print(f"Не удалось скачать медиа для сообщения {message.id}")
                if media_path and not is_valid_media_extension(media_path, filters):
                    print(f"Медиафайл {media_path} удален: неподдерживаемое расширение")
                    os.remove(media_path)
                    media_path = None

            sender_id = str(message.sender_id) if message.sender_id else 'None'
            message_entry = f"{message.id}|{message.date}|{sender_id}|{text}|{media_path}"
            print(f"Сообщение прошло фильтр: {message_entry}")
            new_messages.append(message_entry)

        if len(new_messages) >= batch_size:
            await storage_provider.save_messages(new_messages, chat_id)
            new_messages = []

        last_fetched_id = message.id

    if new_messages:
        await storage_provider.save_messages(new_messages, chat_id)

    if last_fetched_id:
        await storage_provider.save_last_message_id(chat_id, last_fetched_id)

# Функции фильтрации
def should_download_media(message, filters):
    if not message.media:
        return False

    if filters["filter_hashtags"] and message.text:
        if not any(hashtag in message.text for hashtag in filters["filter_hashtags"]):
            return False

    if filters["filter_keywords"] and message.text:
        if not any(keyword.lower() in message.text.lower() for keyword in filters["filter_keywords"]):
            return False

    if not filters["filter_message_types"]:
        return filters["filter_max_file_size"] == 0 or message.media.document.size <= filters["filter_max_file_size"] if isinstance(message.media, types.MessageMediaDocument) else True

    if "photo" in filters["filter_message_types"] and isinstance(message.media, types.MessageMediaPhoto):
        if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
            return False
        return True

    if "video" in filters["filter_message_types"] and isinstance(message.media, types.MessageMediaDocument) and message.media.document.mime_type.startswith('video'):
        if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
            return False
        return filters["filter_max_file_size"] == 0 or message.media.document.size <= filters["filter_max_file_size"]

    if "document" in filters["filter_message_types"] and isinstance(message.media, types.MessageMediaDocument) and not message.media.document.mime_type.startswith('video'):
        if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
            return False
        return filters["filter_max_file_size"] == 0 or message.media.document.size <= filters["filter_max_file_size"]

    if isinstance(message.media, types.MessageMediaPhoto):
        for ext in filters["filter_message_types"]:
            if ext in ["jpg", "jpeg", "png", "gif"] and ext in message.media.photo.mime_type.lower():
                if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
                    return False
                return True
    elif isinstance(message.media, types.MessageMediaDocument):
        for ext in filters["filter_message_types"]:
            if message.media.document.mime_type.startswith('video') and ext in ["mp4", "mov", "avi"]:
                if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
                    return False
                return filters["filter_max_file_size"] == 0 or message.media.document.size <= filters["filter_max_file_size"]
            if not message.media.document.mime_type.startswith('video') and ext in ["pdf", "doc", "docx", "txt"]:
                if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
                    return False
                return filters["filter_max_file_size"] == 0 or message.media.document.size <= filters["filter_max_file_size"]

    return False

def is_valid_media_extension(media_path, filters):
    if not media_path:
        return True

    if not filters["filter_message_types"]:
        return True

    for ext in filters["filter_message_types"]:
        if ext in ["jpg", "jpeg", "png", "gif", "mp4", "mov", "avi", "pdf", "doc", "docx", "txt"] and media_path.endswith(ext):
            return True

    if "photo" in filters["filter_message_types"] and media_path.endswith(("jpg", "jpeg", "png", "gif")):
        return True
    if "video" in filters["filter_message_types"] and media_path.endswith(("mp4", "mov", "avi")):
        return True
    if "document" in filters["filter_message_types"] and media_path.endswith(("pdf", "doc", "docx", "txt")):
        return True

    return False

def should_process_message(message, filters):
    if not filters["filter_message_types"]:
        return True

    # Логируем дату сообщения
    print(f"Дата сообщения (message.date, UTC): {message.date}")
    # Преобразуем дату сообщения в местное время (Europe/Moscow) для удобства
    local_tz = pytz.timezone('Europe/Moscow')  # Можно заменить на local_tz из load_filters
    message_date_local = message.date.astimezone(local_tz)
    print(f"Дата сообщения (местное время, {local_tz}): {message_date_local}")

    if filters["filter_date_from"]:
        message_date = message.date.replace(microsecond=0)
        filter_date_from = filters["filter_date_from"].replace(microsecond=0)
        print(f"Сравнение с filter_date_from: message_date={message_date}, filter_date_from={filter_date_from}")
        if message_date < filter_date_from:
            print(f"Сообщение отфильтровано: дата {message_date} раньше filter_date_from {filter_date_from}")
            return False

    if filters["filter_date_to"]:
        message_date = message.date.replace(microsecond=0)
        filter_date_to = filters["filter_date_to"].replace(microsecond=0)
        print(f"Сравнение с filter_date_to: message_date={message_date}, filter_date_to={filter_date_to}")
        if message_date > filter_date_to:
            print(f"Сообщение отфильтровано: дата {message_date} позже filter_date_to {filter_date_to}")
            return False

    if filters["filter_sender_ids"] and message.sender_id not in filters["filter_sender_ids"]:
        print(f"Сообщение отфильтровано: sender_id {message.sender_id} не в filter_sender_ids")
        return False

    if filters["filter_hashtags"] and message.text:
        if not any(hashtag in message.text for hashtag in filters["filter_hashtags"]):
            print(f"Сообщение отфильтровано: нет хэштегов {filters['filter_hashtags']} в тексте")
            return False

    if filters["filter_keywords"] and message.text:
        if not any(keyword.lower() in message.text.lower() for keyword in filters["filter_keywords"]):
            print(f"Сообщение отфильтровано: нет ключевых слов {filters['filter_keywords']} в тексте")
            return False

    if "text" in filters["filter_message_types"] and message.text:
        return True

    if "photo" in filters["filter_message_types"] and isinstance(message.media, types.MessageMediaPhoto):
        if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
            print("Сообщение отфильтровано: фото без текста, но есть фильтры по хэштегам или ключевым словам")
            return False
        return True

    if "video" in filters["filter_message_types"] and isinstance(message.media, types.MessageMediaDocument) and message.media.document.mime_type.startswith('video'):
        if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
            print("Сообщение отфильтровано: видео без текста, но есть фильтры по хэштегам или ключевым словам")
            return False
        return True

    if "document" in filters["filter_message_types"] and isinstance(message.media, types.MessageMediaDocument) and not message.media.document.mime_type.startswith('video'):
        if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
            print("Сообщение отфильтровано: документ без текста, но есть фильтры по хэштегам или ключевым словам")
            return False
        return True

    if message.media:
        if isinstance(message.media, types.MessageMediaPhoto):
            for ext in filters["filter_message_types"]:
                if ext in ["jpg", "jpeg", "png", "gif"] and ext in message.media.photo.mime_type.lower():
                    if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
                        print("Сообщение отфильтровано: фото без текста, но есть фильтры по хэштегам или ключевым словам")
                        return False
                    return True
        elif isinstance(message.media, types.MessageMediaDocument):
            for ext in filters["filter_message_types"]:
                if message.media.document.mime_type.startswith('video') and ext in ["mp4", "mov", "avi"]:
                    if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
                        print("Сообщение отфильтровано: видео без текста, но есть фильтры по хэштегам или ключевым словам")
                        return False
                    return True
                if not message.media.document.mime_type.startswith('video') and ext in ["pdf", "doc", "docx", "txt"]:
                    if (filters["filter_hashtags"] or filters["filter_keywords"]) and not message.text:
                        print("Сообщение отфильтровано: документ без текста, но есть фильтры по хэштегам или ключевым словам")
                        return False
                    return True

    return False


def is_valid_media_extension(media_path, filters):
    if not media_path:
        return True

    if not filters["filter_message_types"]:
        return True

    for ext in filters["filter_message_types"]:
        if ext in ["jpg", "jpeg", "png", "gif", "mp4", "mov", "avi", "pdf", "doc", "docx", "txt"] and media_path.endswith(ext):
            return True

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
    await storage_provider.load_all_chats()

    filters = load_filters()
    # print(f"Загруженные фильтры: {filters}")

    chat_ids = []
    try:
        chat_ids = [int(chat_id) for chat_id in filters["chats"]] if filters["chats"] else await storage_provider.get_active_chats()
    except ValueError as e:
        print(f"Ошибка при преобразовании chat_id в число: {e}")
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

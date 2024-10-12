import os
from dotenv import load_dotenv
import asyncio
from telethon import TelegramClient
from pymongo import MongoClient
from telethon.errors import FloodWaitError

load_dotenv()

# Вводим данные сессии
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
phone = os.getenv('PHONE')
session_name = os.getenv('SESSION_NAME')
output_file = os.getenv('OUTPUT_FILE')
mongodb_uri = os.getenv('MONGODB_URI')  # URI для подключения к MongoDB
provider_type = os.getenv('PROVIDER_TYPE', 'file')  # Определяем тип провайдера (по умолчанию 'file')
chats_id = [-1001512290359, -1001075858615, -165712385, -1002406932785]

# Создаем клиент Telegram
client = TelegramClient(session_name, api_id, api_hash)


# Базовый класс для хранения данных
class StorageProvider:
    """Базовый класс для хранения данных."""
    
    async def load_messages(self, chat_id):
        raise NotImplementedError

    async def save_messages(self, messages, chat_id):
        raise NotImplementedError


# Провайдер для хранения сообщений в файлах
class FileProvider(StorageProvider):
    """Провайдер для хранения сообщений в файлах."""
    
    def __init__(self, output_file):
        self.output_file = output_file
    
    async def load_messages(self, chat_id):
        file_path = f'chat-{abs(chat_id)}.txt'
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.readlines()
        return []

    async def save_messages(self, messages, chat_id):
        file_path = f'chat-{abs(chat_id)}.txt'
        with open(file_path, 'a', encoding='utf-8') as f:
            f.writelines(messages)


# Провайдер для хранения сообщений в MongoDB
class MongoDBProvider(StorageProvider):
    """Провайдер для хранения сообщений в MongoDB."""
    
    def __init__(self, mongodb_uri):
        self.client = MongoClient(mongodb_uri)
        self.db = self.client['telegram_db']
        self.collection = self.db['messages']
    
    async def load_messages(self, chat_id):
        messages = self.collection.find({'chat_id': chat_id})
        return [f"{msg['id']}|{msg['date']}|{msg['sender_id']}|{msg['text']}\n" for msg in messages]
    
    async def save_messages(self, messages, chat_id):
        for message in messages:
            message_parts = message.split('|')
            message_id = int(message_parts[0])
            message_date = message_parts[1]
            sender_id = int(message_parts[2])
            text = message_parts[3]
            
            # Проверка на дубликаты сообщений
            if not self.collection.find_one({'chat_id': chat_id, 'id': message_id}):
                self.collection.insert_one({
                    'chat_id': chat_id,
                    'id': message_id,
                    'date': message_date,
                    'sender_id': sender_id,
                    'text': text
                })


# Функция для выбора провайдера
def get_storage_provider(provider_type):
    if provider_type == 'file':
        return FileProvider(output_file)
    elif provider_type == 'mongodb':
        return MongoDBProvider(mongodb_uri)
    else:
        raise ValueError(f"Неподдерживаемый тип провайдера хранения: {provider_type}")


# Функция для загрузки чатов
async def fetch_chat_messages(chat_id, provider_type='file', batch_size=50):
    storage_provider = get_storage_provider(provider_type)

    await client.start(phone)

    # Загружаем существующие сообщения через провайдер
    existing_messages = await storage_provider.load_messages(chat_id)
    existing_message_ids = {msg.split('|')[0] for msg in existing_messages}

    new_messages = []
    total_new_messages = 0

    # Итерация по сообщениям
    async for message in client.iter_messages(chat_id):
        if str(message.id) not in existing_message_ids:
            new_messages.append(f"{message.id}|{message.date}|{message.sender_id}|{message.text}\n")

        if len(new_messages) >= batch_size:
            await storage_provider.save_messages(new_messages, chat_id)
            total_new_messages += len(new_messages)
            print(f"Добавлено новых сообщений: {len(new_messages)}")
            new_messages = []

        try:
            await asyncio.sleep(0)
        except FloodWaitError as e:
            print(f"Слишком много запросов. Ожидание {e.seconds} секунд.")
            await asyncio.sleep(e.seconds)

    if new_messages:
        await storage_provider.save_messages(new_messages, chat_id)
        total_new_messages += len(new_messages)
        print(f"Добавлено новых сообщений: {len(new_messages)}")

    print(f"Всего новых сообщений добавлено: {total_new_messages}")


# Функция для получения списка диалогов
async def fetch_dialogs():
    dialogs_list = []
    with open(output_file, 'w', encoding='utf-8') as f:
        while True:
            try:
                async for dialog in client.iter_dialogs(limit=None):
                    dialogs_list.append(dialog)
                    output_line = f"Название: {dialog.title}, ID: {dialog.id}, Тип: {type(dialog.entity).__name__}\n"
                    f.write(output_line)
                    print(output_line.strip())

                break
            except FloodWaitError as e:
                print(f"Слишком много запросов. Ожидание {e.seconds} секунд.")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                print(f"Произошла ошибка: {e}")
                break

    print(f"Всего загружено диалогов: {len(dialogs_list)}")
    print(f"Вывод сохранен в файл: {output_file}")


# Основная функция (запуск основного сценария)
async def main():
    print('Запускаем основную функцию.')
    await client.start(phone)

    print('Запускаем функцию для получения списка диалогов.')
    await fetch_dialogs()

    print('Запускаем функцию для загрузки сообщений.')
    for chat_id in chats_id:
        await fetch_chat_messages(chat_id, provider_type)  # Используем провайдер, указанный в окружении


# Запуск клиента
with client:
    client.loop.run_until_complete(main())

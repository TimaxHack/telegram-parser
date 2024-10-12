import os
from dotenv import load_dotenv
import asyncio
from telethon import TelegramClient
from telethon import types
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

# Session data
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
phone = os.getenv('PHONE')
session_name = os.getenv('SESSION_NAME')
mongodb_uri = os.getenv('MONGODB_URI')

client = TelegramClient(session_name, api_id, api_hash)

class MongoDBProvider:
    def __init__(self, mongodb_uri):
        print("Инициализация MongoDB клиента...")
        self.client = AsyncIOMotorClient(mongodb_uri)
        self.db = self.client['telegram_db']
        self.messages_collection = self.db['messages']
        self.last_ids_collection = self.db['last_ids']
        self.chats_collection = self.db['chats']

    async def load_messages(self, chat_id):
        print(f"Загружаем сообщения из базы для чата {chat_id}...")
        messages = await self.messages_collection.find({'chat_id': chat_id}).to_list(length=None)
        return [f"{msg['id']}|{msg['date']}|{msg['sender_id']}|{msg['text']}\n" for msg in messages]

    async def save_messages(self, messages, chat_id):
        print(f"Сохраняем {len(messages)} новых сообщений в базу для чата {chat_id}...")
        for message in messages:
            message_parts = message.split('|')
            message_id = int(message_parts[0])
            message_date = message_parts[1]

            sender_id_str = message_parts[2]
            sender_id = int(sender_id_str) if sender_id_str != 'None' else None
            text = message_parts[3] if len(message_parts) > 3 else 'No Text'

            existing_message = await self.messages_collection.find_one({'chat_id': chat_id, 'id': message_id})
            if not existing_message:
                await self.messages_collection.insert_one({
                    'chat_id': chat_id,
                    'id': message_id,
                    'date': message_date,
                    'sender_id': sender_id,
                    'text': text
                })
        print(f"Сообщения для чата {chat_id} сохранены в базу данных.")

    async def load_last_message_id(self, chat_id):
        print(f"Загружаем последний сохранённый ID сообщения для чата {chat_id}...")
        last_id_entry = await self.last_ids_collection.find_one({'chat_id': chat_id})
        last_message_id = last_id_entry['last_message_id'] if last_id_entry else 0
        print(f"Последний ID сообщения для чата {chat_id}: {last_message_id}")
        return last_message_id

    async def save_last_message_id(self, chat_id, message_id):
        print(f"Обновляем последний ID сообщения для чата {chat_id}: {message_id}")
        await self.last_ids_collection.update_one(
            {'chat_id': chat_id},
            {'$set': {'last_message_id': message_id}},
            upsert=True
        )

    async def save_chat_info(self, chat_id, title, active):
        print(f"Сохраняем информацию о чате {chat_id}: {title}, активный: {active}")
        await self.chats_collection.update_one(
            {'chat_id': chat_id},
            {'$set': {'title': title}, '$setOnInsert': {'active': active}},
            upsert=True
        )

    async def get_active_chats(self):
        print("Получаем список активных чатов...")
        active_chats = await self.chats_collection.find({'active': True}).to_list(length=None)
        active_chat_ids = [chat['chat_id'] for chat in active_chats]
        print(f"Активные чаты: {active_chat_ids}")
        return active_chat_ids

    async def load_all_chats(self):
        print("Загружаем все чаты из Telegram...")
        async for dialog in client.iter_dialogs():
            await self.save_chat_info(dialog.id, dialog.title, active=False)
        print("Чаты загружены.")

async def fetch_chat_messages(chat_id, batch_size=50):
    print(f"Начинаем выгрузку сообщений для чата {chat_id}...")
    storage_provider = MongoDBProvider(mongodb_uri)
    await client.start(phone)

    chat = await client.get_entity(chat_id)
    title = chat.title if isinstance(chat, (types.Chat, types.Channel)) else 'Нет названия'

    await storage_provider.save_chat_info(chat.id, title, active=False)

    last_fetched_id = await storage_provider.load_last_message_id(chat_id)
    new_messages = []
    total_new_messages = 0

    print(f"Получаем сообщения для чата {chat_id}, начиная с ID {last_fetched_id}...")

    async for message in client.iter_messages(chat_id, min_id=last_fetched_id, reverse=True):  # Важно - reverse=True!
        if message.id <= last_fetched_id:
            print(f"Пропускаем сообщение с ID {message.id}, так как оно уже сохранено")
            continue

        # Обрабатываем текст сообщения
        text = message.text.replace('|', ', ') if message.text is not None else 'No Text'

        # Проверяем наличие медиа
        media_path = None
        if message.media:
            media_path = await message.download_media(file="./media")  # Загружаем медиафайл
            print(f"Медиа файл загружен в: {media_path}")

        # Добавляем данные сообщения
        new_messages.append(f"{message.id}|{message.date}|{message.sender_id}|{text}|{media_path}\n")

        print(f"Обработано сообщение ID {message.id} в чате {chat_id}")

        # Сохраняем сообщения по достижению batch_size
        if len(new_messages) >= batch_size:
            await storage_provider.save_messages(new_messages, chat_id)
            total_new_messages += len(new_messages)
            print(f"Сохранено {len(new_messages)} сообщений для чата {chat_id}.")
            new_messages = []

        last_fetched_id = message.id  # Обновляем последний ID после каждого сообщения
        print(f"Обновлён последний сохранённый ID сообщения до: {last_fetched_id}")

    # Сохраняем оставшиеся сообщения, если они есть
    if new_messages:
        await storage_provider.save_messages(new_messages, chat_id)
        total_new_messages += len(new_messages)
        print(f"Сохранены оставшиеся {len(new_messages)} сообщения для чата {chat_id}.")

    # Сохраняем последний ID, если сообщения были выгружены
    if last_fetched_id:
        await storage_provider.save_last_message_id(chat_id, last_fetched_id)
        print(f"Последний ID сообщения для чата {chat_id} обновлён в базе: {last_fetched_id}")

    print(f"В чате {chat_id} найдено и сохранено новых сообщений: {total_new_messages}")

async def main():
    print('Запуск основного процесса...')
    await client.start(phone)

    storage_provider = MongoDBProvider(mongodb_uri)

    print('Чаты уже загружены в базу. Поэтому на время разработки это долгая операция отключена')
    # print('Загружаем все чаты в базу данных...')
    # await storage_provider.load_all_chats()

    print('Получаем список активных чатов...')
    active_chats = await storage_provider.get_active_chats()

    print('Начинаем выгрузку сообщений для активных чатов...')
    for chat_id in active_chats:
        await fetch_chat_messages(chat_id)

    print('Завершение работы.')

with client:
    client.loop.run_until_complete(main())

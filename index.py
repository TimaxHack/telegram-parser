import os
from dotenv import load_dotenv
import asyncio
from telethon import TelegramClient
from pymongo import MongoClient
from telethon.errors import FloodWaitError

load_dotenv()

# Session data
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
phone = os.getenv('PHONE')
session_name = os.getenv('SESSION_NAME')
output_file = os.getenv('OUTPUT_FILE')
mongodb_uri = os.getenv('MONGODB_URI')
provider_type = os.getenv('PROVIDER_TYPE', 'mongodb')  # Изменено на 'mongodb' по умолчанию
chats_id = [-1001512290359, -1001075858615, -165712385, -1002406932785]

# Create the Telegram client
client = TelegramClient(session_name, api_id, api_hash)

class StorageProvider:
    async def load_messages(self, chat_id):
        raise NotImplementedError

    async def save_messages(self, messages, chat_id):
        raise NotImplementedError

    async def load_last_message_id(self, chat_id):
        return 0

    async def save_last_message_id(self, chat_id, message_id):
        raise NotImplementedError

    async def save_chat_info(self, chat_id, title):
        raise NotImplementedError


class MongoDBProvider(StorageProvider):
    def __init__(self, mongodb_uri):
        self.client = MongoClient(mongodb_uri)
        self.db = self.client['telegram_db']
        self.messages_collection = self.db['messages']
        self.last_ids_collection = self.db['last_ids']
        self.chats_collection = self.db['chats']

    async def load_messages(self, chat_id):
        messages = self.messages_collection.find({'chat_id': chat_id})
        return [f"{msg['id']}|{msg['date']}|{msg['sender_id']}|{msg['text']}\n" for msg in messages]

    async def save_messages(self, messages, chat_id):
        for message in messages:
            message_parts = message.split('|')
            message_id = int(message_parts[0])
            message_date = message_parts[1]

            sender_id_str = message_parts[2]
            sender_id = int(sender_id_str) if sender_id_str != 'None' else None
            text = message_parts[3] if len(message_parts) > 3 else 'No Text'

            if not self.messages_collection.find_one({'chat_id': chat_id, 'id': message_id}):
                self.messages_collection.insert_one({
                    'chat_id': chat_id,
                    'id': message_id,
                    'date': message_date,
                    'sender_id': sender_id,
                    'text': text
                })

    async def load_last_message_id(self, chat_id):
        last_id_entry = self.last_ids_collection.find_one({'chat_id': chat_id})
        return last_id_entry['last_message_id'] if last_id_entry else 0

    async def save_last_message_id(self, chat_id, message_id):
        self.last_ids_collection.update_one(
            {'chat_id': chat_id},
            {'$set': {'last_message_id': message_id}},
            upsert=True
        )

    async def save_chat_info(self, chat_id, title):
        if not self.chats_collection.find_one({'chat_id': chat_id}):
            self.chats_collection.insert_one({
                'chat_id': chat_id,
                'title': title
            })


def get_storage_provider(provider_type):
    if provider_type == 'mongodb':
        return MongoDBProvider(mongodb_uri)
    else:
        raise ValueError(f"Unsupported storage provider type: {provider_type}")


async def fetch_chat_messages(chat_id, provider_type='mongodb', batch_size=50):
    storage_provider = get_storage_provider(provider_type)
    await client.start(phone)

    # Сохранение информации о чате
    chat = await client.get_entity(chat_id)
    await storage_provider.save_chat_info(chat.id, chat.title)

    last_fetched_id = await storage_provider.load_last_message_id(chat_id)

    new_messages = []
    total_new_messages = 0

    async for message in client.iter_messages(chat_id, min_id=last_fetched_id):
        text = message.text.replace('|', ', ') if message.text is not None else 'No Text'
        new_messages.append(f"{message.id}|{message.date}|{message.sender_id}|{text}\n")

        if len(new_messages) >= batch_size:
            await storage_provider.save_messages(new_messages, chat_id)
            total_new_messages += len(new_messages)
            new_messages = []

        last_fetched_id = message.id

    if new_messages:
        await storage_provider.save_messages(new_messages, chat_id)
        total_new_messages += len(new_messages)

    if last_fetched_id is not None:
        await storage_provider.save_last_message_id(chat_id, last_fetched_id)

    print(f"Chat ID {chat_id}: Найдено новых сообщений: {total_new_messages}. Записано в БД: {total_new_messages}")


async def main():
    print('Запуск основной функции.')
    await client.start(phone)

    print('Получение сообщений чатов.')
    for chat_id in chats_id:
        await fetch_chat_messages(chat_id, provider_type)


with client:
    client.loop.run_until_complete(main())

from telethon import TelegramClient
import os
from dotenv import load_dotenv
import asyncio
from telethon.errors import FloodWaitError

load_dotenv()

# Вводим данные сессии
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
phone = os.getenv('PHONE')
session_name = os.getenv('SESSION_NAME')
output_file = os.getenv('OUTPUT_FILE')

# Создаем клиент
client = TelegramClient(session_name, api_id, api_hash)

async def main():
    print('Запускаем основную функцию.')
    await client.start(phone)
    print('Запускаем функцию для получения списка диалогов')
    await fecth_dialogs()
    print('Запускаем функцию для загрузки сообщений')
    await fetch_chat_messages(-1001512290359) # Чат проповедей глубины @propoved_deep

async def fecth_dialogs():
    dialogs_list = []  # Переменная для хранения всех диалогов
    # Открываем файл для записи
    with open(output_file, 'w', encoding='utf-8') as f:
        while True:
            try:
                # Используем iter_dialogs для получения всех диалогов
                async for dialog in client.iter_dialogs(limit=None):  # Устанавливаем limit=None для получения всех диалогов
                    dialogs_list.append(dialog)
                    output_line = f"Название: {dialog.title}, ID: {dialog.id}, Тип: {type(dialog.entity).__name__}\n"
                    f.write(output_line)  # Записываем информацию в файл
                    print(output_line.strip())  # Печатаем на экран для контроля

                # Если диалоги закончились, выходим из цикла
                break
            except errors.FloodWaitError as e:
                print(f"Слишком много запросов. Ожидание {e.seconds} секунд.")
                await asyncio.sleep(e.seconds)  # Ожидаем, прежде чем повторить запрос
            except Exception as e:
                print(f"Произошла ошибка: {e}")
                break  # Выход из цикла в случае ошибки

    print(f"Всего загружено диалогов: {len(dialogs_list)}")
    print(f"Вывод сохранен в файл: {output_file}")

async def send_message():
    await client.start(phone)
    
    # ID пользователя @suenot
    user_id = 50095099
    
    # Тестовое сообщение
    test_message = "Привет, Evgeniy! Это тестовое сообщение от бота."
    
    # Отправляем сообщение
    await client.send_message(user_id, test_message)
    print(f"Сообщение отправлено пользователю с ID: {user_id}")

async def load_existing_messages(chat_id):
    """Загружает уже существующие сообщения из файла, если он существует."""
    output_file = f'chat-{abs(chat_id)}.txt'  # Имя файла для сохранения сообщений с ID чата
    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8') as f:
            return f.readlines()
    return []

async def save_messages(messages, chat_id):
    """Сохраняет новые сообщения в текстовый файл."""
    output_file = f'chat-{abs(chat_id)}.txt'  # Имя файла для сохранения сообщений с ID чата
    with open(output_file, 'a', encoding='utf-8') as f:  # Открываем файл в режиме добавления
        f.writelines(messages)

async def fetch_chat_messages(chat_id, batch_size=50):
    await client.start(phone)

    # Загружаем уже существующие сообщения
    existing_messages = await load_existing_messages(chat_id)
    existing_message_ids = {msg.split('|')[0] for msg in existing_messages}

    new_messages = []
    total_new_messages = 0  # Общее количество новых сообщений

    # Итерация по сообщениям чата
    async for message in client.iter_messages(chat_id):
        # Если сообщение уже существует, пропускаем его
        if str(message.id) not in existing_message_ids:
            new_messages.append(f"{message.id}|{message.date}|{message.sender_id}|{message.text}\n")

        # Если накоплен пакет из batch_size сообщений, записываем его в файл
        if len(new_messages) >= batch_size:
            await save_messages(new_messages, chat_id)
            total_new_messages += len(new_messages)
            print(f"Добавлено новых сообщений: {len(new_messages)}")
            new_messages = []  # Очищаем список для следующего пакета

        try:
            await asyncio.sleep(0)  # Безопасная точка для переключения контекста
        except FloodWaitError as e:
            print(f"Слишком много запросов. Ожидание {e.seconds} секунд.")
            await asyncio.sleep(e.seconds)

    # Записываем любые оставшиеся сообщения, если они есть
    if new_messages:
        await save_messages(new_messages, chat_id)
        total_new_messages += len(new_messages)
        print(f"Добавлено новых сообщений: {len(new_messages)}")

    print(f"Всего новых сообщений добавлено: {total_new_messages}")

# Запуск клиента
with client:
    client.loop.run_until_complete(main())

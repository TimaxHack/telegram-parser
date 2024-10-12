## Create api key
go https://my.telegram.org/auth

# Create .env
```
API_ID = 
API_HASH = 
PHONE = 
SESSION_NAME = 
OUTPUT_FILE = 
```

## Start
```
python3 -m venv path/to/venv
source path/to/venv/bin/activate

pip install telethon
pip install python-dotenv
pip install pymongo

python index.py
```

При первом запуске нужно будет указать номер телефона, код подтверждения и пароль. Далее авторизация будет проходить через сессию. Сессия появится в папке с проектом <yout_session_name>.session.

# Lib docs
- [Метод для получения списка чатов](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.dialogs.DialogMethods.get_dialogs)



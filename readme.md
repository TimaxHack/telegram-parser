## Install mongo
ddocker run --name mongodb \
  -e MONGO_INITDB_ROOT_USERNAME=admin \
  -e MONGO_INITDB_ROOT_PASSWORD=pass \
  -p 27017:27017 \
  -d mongo:latest

## Create api key
go https://my.telegram.org/auth

# Create .env and fill:
```
API_ID = <YOUR_API_ID>
API_HASH = <YOUR_API_HASH>
PHONE = <YOUR_PHONE>
SESSION_NAME = <HOW_YOU_WANT_TO_NAME_SESSION_FILE>
OUTPUT_FILE = <HOW_YOU_WANT_TO_NAME_FILE_WITH_CHATS_LIST>
MONGODB_URI = "mongodb://admin:pass@127.0.0.1:27017/?connectTimeoutMS=30000&socketTimeoutMS=30000"
PROVIDER_TYPE = "mongodb"
DOWNLOAD_MEDIA_ENABLED = "True"
DOWNLOAD_MEDIA_PATH = "./media"
```

## Start
```
python3 -m venv path/to/venv
source path/to/venv/bin/activate

pip install telethon
pip install python-dotenv
pip install pymongo
pip install motor

mkdir media

python index.py
```

При первом запуске нужно будет указать номер телефона, код подтверждения и пароль. Далее авторизация будет проходить через сессию. Сессия появится в папке с проектом <yout_session_name>.session.

# Lib docs
- [Метод для получения списка чатов](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.dialogs.DialogMethods.get_dialogs)



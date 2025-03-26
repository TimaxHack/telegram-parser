Рад, что тебе в целом нравится предложенная архитектура! Я переработаю её, чтобы она больше соответствовала структуре и стилю, которые ты указал в своём примере. Вот обновлённая версия архитектуры системы интеграции Telegram с MCP, с акцентом на схемы Mermaid, чёткие потоки данных и подробное описание компонентов.

---

# Архитектура системы интеграции Telegram с MCP

## Схема архитектуры

Ниже представлена общая схема системы, которая отражает взаимодействие компонентов в Docker Compose окружении:

```mermaid
graph TD
    %% Внешние сервисы
    TelegramAPI[Telegram API] --- |MTProto| TelegramService
    LLM[Large Language Model] --- |HTTP/WS| MCPServer
    
    subgraph "Docker Compose Окружение"
        %% Telegram API Сервер
        subgraph "Telegram API Сервер"
            TelegramService[Django REST API]
            CeleryWorker[Celery Worker]
            CeleryBeat[Celery Beat]
            
            TelegramService --- |Tasks| CeleryWorker
            TelegramService --- |Schedule| CeleryBeat
            CeleryBeat --- |Scheduled Tasks| CeleryWorker
        end
        
        %% Базы данных и хранилища
        PostgreSQL[(PostgreSQL)]
        Redis[(Redis)]
        MinIO[(MinIO S3)]
        
        %% MCP Сервер
        MCPServer[MCP TypeScript Server]
        
        %% Связи внутри Docker Compose
        TelegramService --- |SQL| PostgreSQL
        TelegramService --- |Cache/Queue| Redis
        CeleryWorker --- |Cache/Queue| Redis
        CeleryBeat --- |Cache/Queue| Redis
        TelegramService --- |S3 API| MinIO
        CeleryWorker --- |S3 API| MinIO
        
        MCPServer --- |HTTP API| TelegramService
    end
    
    %% Опциональные внешние соединения
    ExternalS3[(Внешнее S3 хранилище)]
    TelegramService -.- |S3 API| ExternalS3
    CeleryWorker -.- |S3 API| ExternalS3
    
    %% Стили
    classDef mainService fill:#f96,stroke:#333,stroke-width:2px
    classDef database fill:#6b8e23,stroke:#333,stroke-width:2px,color:white
    classDef external fill:#6495ed,stroke:#333,stroke-width:2px
    classDef optional stroke-dasharray: 5 5
    
    class TelegramService,MCPServer mainService
    class PostgreSQL,Redis,MinIO database
    class TelegramAPI,LLM,ExternalS3 external
    class ExternalS3 optional
```

## Общий подход

Система разделена на два основных компонента с чётким разделением ответственности:

1. **Telegram API Сервер** — бэкенд на Django REST Framework (DRF), который:
   - Взаимодействует с Telegram API через MTProto (с использованием Telethon).
   - Предоставляет REST API для MCP Сервера.
   - Обрабатывает асинхронные задачи (например, синхронизацию чатов) через Celery.

2. **MCP Сервер** — прослойка на TypeScript, которая:
   - Связывает LLM с Telegram API Сервером через HTTP API.
   - Предоставляет инструменты для авторизации, работы с чатами, сообщениями и медиа.
   - Использует LangChain для интеграции с LLM.

Такой подход обеспечивает:
- Надёжность и масштабируемость за счёт DRF и Celery.
- Гибкость в управлении доступом LLM к Telegram через MCP.
- Асинхронную обработку тяжёлых операций (например, загрузка медиа).

---

## Потоки данных

Потоки данных описывают ключевые сценарии взаимодействия между компонентами:

```mermaid
sequenceDiagram
    participant LLM as LLM
    participant MCP as MCP Сервер
    participant API as Telegram API Сервер
    participant DB as PostgreSQL
    participant S3 as MinIO/S3
    participant Telegram as Telegram API
    
    %% Авторизация
    LLM->>MCP: Запрос авторизации
    MCP->>API: POST /auth/telegram
    API->>Telegram: Запрос кода (Telethon)
    Telegram-->>API: Код отправлен пользователю
    API-->>MCP: Ожидание кода
    MCP-->>LLM: Введите код
    LLM->>MCP: Код подтверждения
    MCP->>API: POST /auth/verify {code}
    API->>Telegram: Подтверждение кода
    Telegram-->>API: Сессия создана
    API->>DB: Сохранение сессии
    API-->>MCP: Сессия активна
    MCP-->>LLM: Авторизация успешна
    
    %% Синхронизация чатов
    LLM->>MCP: Синхронизировать чаты
    MCP->>API: POST /sync/chats {chat_ids}
    API->>Telegram: Получение чатов
    Telegram-->>API: Список чатов
    API->>DB: Сохранение метаданных
    API->>API: Запуск Celery задачи
    API->>Telegram: Получение сообщений
    Telegram-->>API: Сообщения и медиа
    API->>DB: Сохранение сообщений
    API->>S3: Загрузка медиа
    S3-->>API: URL медиа
    API-->>MCP: Синхронизация выполняется
    MCP-->>LLM: Статус синхронизации
    
    %% Чтение сообщений
    LLM->>MCP: Получить сообщения из чата
    MCP->>API: GET /chats/{id}/messages
    API->>DB: Запрос сообщений
    DB-->>API: Сообщения
    API->>S3: Получение URL медиа
    S3-->>API: URL медиа
    API-->>MCP: Сообщения с URL
    MCP-->>LLM: Форматированные данные
    
    %% Отправка сообщения
    LLM->>MCP: Отправить сообщение
    MCP->>API: POST /chats/{id}/messages {text}
    API->>Telegram: Отправка сообщения
    Telegram-->>API: Успех
    API->>DB: Сохранение сообщения
    API-->>MCP: Сообщение отправлено
    MCP-->>LLM: Подтверждение
```

---

## Ключевые алгоритмы

### 1. Алгоритм авторизации в Telegram

```mermaid
flowchart TD
    Start([Начало]) --> CheckSession{Сессия\nсуществует?}
    CheckSession -->|Да| LoadSession[Загрузить сессию]
    CheckSession -->|Нет| RequestPhone[Запросить номер]
    
    LoadSession --> ValidateSession{Сессия\nвалидна?}
    ValidateSession -->|Да| Success([Успех])
    ValidateSession -->|Нет| RequestPhone
    
    RequestPhone --> SendCode[Отправить код]
    SendCode --> WaitCode[Ожидать код]
    WaitCode --> VerifyCode{Код\nверный?}
    
    VerifyCode -->|Да| Check2FA{2FA\nвключена?}
    VerifyCode -->|Нет| ErrorCode[Ошибка кода]
    ErrorCode --> WaitCode
    
    Check2FA -->|Да| RequestPassword[Запросить пароль]
    Check2FA -->|Нет| SaveSession[Сохранить сессию]
    
    RequestPassword --> VerifyPassword{Пароль\nверный?}
    VerifyPassword -->|Да| SaveSession
    VerifyPassword -->|Нет| ErrorPassword[Ошибка пароля]
    ErrorPassword --> RequestPassword
    
    SaveSession --> Success
```

### 2. Алгоритм синхронизации чатов

```mermaid
flowchart TD
    Start([Начало]) --> GetConfig[Получить настройки]
    GetConfig --> FilterChats{Фильтр\nчатов?}
    
    FilterChats -->|Все| FetchAll[Получить все чаты]
    FilterChats -->|Выбранные| FetchSelected[Получить выбранные]
    
    FetchAll --> SaveMetadata[Сохранить метаданные]
    FetchSelected --> SaveMetadata
    
    SaveMetadata --> QueueTasks[Создать задачи Celery]
    QueueTasks --> SyncChat[Синхронизация чата]
    
    SyncChat --> FetchMessages[Получить сообщения]
    FetchMessages --> SaveMessages[Сохранить в БД]
    
    SaveMessages --> HasMedia{Есть\nмедиа?}
    HasMedia -->|Да| DownloadMedia[Загрузить медиа]
    HasMedia -->|Нет| Complete
    
    DownloadMedia --> UploadS3[Сохранить в S3]
    UploadS3 --> Complete([Завершено])
```

---

## Компоненты системы

### 1. Telegram API Сервер (Django REST Framework)

#### Основные компоненты:
- **Аутентификация и авторизация**:
  - Поддержка авторизации через номер телефона или QR-код (Telethon).
  - Сохранение сессий в PostgreSQL.
  - API ключи для MCP Сервера.
  - Permissions в DRF для контроля доступа.

- **Модуль синхронизации**:
  - Импорт всех или выбранных чатов.
  - Асинхронная синхронизация через Celery.
  - Webhook или Long Polling для новых сообщений.

- **База данных**:
  - Модели: чаты, сообщения, пользователи, медиа, сессии.
  - Хранение истории синхронизации.

- **Медиа обработчик**:
  - Загрузка в MinIO или внешнее S3 (Boto3).
  - Опциональное преобразование медиа.
  - Кэширование в Redis.

- **API Endpoints**:
  - `GET /chats` — список чатов.
  - `POST /sync/chats` — запуск синхронизации.
  - `GET /chats/{id}/messages` — получение сообщений.
  - `POST /chats/{id}/messages` — отправка сообщения.

- **Throttling и безопасность**:
  - Ограничение запросов через DRF Throttling.
  - Фильтры по IP и User-Agent.
  - Логирование с помощью `loguru`.

#### Технический стек:
- Django 5.1
- Django REST Framework 3.15
- Telethon 1.36
- Celery 5.4 + Redis 5.0
- PostgreSQL 16
- Boto3 для S3
- Pydantic 2.9 для валидации
- OpenAPI для документации

#### Фильтры для Telegram Parser:
- Максимальный размер файла (`MAX_FILE_SIZE`).
- Типы файлов (фото, видео, документы).
- Ключевые слова и хэштеги.
- Диапазон дат (`offset_date`).
- Список чатов (`chat_ids`).

---

### 2. MCP Сервер (TypeScript SDK)

#### Основные компоненты:
- **Клиент Telegram API Сервера**:
  - HTTP-запросы через Axios.
  - Обработка ошибок и повторные попытки.

- **Инструменты MCP**:
  - `telegram_auth` — авторизация.
  - `telegram_chats` — управление чатами.
  - `telegram_messages` — работа с сообщениями.
  - `telegram_media` — обработка медиа.
  - `telegram_search` — поиск.
  - `telegram_monitor` — мониторинг.

- **Менеджер инструментов**:
  - Динамическая активация инструментов.
  - Конфигурация через JSON.

- **Управление состоянием**:
  - Кэширование в Redis через LangChain.js.
  - Хранение истории запросов.

#### Технический стек:
- TypeScript 5.5
- Axios 1.7
- Winston 3.14 для логирования
- LangChain.js для LLM

---

## Хранение данных

- **PostgreSQL**:
  - Чаты, сообщения, пользователи, сессии.
- **Redis**:
  - Кэш, очереди Celery.
- **MinIO**:
  - Локальное S3-хранилище для медиа.
- **MCP Сервер**:
  - Временный кэш и конфигурация.

---

## Контейнеризация и развертывание

### Docker Compose
- **Сервисы**:
  - `telegram-api` (Django REST API).
  - `celery-worker` и `celery-beat`.
  - `mcp-server` (TypeScript).
  - `postgres`, `redis`, `minio`.

### Запуск
```bash
docker-compose up -d
```

---

## Безопасность

- API ключи между MCP и Telegram API Сервером.
- Throttling в DRF.
- Базовое логирование (Winston и `loguru`).

---

Если что-то нужно доработать или уточнить, дай знать!

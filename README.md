# FinTechHub Backend: Enterprise Card Management & Payment System

A high-performance, enterprise-grade banking backend engineered with **Python 3.10+** and **Django 5.2**. This system provides a secure **JSON-RPC 2.0** interface for high-concurrency financial operations, featuring AES-256 encryption, Redis caching, and ACID-compliant transaction integrity.

**Key Features:**
- JSON-RPC 2.0 API for seamless integration
- Multi-language support (Uzbek, Russian, English)
- Real-time balance management with Redis caching
- Secure card operations with Luhn validation
- QR-code based payment transactions
- Asynchronous notifications via Celery + Telegram
- Comprehensive audit logging with PII masking
- Django admin dashboard for card management
- Role-based access control with custom permissions
- Progressive rate limiting and anti-fraud mechanisms

---

## Requirements

### System Requirements
- **Python**: 3.10 or higher
- **Django**: 5.2+
- **Database**: PostgreSQL 8.0+ (or SQLite for development)
- **Cache**: Redis 6.0+
- **Message Broker**: RabbitMQ or Redis

### Python Dependencies
Core dependencies include:
- `Django==5.2.12` - Web framework
- `djangorestframework` - REST framework
- `psycopg2-binary` - PostgreSQL adapter
- `redis>=5.0` - Redis client
- `celery>=5.3` - Task queue
- `cryptography` - Encryption library
- `jsonrpcserver>=5.0` - JSON-RPC server
- `python-dotenv` - Environment variables
- `pycryptodome` - Cryptographic algorithms

Run `pip install -r requirements.txt` to install all dependencies.

---

## Installation & Setup

### 1. Clone Repository
```bash
git clone https://github.com/Junior-Darksize/fintechhub-project.git
cd fintechhub-project
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create `.env` file in project root:
```env
# Django
DEBUG=True
DJANGO_SECRET_KEY=your-super-secret-key-change-in-production
ALLOWED_HOSTS=localhost,127.0.0.1,api.fintechhub.uz

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/fintechhub
DB_NAME=fintechhub
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432

# Redis & Cache
REDIS_URL=redis://localhost:6379/0
CACHE_URL=redis://localhost:6379/1

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Telegram Bot (for notifications)
TG_TOKEN=your-telegram-bot-token
TG_CHAT_ID=your-telegram-chat-id

# CORS
CORS_ALLOWED_ORIGINS=https://api.fintechhub.uz,http://localhost:3000
```

### 5. Initialize Database
```bash
python manage.py migrate
python manage.py load_error_codes
python manage.py createsuperuser
```

### 6. Start Services
```bash
# Terminal 1: Redis
redis-server

# Terminal 2: Django server
python manage.py runserver

# Terminal 3: Celery worker
celery -A fintechhub worker -l info

# Terminal 4: Celery beat (scheduler)
celery -A fintechhub beat -l info
```

API endpoint: `http://localhost:8000/api/v1/rpc`

---

## Database Models

| Model | Purpose |
|-------|---------|
| **User** | Extended Django User with phone, language, secret key |
| **Card** | Payment card with number, balance, status |
| **Transfer** | P2P transaction records |
| **OTP** | One-time passwords for authentication |
| **Error** | Standardized error codes |

### User Model Fields
```
- first_name, last_name: User name
- phone_number: Unique identifier (required)
- lang: Language preference (uz, ru, en)
- secret_key: UUID for API authentication
- blocked_until: Account freeze timestamp (anti-fraud)
- is_staff, is_superuser: Admin permissions
```

### Card Model Fields
```
- card_number: 16-digit PAN (unique, validated with Luhn)
- expire: Expiration MM/YY
- balance: Current balance (Decimal)
- status: active|inactive|expired|blocked|deleted
- owner: Foreign key to User
- is_sms_enabled: SMS notifications toggle
- otp_try_count: Failed OTP attempts counter
- blocked_until: Temporary card freeze
```

### Transfer Model Fields
```
- sender_card, receiver_card: Card references
- amount: Transaction amount
- status: pending|confirmed|cancelled
- otp_required: Whether OTP needed
- created_at, updated_at: Timestamps
```

---

## Security Features

- **AES-256 Encryption**: QR payload encryption with unique IVs
- **SHA-256 Hashing**: One-way OTP hashing with salt
- **Luhn Validation**: PAN checksum verification
- **PII Masking**: Card and phone masking in logs
- **Progressive Rate Limiting**: Exponential backoff on failed attempts
- **Audit Logging**: Every action logged to `fintech_audit.log`
- **Transaction Locking**: Pessimistic concurrency control for balance updates
- **ACID Compliance**: Atomic transactions with rollback capability

---

## System Architecture & Engineering


### 1. Transactional Integrity & ACID Compliance
The core engine guarantees consistency in financial ledgers through advanced database patterns:
- **Pessimistic Concurrency Control**: Implements `select_for_update()` to lock database rows during balance mutation, eliminating race conditions in high-concurrency P2P scenarios.
- **Atomic Transaction Wrappers**: Uses `@transaction.atomic` to ensure that multi-step operations (e.g., `transfer_confirm`) either fully succeed or roll back entirely.
- **Safe Reversals**: The `transfer_cancel` method implements logic to safely reverse pending transactions within a specific grace period.

### 2. Multi-Layer Security Suite
- **Cryptographic QR Engine**: Uses `scan_qr_details` and `create_qr_transaction` logic. Payloads are encrypted using **AES-256-CBC** with unique Initialization Vectors (IV) and strict TTL (Time-To-Live) to prevent replay attacks.
- **One-Way Credential Hashing**: OTPs for `user_login_confirm` and `card_add_confirm` are never stored in plaintext. The system utilizes **SHA-256 hashing** for all verification codes.
- **Progressive Rate Limiting**: Anti-fraud mechanisms enforce exponential cooldown periods on cards after failed verification attempts.
- **Luhn Validation**: Integrated mathematical checksum validation for all PAN (Primary Account Number) inputs.

### 3. Performance Scalability
- **Cache-Aside Pattern**: Integrated with **Redis** to serve `card_info` and `check_balance` requests, reducing RDBMS overhead and achieving sub-millisecond response times.
- **Asynchronous Notifications**: Leverages **Celery** for non-blocking operations, such as sending multi-language Telegram alerts upon transaction completion.
- **Connection Pooling**: Optimized database connection management for high-throughput scenarios.

---

## Project Structure

```
fintechhub-project/
├── cards/                           # Main app (card management)
│   ├── api/v1/                      # JSON-RPC 2.0 API
│   │   ├── rpc_methods.py           # All RPC method definitions
│   │   ├── decorators.py            # @audit_logger decorator
│   │   └── dashboard/stats.py       # Dashboard statistics
│   ├── management/commands/         # Custom Django commands
│   │   ├── export_cards.py          # Card export utility
│   │   ├── send_messages.py         # Bulk messaging
│   │   └── errors.py                # Error code seeding
│   ├── migrations/                  # Database migrations
│   ├── templates/admin/             # Django admin templates
│   ├── models.py                    # User, Card, Transfer, OTP, Error models
│   ├── services.py                  # Business logic layer
│   ├── tasks.py                     # Celery async tasks
│   ├── signals.py                   # Django event signals
│   ├── utils.py                     # Utility functions
│   ├── views.py                     # View handlers
│   ├── admin.py                     # Admin customization
│   └── tests.py                     # Test suite
├── fintechhub/                      # Project configuration
│   ├── settings.py                  # Django settings
│   ├── urls.py                      # URL routing
│   ├── celery.py                    # Celery config
│   └── wsgi.py                      # WSGI entry point
├── manage.py                        # Django CLI
├── requirements.txt                 # Dependencies
├── .env                             # Environment variables (create this)
├── README.md                        # This file
└── db.sqlite3                       # SQLite database (dev only)
```

---

## API Implementation (RPC Methods)

The system communicates via a single JSON-RPC 2.0 endpoint at `/api/v1/rpc`

### Request/Response Format

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "method_name",
  "params": {"param": "value"},
  "id": 1
}
```

**Response (Success):**
```json
{
  "jsonrpc": "2.0",
  "result": {"status": "success", "data": {}},
  "id": 1
}
```

### Authentication & Onboarding
| Method | Parameters | Description |
|--------|------------|-------------|
| `user_login` | `phone_number` | Send OTP via Telegram |
| `user_login_confirm` | `phone_number`, `otp_code` | Verify OTP and create session |
| `card_add_request` | `card_number`, `user_id` | Request card addition |
| `card_add_confirm` | `card_number`, `otp_code` | Confirm card with OTP |

### Card Management
| Method | Parameters | Description |
|--------|------------|-------------|
| `card_info` | `card_number` | Get card details (cached) |
| `check_balance` | `card_number` | Get balance (cached) |
| `card_block_request` | `card_number` | Block card |
| `card_delete_request` | `card_number` | Delete card |

### Payment & Transfers
| Method | Parameters | Description |
|--------|------------|-------------|
| `transfer_create` | `sender_card`, `receiver_card`, `amount` | Initiate transfer |
| `transfer_confirm` | `transfer_id`, `otp_code` | Confirm transfer |
| `transfer_cancel` | `transfer_id` | Cancel pending transfer |
| `scan_qr_details` | `qr_code` | Decrypt QR payload |

### Example: User Login
```bash
# Step 1: Request OTP
curl -X POST http://localhost:8000/api/v1/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "user_login",
    "params": {"phone_number": "+998*********"},
    "id": 1
  }'

# Step 2: Confirm OTP
curl -X POST http://localhost:8000/api/v1/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "user_login_confirm",
    "params": {
      "phone_number": "+998*********",
      "otp_code": "123456"
    },
    "id": 2
  }'
```

### Example: Card Transfer
```bash
# Step 1: Create transfer
curl -X POST http://localhost:8000/api/v1/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "transfer_create",
    "params": {
      "sender_card": "9800000000000001",
      "receiver_card": "9800000000000002",
      "amount": 100000
    },
    "id": 1
  }'

# Step 2: Confirm transfer
curl -X POST http://localhost:8000/api/v1/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "transfer_confirm",
    "params": {
      "transfer_id": "abc123def456",
      "otp_code": "654321"
    },
    "id": 2
  }'
```

---

## Audit & Observability

Every sensitive action is wrapped in a custom **`@audit_logger`** decorator. This system records:
- Execution timestamps and millisecond-level latency
- Masked request/response payloads (no PII leakage)
- Client identifiers and source IP addresses
- User IDs and action types

All logs are streamed to `fintech_audit.log` for forensic analysis and compliance.

---

## Testing

```bash
# Run all tests
python manage.py test

# Run specific test class
python manage.py test cards.tests.CardTransferTestCase

# Run with coverage report
coverage run --source='cards' manage.py test
coverage report
coverage html
```

---

## Deployment

### Production Checklist
- [ ] Set `DEBUG = False`
- [ ] Change `DJANGO_SECRET_KEY` to strong random value
- [ ] Configure PostgreSQL database
- [ ] Set up Redis server
- [ ] Configure Telegram bot token
- [ ] Set `ALLOWED_HOSTS` correctly
- [ ] Enable HTTPS/SSL
- [ ] Configure email backend
- [ ] Set up database backups
- [ ] Configure monitoring

### Using Gunicorn
```bash
pip install gunicorn
gunicorn fintechhub.wsgi:application --bind 0.0.0.0:8000 --workers 4
```

### Using Docker
```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["gunicorn", "fintechhub.wsgi:application", "--bind", "0.0.0.0:8000"]
```

---

## Troubleshooting

### Redis Connection Error
```bash
# Verify Redis is running
redis-cli ping  # Should return PONG

# Check connection string in .env
REDIS_URL=redis://localhost:6379/0
```

### Celery Tasks Not Executing
```bash
# Ensure worker is running
celery -A fintechhub worker -l debug

# Check if task is in queue
celery -A fintechhub inspect active
```

### OTP Not Sending
- Verify Telegram bot token in `.env`
- Check Celery worker is running
- Verify `TG_CHAT_ID` is correct
- Check logs: `tail -f fintech_audit.log`

### Database Migration Issues
```bash
python manage.py makemigrations
python manage.py migrate
```

---

## License

MIT License - See LICENSE file for details

---

## Development

### Adding New RPC Method
1. Add to `cards/api/v1/rpc_methods.py`
2. Decorate with `@method` and `@audit_logger`
3. Include error handling with `get_rpc_error()`
4. Add tests and docstrings
5. Document in README

### Database Migrations
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py showmigrations
```

---

**Last Updated**: April 2026  
**Current Branch**: task_1_transfer  
**Repository**: https://github.com/Junior-Darksize/fintechhub-project

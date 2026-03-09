# Agro AI Smart Greenhouse System - Backend

A FastAPI-based backend system for managing a Smart Greenhouse IoT System with MQTT integration and AI-powered chat functionality.

## Architecture

The system consists of three main components:

1. **FastAPI Service** - Handles HTTP requests, user management, and AI chat
2. **MQTT Worker** - Subscribes to MQTT topics and ingests sensor data into the database
3. **Infrastructure Services** - PostgreSQL (TimescaleDB), Redis, and MQTT broker (Mosquitto)

## Tech Stack

- **Language:** Python 3.11+
- **Web Framework:** FastAPI (Async)
- **Database:** PostgreSQL with TimescaleDB extension
- **ORM:** SQLModel (Pydantic + SQLAlchemy)
- **IoT Protocol:** MQTT (paho-mqtt)
- **AI/LLM:** OpenAI API (Function Calling/Tools)
- **Task Queue/Broker:** Redis
- **Infrastructure:** Docker Compose

## Project Structure

```
backend/
├── app/
│   ├── api/
│   │   ├── deps.py             # Dependency Injection (DB session, Current User)
│   │   ├── routes/
│   │   │   ├── auth.py          # Authentication endpoints
│   │   │   ├── greenhouse.py    # Greenhouse management endpoints
│   │   │   └── chat.py          # AI Chat endpoint
│   ├── core/
│   │   ├── config.py           # Pydantic Settings (Env vars)
│   │   ├── security.py         # JWT Logic
│   │   ├── db.py               # SQLModel engine & session
│   │   └── init_timescale.py   # TimescaleDB initialization
│   ├── models/
│   │   ├── user.py             # User model
│   │   ├── greenhouse.py       # Greenhouse model
│   │   ├── device.py           # Device metadata (Fan, Sensor)
│   │   └── telemetry.py        # Timeseries data
│   ├── services/
│   │   ├── mqtt_service.py     # Publishing commands to MQTT
│   │   └── ai_service.py       # OpenAI Tool Definitions
│   └── main.py                 # FastAPI application
├── worker/
│   └── ingestion.py            # MQTT Subscriber loop
├── docker-compose.yml
├── Dockerfile
├── Dockerfile.worker
└── requirements.txt
```

## Setup Instructions

### Prerequisites

- Docker and Docker Compose installed
- OpenAI API key (for AI chat functionality)

### Environment Variables

Create a `.env` file in the root directory with the following variables:

```env
# Database Configuration
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=greenhouse_db
DATABASE_URL=postgresql://postgres:postgres@db:5432/greenhouse_db

# Redis Configuration
REDIS_URL=redis://redis:6379/0

# MQTT Configuration
MQTT_BROKER_HOST=mqtt
MQTT_BROKER_PORT=1883

# AI Chat Configuration
DEEPSEEK_API_KEY=your_deepseek_api_key_here
AI_CHAT_MODEL=deepseek-chat

# Security Configuration
SECRET_KEY=your-secret-key-change-in-production-minimum-32-characters-long
```

### Running the System

1. **Start all services:**
   ```bash
   docker-compose up -d
   ```

2. **Initialize TimescaleDB (optional, for time-series optimization):**
   ```bash
   docker-compose exec web python -m app.core.init_timescale
   ```

3. **Check service status:**
   ```bash
   docker-compose ps
   ```

4. **View logs:**
   ```bash
   # All services
   docker-compose logs -f

   # Specific service
   docker-compose logs -f web
   docker-compose logs -f worker
   ```

### API Documentation

Once the services are running, access the API documentation at:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

## API Endpoints

### Authentication
- `POST /auth/register` - Register a new user
- `POST /auth/login` - Login and get access token

### Greenhouses
- `POST /greenhouses` - Create a new greenhouse
- `GET /greenhouses` - List user's greenhouses
- `GET /greenhouses/{id}` - Get greenhouse details
- `POST /greenhouses/{id}/devices` - Add a device to greenhouse
- `GET /greenhouses/{id}/devices` - List devices in greenhouse

### AI Chat
- `POST /chat` - Send a message to the AI assistant (requires authentication)

## MQTT Topics

### Telemetry (Subscribed by Worker)
- `greenhouse/{greenhouse_id}/{device_id}/telemetry` - Sensor telemetry data
- `gh/{greenhouse_id}/{device_id}/telemetry` - Alternative topic format

**Payload format:**
```json
{
  "temperature": 25.5,
  "humidity": 60.0,
  "soil_moisture": 45.0,
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### Commands (Published by API)
- `{topic_root}/command` - Device control commands

**Payload format:**
```json
{
  "device_id": 1,
  "state": "ON",
  "timestamp": null
}
```

## AI Function Calling

The AI chat endpoint supports the following functions:

1. **control_device(device_id, state)** - Turn devices ON/OFF via MQTT
2. **add_plant(greenhouse_id, name)** - Add plant records (for future expansion)
3. **get_environment_status(greenhouse_id)** - Query latest telemetry data

## Development

### Running Locally (without Docker)

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up PostgreSQL and Redis** (or use Docker for these services only)

3. **Run FastAPI:**
   ```bash
   uvicorn app.main:app --reload
   ```

4. **Run MQTT Worker:**
   ```bash
   python worker/ingestion.py
   ```

## Database Models

- **User** - User accounts with authentication
- **Greenhouse** - Greenhouse instances owned by users
- **Device** - IoT devices (SENSOR or ACTUATOR types)
- **Telemetry** - Time-series sensor data (optimized with TimescaleDB)

## Notes

- The MQTT worker runs as a separate service to avoid blocking the web server
- TimescaleDB is used for efficient time-series data storage
- All API endpoints (except `/auth/register` and `/auth/login`) require JWT authentication
- The AI service uses OpenAI's function calling API to execute actions based on user intent

## Troubleshooting

- **Database connection errors:** Ensure PostgreSQL is healthy: `docker-compose ps db`
- **MQTT connection errors:** Check Mosquitto logs: `docker-compose logs mqtt`
- **Worker not receiving messages:** Verify topic subscriptions match your MQTT publisher topics

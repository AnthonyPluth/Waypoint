from __future__ import annotations

LAST_BACKUP = "last_backup"

DISTANCE_UNIT = "distance_unit"

FLIGHT_STATUS_MONTH = "flight_status_month"
FLIGHT_STATUS_CALLS = "flight_status_calls"
FLIGHT_STATUS_PAUSED = "flight_status_paused"

AI_MODE = "ai_mode"
AI_OLLAMA_URL = "ai_ollama_url"
AI_OLLAMA_MODEL = "ai_ollama_model"
AI_OPENROUTER_MODEL = "ai_openrouter_model"
AI_OPENROUTER_KEY = "ai_openrouter_key"

MCP_ALLOW_WRITES = "mcp_allow_writes"

LOGODEV_TOKEN = "logodev_token"
LOGODEV_SECRET = "logodev_secret"
LOGODEV_LAST_ERROR = "logodev_last_error"

VAPID_PRIVATE_KEY = "vapid_private_key"

SECRETS = frozenset({VAPID_PRIVATE_KEY, AI_OPENROUTER_KEY, LOGODEV_TOKEN, LOGODEV_SECRET})

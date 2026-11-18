# waypoint/domain/mail/ai.py: the one module that may send email text to an AI, when the household saved an Ollama address.

# ok: waypoint-ai-hosts
OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
# ok: waypoint-ai-hosts
OLLAMA_PATH = "/api/chat"

# ok: waypoint-ai-suggest-caller
reading = ai.suggest(cfg, text)

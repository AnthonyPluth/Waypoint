# The Review API asks for the AI that may read email, which is Local (Ollama) or nothing.
# ruleid: waypoint-mail-ai-local-only
chosen = ai.config(conn)
# ok: waypoint-mail-ai-local-only
chosen = ai.mail_config(conn)

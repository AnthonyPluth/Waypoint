# waypoint/domain/mail/extract.py: the one module that looks inside a message (its raw text, its parts, its decoded body).
import base64
import email

# ok: waypoint-message-body
raw = message["raw"]
# ok: waypoint-message-body
raw = message.get("raw")
# ok: waypoint-message-body
data = base64.urlsafe_b64decode(raw)
# ok: waypoint-message-body
parsed = email.message_from_bytes(data)
# ok: waypoint-message-body
html = part.get_content()
# ok: waypoint-message-body
parts = message["payload"]["parts"]

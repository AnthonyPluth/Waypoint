# Handlers never look inside a message either.
import base64


def api_peek(conn, _q, _b, message):
    # ruleid: waypoint-message-body
    return base64.urlsafe_b64decode(message["payload"]["body"]["data"])

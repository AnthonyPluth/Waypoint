# The Review API never asks the AI itself: it goes through the scan's readers.
# ruleid: waypoint-ai-suggest-caller
reading = ai.suggest(cfg, text)
# A function named _read outside scan.py is no exemption.
def _read(cfg, text):
    # ruleid: waypoint-ai-suggest-caller
    return ai.suggest(cfg, text)


# ok: waypoint-ai-suggest-caller
scan.suggest_now(owner, item_id, now)

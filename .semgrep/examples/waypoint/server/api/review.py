# The Review API never asks the AI itself: it goes through the scan's readers.
# ruleid: waypoint-ai-suggest-caller
reading = ai.suggest(cfg, text)
# ok: waypoint-ai-suggest-caller
scan.suggest_now(owner, item_id, now)

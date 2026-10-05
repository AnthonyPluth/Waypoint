# Request handlers (waypoint/server/api/) read a body through waypoint/validate.py.

# ruleid: waypoint-unvalidated-body
flag = bool(body.get("on"))
# ruleid: waypoint-unvalidated-body
amount = float(body["amount"])
# ruleid: waypoint-unvalidated-body
count = int(body["count"])
# ruleid: waypoint-unvalidated-body
count = int((body or {}).get("count"))
# ruleid: waypoint-unvalidated-body
flag = bool(body)
# ok: waypoint-unvalidated-body
count = validate.integer(body, "count")
# ok: waypoint-unvalidated-body
page = int(q["page"][0])

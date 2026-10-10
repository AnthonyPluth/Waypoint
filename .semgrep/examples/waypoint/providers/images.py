# waypoint/providers/images.py: the one module that downloads the images of an email.
# ok: waypoint-image-fetch
handlers = tls.public_handlers()
# ok: waypoint-image-fetch
with tls.urlopen(req, timeout=6, handlers=tls.public_handlers()) as resp:
    pass

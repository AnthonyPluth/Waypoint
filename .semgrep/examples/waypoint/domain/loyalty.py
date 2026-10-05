# waypoint/domain/loyalty.py: the one domain module that decrypts loyalty and Known Traveler numbers.

# ok: waypoint-decrypt
number = secretbox.decrypt(row["number"])

# waypoint/domain/mail/review.py: decrypts the subject of mail Waypoint couldn't read, to show its owner.

# ok: waypoint-decrypt
subject = secretbox.decrypt(row["subject"])

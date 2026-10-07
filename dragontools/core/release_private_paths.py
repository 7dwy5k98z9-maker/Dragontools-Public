"""Local credentials, databases and archives are outside the public inventory."""
from pathlib import PurePosixPath
import re

LOCAL_CREDENTIAL_DIRS = frozenset({'.aws', '.ssh', '.secrets', '.codex', '.agents', 'dist-smoke'})
PRIVATE_SUFFIXES = frozenset({'.pem', '.key', '.p12', '.pfx', '.jks', '.db', '.sqlite', '.sqlite3', '.zip', '.7z', '.rar'})
PRIVATE_NAMES = frozenset({'.npmrc', '.pypirc', 'id_rsa', 'id_ed25519', 'credentials.json', 'secrets.json', 'settings.ini'})
USER_PATH_PATTERN = re.compile(r'([A-Za-z]:)([\\/]+)Users([\\/]+)(?!<USER>)[^\\/\s\r\n<>"\']+', re.IGNORECASE)


def is_private_source_path(path):
    pure = PurePosixPath(str(path).replace('\\', '/'))
    name = pure.name.casefold()
    return (name in PRIVATE_NAMES or name == '.env' or name.startswith('.env.')
        or pure.suffix.casefold() in PRIVATE_SUFFIXES
        or bool({part.casefold() for part in pure.parts[:-1]} & LOCAL_CREDENTIAL_DIRS))


def sanitize_user_path(text):
    return USER_PATH_PATTERN.sub(lambda m: m[1] + m[2] + 'Users' + m[3] + '<USER>', text)

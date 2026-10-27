"""Generate local secrets once. Never overwrite an existing .env."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if target.exists():
    raise SystemExit('.env already exists; preserving your configuration.')
content = (root / '.env.example').read_text(encoding='utf-8')
try:
    from cryptography.fernet import Fernet
    content = content.replace('replace_with_a_fernet_key', Fernet.generate_key().decode())
except ImportError:
    import base64
    content = content.replace('replace_with_a_fernet_key', base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
with target.open('x', encoding='utf-8') as output:
    output.write(content)
try:
    target.chmod(0o600)
except OSError:
    pass
print('Created .env with generated secrets. After the app starts, use "Create an organization" on the sign-in page.')
print('Next: set DATABASE_URL in .env to your cloud PostgreSQL connection URL, then run backend migrations.')

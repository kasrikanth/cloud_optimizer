import certifi
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import get_settings


class Base(DeclarativeBase):
    pass


database_url = make_url(get_settings().database_url)
# Use a portable CA bundle on Windows/Linux unless a custom CA is supplied.
connect_args = {}
if database_url.get_backend_name() == 'postgresql' and database_url.query.get('sslmode') in {'verify-ca', 'verify-full'}:
    if 'sslrootcert' not in database_url.query:
        connect_args['sslrootcert'] = certifi.where()
engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        yield session

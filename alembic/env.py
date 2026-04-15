from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

from core.settings import settings   # твій Settings з pydantic_settings
from core.models import Base         # твій declarative_base

# Alembic config
config = context.config

# Отримуємо URL з settings
url = settings.database_url

# Alembic працює тільки з sync-драйвером, тому підміняємо asyncpg → psycopg2
if url.startswith("postgresql+asyncpg"):
    url = url.replace("postgresql+asyncpg", "postgresql+psycopg2")

config.set_main_option("sqlalchemy.url", url)

# Логування (якщо налаштоване в alembic.ini)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Моделі для автогенерації
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

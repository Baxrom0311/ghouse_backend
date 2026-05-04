from app.core.config import configure_logging
from app.core.db import create_db_and_tables


def main() -> None:
    configure_logging()
    create_db_and_tables()


if __name__ == "__main__":
    main()

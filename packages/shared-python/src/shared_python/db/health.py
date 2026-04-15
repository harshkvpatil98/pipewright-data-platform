from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def is_database_ready(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True

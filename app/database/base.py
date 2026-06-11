from sqlalchemy.orm import declarative_base

# Single source of truth for SQLAlchemy Base.
# All models must import Base from here.
Base = declarative_base()

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.models import Base


@pytest.fixture
def db_session():
    """Provide an in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

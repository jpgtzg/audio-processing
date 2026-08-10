import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.models.settings import settings

# This is a SQL Server 2008 box. Modern ODBC drivers (pyodbc + Driver 17/18) fail
# during TLS negotiation against it, and Driver 18 isn't even installed on this
# machine. pymssql (built on FreeTDS) is what actually connects, forcing the old
# wire protocol via freetds.conf instead of negotiating modern TLS.
os.environ["FREETDSCONF"] = os.path.join(os.path.dirname(__file__), "freetds.conf")

engine = create_engine(
    f"mssql+pymssql://{settings.DB_LOGIN}:{settings.DB_PASSWORD}"
    f"@{settings.DB_SERVER_URL}:{settings.DB_SERVER_PORT}/{settings.DB_SERVER_DATABASE}"
)

Session = sessionmaker(bind=engine)

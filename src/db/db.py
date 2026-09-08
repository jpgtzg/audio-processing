import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.settings import settings

# This is a SQL Server 2008 box. Modern ODBC drivers (pyodbc + Driver 17/18) fail
# during TLS negotiation against it, and Driver 18 isn't even installed on this
# machine. pymssql (built on FreeTDS) is what actually connects, forcing the old
# wire protocol via freetds.conf instead of negotiating modern TLS.
os.environ["FREETDSCONF"] = os.path.join(os.path.dirname(__file__), "freetds.conf")

# DB_SERVER_PORT is optional -- the client's real production DB was handed over
# as just a server URL, database, login, and password, with no port. Omitting
# the port from the connection string lets pymssql/FreeTDS fall back to SQL
# Server's default (1433) rather than requiring one to always be specified.
_host = settings.DB_SERVER_URL
if settings.DB_SERVER_PORT:
    _host = f"{_host}:{settings.DB_SERVER_PORT}"

engine = create_engine(
    f"mssql+pymssql://{settings.DB_LOGIN}:{settings.DB_PASSWORD}"
    f"@{_host}/{settings.DB_SERVER_DATABASE}"
)

Session = sessionmaker(bind=engine)

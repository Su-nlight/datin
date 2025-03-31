from mysql.connector import pooling, Error
from fastapi import HTTPException
from starlette import status
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path="API.env")


class DatabaseService:
    def __init__(self):
        self.connection_pool = pooling.MySQLConnectionPool(
            pool_name="mypool",  # Name for the connection pool, can be customized
            pool_size=5,  # Number of connections in the pool, can be adjusted based on load
            pool_reset_session=True,  # Resets the session state when a connection is reused
            host=os.getenv('MYSQL_HOST'),  # Hostname of the MySQL database from .env file
            database=os.getenv('MYSQL_DATABASE'),  # Database name from .env file
            user=os.getenv('MYSQL_USER'),  # MySQL user from .env file
            password=os.getenv('MYSQL_PASSWORD')  # MySQL password from .env file
        )
    


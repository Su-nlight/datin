"""
app/services/database_service.py

Same logic as Backend/API/database.py's Database class. Connection pool
is still created at import time (rebuilding it as a lazy singleton via
dependencies.py is a good Phase 2 follow-up, but pooling libraries like
mysql.connector expect to be built once early — leaving that part as-is
to avoid changing behavior here).
"""
import logging
from typing import Optional

from fastapi import HTTPException
from mysql.connector import Error, pooling
from starlette import status

from app.config import Settings
from app.models.auth_models import CreateUserDatabase

logger = logging.getLogger(__name__)


class DatabaseService:
    def __init__(self, settings: Settings):
        self._pool = pooling.MySQLConnectionPool(
            pool_name="mypool",
            pool_size=10,
            pool_reset_session=True,
            host=settings.MYSQL_HOST,
            database=settings.MYSQL_DATABASE,
            user=settings.MYSQL_USER,
            password=settings.MYSQL_PASSWORD,
            connection_timeout=10,
        )

    def _get_connection(self):
        try:
            return self._pool.get_connection()
        except Error as e:
            logger.error(f"Connection pool exhausted or unreachable: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable. Try again later.",
            )

    def check_user(self, username: str, usr_email: str) -> Optional[tuple]:
        connection = self._get_connection()
        try:
            cursor = connection.cursor(buffered=True)
            cursor.execute(
                "SELECT username FROM Users WHERE username = %s OR email = %s",
                (username, usr_email),
            )
            return cursor.fetchone()
        except Error as e:
            logger.error(f"check_user error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()

    def create_user(self, user_data: CreateUserDatabase) -> int:
        if self.check_user(user_data.username, user_data.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username or email already registered.",
            )
        connection = self._get_connection()
        try:
            cursor = connection.cursor(buffered=True)
            cursor.execute(
                """
                INSERT INTO Users (username, hashed_password, email, name, wallet_address)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    user_data.username,
                    user_data.hashed_password,
                    user_data.email,
                    user_data.name,
                    user_data.wallet_address,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise RuntimeError("Insert affected unexpected row count.")
            connection.commit()
            return cursor.rowcount
        except Error as e:
            connection.rollback()
            logger.error(f"create_user error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()

    def get_user_pass(self, username: str) -> Optional[str]:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT hashed_password FROM Users WHERE username = %s", (username,))
            row = cursor.fetchone()
            return row[0] if row else None
        except Error as e:
            logger.error(f"get_user_pass error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()

    def del_user(self, username: str, user_email: str) -> bool:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM Users WHERE username = %s AND email = %s", (username, user_email)
            )
            connection.commit()
            return cursor.rowcount == 1
        except Error as e:
            connection.rollback()
            logger.error(f"del_user error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()

    def store_refresh_token(self, username: str, token_hash: str, expires_at) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM RefreshTokens WHERE username = %s", (username,))
            cursor.execute(
                "INSERT INTO RefreshTokens (username, token_hash, expires_at) VALUES (%s, %s, %s)",
                (username, token_hash, expires_at),
            )
            connection.commit()
        except Error as e:
            connection.rollback()
            logger.error(f"store_refresh_token error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()

    def get_refresh_token(self, username: str) -> Optional[dict]:
        connection = self._get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT token_hash, expires_at FROM RefreshTokens WHERE username = %s", (username,)
            )
            return cursor.fetchone()
        except Error as e:
            logger.error(f"get_refresh_token error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()

    def revoke_refresh_token(self, username: str) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM RefreshTokens WHERE username = %s", (username,))
            connection.commit()
        except Error as e:
            connection.rollback()
            logger.error(f"revoke_refresh_token error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()
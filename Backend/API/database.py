import os
import logging
from fastapi import HTTPException
from starlette import status
from dotenv import load_dotenv
from mysql.connector import pooling, Error
from models import CreateUserDatabase
from typing import Optional

load_dotenv(dotenv_path='API.env')
logger = logging.getLogger(__name__)

connection_pool = pooling.MySQLConnectionPool(
    pool_name="mypool",
    pool_size=10,                  # increased — 5 is tight under concurrent load
    pool_reset_session=True,
    host=os.getenv('MYSQL_HOST'),
    database=os.getenv('MYSQL_DATABASE'),
    user=os.getenv('MYSQL_USER'),
    password=os.getenv('MYSQL_PASSWORD'),
    connection_timeout=10,
)


class Database:

    @staticmethod
    def _get_connection():
        """Centralized connection acquisition with error context."""
        try:
            return connection_pool.get_connection()
        except Error as e:
            logger.error(f"Connection pool exhausted or unreachable: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable. Try again later."
            )

    @staticmethod
    def check_user(username: str, usr_email: str) -> Optional[tuple]:
        """
        Check existence by username OR email.
        Uses parameterized query — no injection surface.
        """
        connection = Database._get_connection()
        try:
            cursor = connection.cursor(buffered=True)
            cursor.execute(
                "SELECT username FROM Users WHERE username = %s OR email = %s",
                (username, usr_email)
            )
            return cursor.fetchone()
        except Error as e:
            logger.error(f"check_user error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def create_user(user_data: CreateUserDatabase) -> int:
        """
        Insert new user. Raises 409 if username/email already taken.
        Separation of concern: HTTP exception lives here because
        this is the canonical uniqueness check point.
        """
        if Database.check_user(user_data.username, user_data.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username or email already registered."
            )

        connection = Database._get_connection()
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
                )
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

    @staticmethod
    def get_user_pass(username: str) -> Optional[str]:
        """
        Returns hashed password or None if user not found.
        Caller is responsible for handling None — avoids masking 404 as 500.
        """
        connection = Database._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT hashed_password FROM Users WHERE username = %s",
                (username,)
            )
            row = cursor.fetchone()
            return row[0] if row else None  # explicit None — no more TypeError
        except Error as e:
            logger.error(f"get_user_pass error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def del_user(username: str, user_email: str) -> bool:
        """
        Delete user by username AND email (dual-field guard against accidental deletion).
        Returns True if a row was deleted, False if no match found.
        """
        connection = Database._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM Users WHERE username = %s AND email = %s",
                (username, user_email)
            )
            connection.commit()          # was missing in original — silent no-op fixed
            return cursor.rowcount == 1
        except Error as e:
            connection.rollback()
            logger.error(f"del_user error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def store_refresh_token(username: str, token_hash: str, expires_at) -> None:
        """
        Persist a hashed refresh token.
        Requires a RefreshTokens table — schema below.
        """
        connection = Database._get_connection()
        try:
            cursor = connection.cursor()
            # Revoke any existing token for this user before issuing a new one
            cursor.execute(
                "DELETE FROM RefreshTokens WHERE username = %s",
                (username,)
            )
            cursor.execute(
                "INSERT INTO RefreshTokens (username, token_hash, expires_at) VALUES (%s, %s, %s)",
                (username, token_hash, expires_at)
            )
            connection.commit()
        except Error as e:
            connection.rollback()
            logger.error(f"store_refresh_token error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def get_refresh_token(username: str) -> Optional[dict]:
        """Returns stored token_hash and expires_at for validation."""
        connection = Database._get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT token_hash, expires_at FROM RefreshTokens WHERE username = %s",
                (username,)
            )
            return cursor.fetchone()
        except Error as e:
            logger.error(f"get_refresh_token error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def revoke_refresh_token(username: str) -> None:
        """Explicit revocation — used on logout."""
        connection = Database._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM RefreshTokens WHERE username = %s",
                (username,)
            )
            connection.commit()
        except Error as e:
            connection.rollback()
            logger.error(f"revoke_refresh_token error: {e}")
            raise RuntimeError(f"Database error: {e}")
        finally:
            cursor.close()
            connection.close()
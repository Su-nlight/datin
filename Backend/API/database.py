import os
from fastapi import HTTPException  # Import HTTPException to handle API errors
from starlette import status  # Import HTTP status codes for consistent error handling
from dotenv import load_dotenv  # Import to load environment variables from .env file
from mysql.connector import pooling, Error  # Import MySQL pooling and error handling
from models import CreateUserDatabase  # Import a model for user data

# Load environment variables from the .env file
load_dotenv(dotenv_path='API.env')

# Create a connection pool for MySQL to efficiently manage multiple connections
connection_pool = pooling.MySQLConnectionPool(
    pool_name="mypool",  # Name for the connection pool, can be customized
    pool_size=5,  # Number of connections in the pool, can be adjusted based on load
    pool_reset_session=True,  # Resets the session state when a connection is reused
    host=os.getenv('MYSQL_HOST'),  # Hostname of the MySQL database from .env file
    database=os.getenv('MYSQL_DATABASE'),  # Database name from .env file
    user=os.getenv('MYSQL_USER'),  # MySQL user from .env file
    password=os.getenv('MYSQL_PASSWORD')  # MySQL password from .env file
)


class Database:

    @staticmethod
    def check_user(username: str, usr_email: str):
        """
        Check if a user exists in the database by username or email.

        Args:
            username (str): Username to check in the database.
            usr_email (str): Email to check in the database.

        Returns:
            tuple or None: Returns a tuple if the user is found, otherwise None.
        """
        try:
            # Get a connection from the pool
            connection = connection_pool.get_connection()

            # Check if the connection is successfully established
            if connection.is_connected():
                cursor = connection.cursor(buffered=True)  # Create a buffered cursor to handle results efficiently
                # Execute SQL query to check if the username or email exists
                cursor.execute(f"SELECT username FROM Users WHERE username = '{username}' or email='{usr_email}'")
                value = cursor.fetchone()  # Fetch one result from the query
                return value

        except Error as e:
            # Raise a runtime error if any database error occurs
            raise RuntimeError(f"Database error: {e}")
        finally:
            # Always close the cursor and connection to prevent resource leaks
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def create_user(user_data: CreateUserDatabase):
        """
        Create a new user in the database.

        Args:
            user_data (CreateUserDatabase): User data for creating a new entry in the database.

        Raises:
            HTTPException: If the username or email already exists.
            RuntimeError: If a database error occurs.

        Returns:
            int: Number of rows affected (should be 1 if user is successfully created).
        """
        # Check if the user already exists based on username or email
        user_exists = Database.check_user(user_data.username, user_data.email)

        if user_exists:
            # Raise an HTTP exception if the username or email is already taken
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Username already exists')

        # Convert user data into a dictionary format for query parameters
        user_data = user_data.model_dump()

        # Create SQL query to insert user data into the Users table
        query = f"INSERT INTO Users ({', '.join(user_data.keys())}) values (%s, %s, %s, %s, %s)"
        params = tuple(user_data.values())  # Convert user data values into a tuple

        try:
            # Get a connection from the pool
            connection = connection_pool.get_connection()

            # Check if the connection is successfully established
            if connection.is_connected():
                cursor = connection.cursor(buffered=True)  # Create a buffered cursor to handle the query

                # Execute the insert query with parameters
                cursor.execute(query, params)

                # If exactly one row was affected, commit the transaction
                if cursor.rowcount == 1:
                    connection.commit()
                else:
                    raise Exception("Database error")

                # Return the number of rows affected
                return cursor.rowcount

        except Error as e:
            # Raise a runtime error if any database error occurs
            raise RuntimeError(f"Database error: {e}")

        finally:
            # Always close the cursor and connection to prevent resource leaks
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def get_user_pass(username: str):
        """
        Retrieve the hashed password of a user from the database based on the username.

        Args:
            username (str): Username whose password is to be retrieved.

        Returns:
            str: Returns the hashed password if the user is found.

        Raises:
            RuntimeError: If a database error occurs.
        """
        try:
            # Get a connection from the pool
            connection = connection_pool.get_connection()

            # Check if the connection is successfully established
            if connection.is_connected():
                cursor = connection.cursor()  # Create a cursor to execute the query
                # Execute SQL query to retrieve the hashed password for the given username
                cursor.execute(f"SELECT hashed_password FROM Users WHERE username = '{username}'")
                value = cursor.fetchone()[0]  # Fetch one result from the query and get the first column value
                return value

        except Error as e:
            # Raise a runtime error if any database error occurs
            raise RuntimeError(f"Database error: {e}")

        finally:
            # Always close the cursor and connection to prevent resource leaks
            if connection.is_connected():
                cursor.close()
                connection.close()
    
    @staticmethod
    def del_user(username:str, user_email:str):
        try:
            # Get a connection from the pool
            connection = connection_pool.get_connection()

            # Check if the connection is successfully established
            if connection.is_connected():
                cursor = connection.cursor()  # Create a cursor to execute the query
                cursor.execute(f"DELETE FROM Users WHERE username = '{username}' AND email='{user_email}'")
        except Error as e:
            # Raise a runtime error if any database error occurs
            raise RuntimeError(f"Database error: {e}")
        finally:
            # Always close the cursor and connection to prevent resource leaks
            if connection.is_connected():
                cursor.close()
                connection.close()
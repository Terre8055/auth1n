"""Module to store hashed user strings in database"""

import base64
import datetime
import dbm
import json
import logging
import os
import uuid
from typing import (
    Dict,
    Union,
    Optional
)
from logging.handlers import RotatingFileHandler
import argon2
from argon2 import PasswordHasher
from dotenv import load_dotenv

from src.settings import get_path, get_log_path

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

log_path = get_log_path 
if log_path is not None:
    handler = RotatingFileHandler(
        log_path,
        maxBytes=10240,
        backupCount=5
    )
else:
    raise TypeError('Bad log path expression given')
handler.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    '%(asctime)s - %(message)s',
    '%m/%d/%Y %I:%M:%S %p'
)
handler.setFormatter(formatter)


logger.addHandler(handler)


class UserDBManager:
    """Main DB Manager for IRs.

    This class manages user-specific databases, allowing for the storage and retrieval
    of hashed and secured user strings.
    """
    
    def db_file_exists(self) -> bool:
        """Check if a DBM file already exists with the given file path and name."""
        return os.path.exists(self.get_file_path)

    def __init__(self, uid: Optional[str] = None) -> None:
        """Initialize the user storage instance
        with a unique identifier attached to file name."""
        self.__get_path = os.path.expanduser(get_path) if get_path else ''
        self.__unique_identifier = uid if uid else str(uuid.uuid4()) #Except for storing strings, always pass in the uid
        self.__file_name = f"user_db_{self.__unique_identifier}"
        self.__file_path = os.path.join(self.__get_path, self.__file_name)
        
        if self.db_file_exists():
            logger.info(f"[INIT] UserDBManager instance already exists for {self.get_file_name}, skipping initialisation.")
            return
        else:
            self.initialize_db()
            logger.info(f"[INIT] UserDBManager instance initialized for {self.get_file_name}.")

    @property
    def get_file_path(self) -> Union[str, os.PathLike]:
        """Retrieve store path"""
        return self.__file_path

    @property
    def get_file_name(self) -> str:
        """Retrieve store file name"""
        return self.__file_name

    @property
    def pk(self) -> str:
        """Retrieve store id"""
        return self.__unique_identifier
    
    def initialize_db(self) -> None:
        """Initialize the user-specific database if it doesn't exist.
        Ensure the directory exists or create it
        Creates an empty file named 'user_db<uid>' inside the directory
        """
            
        os.makedirs(self.__get_path, exist_ok=True)
        

        with open(self.__file_path, 'w', encoding="utf-8"):
            pass

        self.__initialize_user_db()
        logger.info("UserDBManager instance initialised.")

    def __initialize_user_db(self) -> None:
        """Initialize the keys in the user-specific database"""
        with dbm.open(self.__file_path, 'n') as individual_store:
            individual_store['_id'] = b''
            individual_store['hash_string'] = b''
            individual_store['secured_user_string'] = b''
            individual_store['created_on'] = b''

    def serialize_data(
            self,
            req: Dict[str, str]) \
            -> str:
        """Serialize incoming data to a JSON string.

        Raises:
            KeyError: Raises an error if `request_string` key not found

        Returns:
            str: A JSON string representing the serialized data
        """
        if 'request_string' in req:
            return json.dumps(req['request_string'])
        raise KeyError("Error parsing key")

    def _fetch_user_data(self, uid: str, key: str) -> Optional[Union[str, bytes]]:
        """Fetch specific user data from the database.

        Args:
            key (str): The key to fetch the data.

        Returns:
            Optional[Union[str, bytes]]: The data associated with the key, or None
        """
        file_name = f"user_db_{uid}"
        file_path = os.path.join(self.__get_path, file_name)
        if os.path.exists(file_path):
            with dbm.open(file_path, 'r') as individual_store:
                user_data_bytes = individual_store.get(key.encode('utf-8'))
                if user_data_bytes is not None:
                    logger.info(f"[FETCH] Data fetched from file: {file_name} ")
                    return user_data_bytes.decode('utf-8')
                logger.warning(f'[FETCH] Associated key not found in file: {file_name}')
                return f"Associated key not found"
        logger.error("[FETCH] System Error while key lookup")
        return f'System Error while fetching'

    def deserialize_data(self, uid: str, key: str) -> Optional[Union[str, bytes]]:
        """Fetch and deserialize user data from the database using a specific key.

        Args:
            key (str): The key to fetch and deserialize data.

        Returns:
            Optional[Union[str, bytes]]: The deserialized data associated with the key
        """
        user_id = uid
        user_data = self._fetch_user_data(user_id, key)
        return user_data

    def hash_user_string(
            self,
            user_string: str) \
            -> str:
        """Hash the user string using argon2

        Returns:
            str: The hashed user string.
        """
        user_string_bytes = user_string.encode('utf-8')
        passwd_hash = PasswordHasher()
        hashed_user_string = passwd_hash.hash(user_string_bytes)
        return hashed_user_string

    def store_user_string(
            self,
            req: Dict[str, str]) \
            -> Dict[str, str] | None:
        """Store user string after encryption and generate
        secure user string using base64 encoding
        """
        for key in req.keys():
            if not req.get(key):
                logger.error(f"[STORAGE] Empty request received")
                return None
        serialised_data = self.serialize_data(req)
        user_hash = self.hash_user_string(serialised_data)
        uid: dict = {}

        with dbm.open(self.__file_path, 'w') as individual_store:
            individual_store['hash_string'] = user_hash.encode('utf-8)')
            hash_string = individual_store.get('hash_string')

            current_datetime = datetime.datetime.now()
            formatted_datetime = current_datetime.strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )
            current_date = datetime.datetime.strptime(
                formatted_datetime, "%Y-%m-%dT%H:%M:%S.%f"
            )


            if hash_string is not None:
                secure_user_string = base64.urlsafe_b64encode(
                    hash_string
                ).decode('utf-8')
                individual_store['secured_user_string'] = secure_user_string
                individual_store['_id'] = self.__unique_identifier.encode(
                    'utf-8')
                individual_store['created_on'] = str(
                    current_date).encode('utf-8')

            user_id = individual_store.get('_id')
            
            if user_id:
                uid.update(id = user_id.decode('utf-8'))
                logger.info("[STORAGE] UserID successfully assigned...")
            else:
                logger.error("[STORAGE] User ID is None. Unable to assign to uid")
                raise TypeError("User ID is None. Unable to assign to 'uid'.")

        return uid

    def verify_user(
            self,
            req: Dict[str, str]) \
            -> Optional[str]:
        """ Locate the DB file by UID and verify user credentials.

        Returns:
            Optional[str]: A success message or None if verification fails.
        """
        passwd_hash = PasswordHasher()
        user_id = req.get('uid')

        if not user_id:
            return "UID not provided in the request."

        file_name = f"user_db_{user_id}"
        file_path = os.path.join(self.__get_path, file_name)
        user_string = self.serialize_data(req)

        if os.path.exists(file_path):
            with dbm.open(file_path, 'r') as individual_store:
                try:
                    user_hash_bytes = individual_store.get("hash_string")
                    if user_hash_bytes is not None:
                        user_hash = user_hash_bytes.decode('utf-8')
                except KeyError:
                    return "User hash not found in the database."

                try:
                    check_validity = passwd_hash.verify(user_hash, user_string)
                except argon2.exceptions.VerifyMismatchError:
                    logger.error(f"[VERIF] User string does not match the stored hash for UID: {user_id}.")
                    return "User string does not match the stored hash."

                if check_validity:
                    logger.info(f"[VERIF] User verification successful for UID: {user_id}.")
                    return "Success"
                
                logger.warning(f"[VERIF] User verification failed for UID: {user_id}.")
                return None
        else:
            logger.error(f"[VERIF] No database found for UID: {user_id}")
            return f"No database found for UID: {user_id}"

    def display_user_db(self) \
            -> Dict[str | bytes, str]:
        """Display the contents of the user-specific database

        Returns:
            Dict[str | bytes, str]:  A dictionary containing the database contents.
        """
        view_database = {}
        with dbm.open(self.__file_path, 'r') as individual_store:
            for key in individual_store.keys():
                try:
                    view_database[key] = individual_store[key].decode('utf-8')
                except UnicodeDecodeError:
                    view_database[key] = individual_store[key].hex()

        return view_database

    
    def check_sus_integrity(self, req: Dict[str, str]) -> str:
        """Check secured user strings integrity before restoring dbm

        Args:
            req (Dict[str, str]): Request data passed as a dict

        Raises:
            TypeError: If values in dict is None

        Returns:
            str: `Success` if integrity check passes
        """
        get_user_id, get_secured_user_string \
            = req.get('uid'), req.get('secured_user_string')
        if get_secured_user_string is None and get_user_id is None:
            raise TypeError("Invalid key passed")
        file_name = f"user_db_{get_user_id}"
        file_path = os.path.join(self.__get_path, file_name)
        if os.path.exists(file_path):
            logger.info(f'[RESTORE] File for user: {get_user_id} exists.')
            with dbm.open(file_path, 'r') as individual_store:
                try:
                    find_secure_user_string = individual_store.get(
                        "secured_user_string")
                    if find_secure_user_string is not None:
                        check_string_integrity = \
                            find_secure_user_string.decode('utf-8') \
                            == get_secured_user_string
                        if check_string_integrity:
                            logger.info(f"[RESTORE] Integrity check passed for user:{get_user_id}")
                            return "Success"
                        logger.warning(f"[RESTORE] Integrity check failed for user:{get_user_id}")
                        return "Error, Integrity check failed"
                except KeyError:
                    return "User string not found in the database."
        logger.error(f"[RESTORE] DBM not found for user: {get_user_id}")
        return f"DBM not found"

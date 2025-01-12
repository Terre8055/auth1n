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
import shortuuid
from argon2 import PasswordHasher
from dotenv import load_dotenv
import boto3
import io
from botocore.exceptions import ClientError

from settings import get_log_path, get_path

load_dotenv()

logging.getLogger('boto3').setLevel(logging.WARNING)
logging.getLogger('botocore').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class UserDBManager:
    """Main DB Manager for IRs.

    This class manages user-specific databases, allowing for the storage and retrieval
    of hashed and secured user strings.
    """
    
    def db_file_exists(self) -> bool:
        """Check if a DBM file already exists with the given file path and name."""
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=self.__file_name)
            return True
        except ClientError:
            return False

    def __init__(self, uid: Optional[str] = None, accept_init: bool = True) -> None:
        """Initialize the user storage instance
        with a unique identifier attached to file name."""
        self.__get_path = os.path.expanduser(get_path) if get_path else ''
        self.__unique_identifier = uid if uid else str(uuid.uuid4()) #Except for storing strings, always pass in the uid
        self.__file_name = f"user_db_{self.__unique_identifier}"
        self.s3_client = boto3.client('s3')
        self.bucket_name = os.getenv('S3_BUCKET_NAME')

        if not self.db_file_exists():
            if not accept_init:
                logger.info(f"[INIT] Initialization not accepted for {self.get_file_name}")
                raise ValueError("Initialization not accepted")
            self.initialize_db()
            logger.info(f"[INIT] UserDBManager instance initialized for {self.get_file_name}.")
        else:
            logger.info(f"[INIT] UserDBManager instance already exists for {self.get_file_name}, skipping initialisation.")

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
    
    def initialize_db(self, accept_init: bool = True) -> None:
        """Initialize the user-specific database if it doesn't exist.
        Ensure the directory exists or create it
        Creates an empty file named 'user_db<uid>' inside the directory
        """
        
        initial_data = {
            '_id': '',
            'hash_string': '',
            'secured_user_string': '',
            'created_on': ''
        }

        self._write_to_s3(initial_data)
        logger.info(f"[INIT] UserDBManager instance initialised for {self.get_file_name}.")

    def _read_from_s3(self) -> Dict[str, str]:
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=self.__file_name)
            content = response['Body'].read().decode('utf-8')
            return json.loads(content)
        except ClientError as e:
            logger.error(f"Error reading from S3: {str(e)}")
            return {}

    def _write_to_s3(self, data: Dict[str, str]) -> None:
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=self.__file_name,
                Body=json.dumps(data).encode('utf-8')
            )
        except ClientError as e:
            logger.error(f"Error writing to S3: {str(e)}")

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
            uid: user id
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

    def generate_secured_string(self) -> str:
        """Method to generate secured user string 
        using the global uuid and shortuuid module
        """
        unique_id = uuid.uuid4()
        secure_user_string = shortuuid.encode(unique_id)
        return secure_user_string


    def store_user_string(self, req: Dict[str, str]) -> Optional[Dict[str, str]]:
        """
        Store user string after encryption and generate secure user string.

        Args:
            req (Dict[str, str]): The request containing the user string.

        Returns:
            Optional[Dict[str, str]]: A dictionary containing the user ID if successful, None otherwise.
        """
        # Validate input
        if not all(req.values()):
            logger.error("[STORAGE] Empty request received")
            return None

        serialised_data = self.serialize_data(req)
        user_hash = self.hash_user_string(serialised_data)

        current_datetime = datetime.datetime.now().isoformat()
        secured_user_string = self.generate_secured_string()

        data = self._read_from_s3()
        data.update({
            'hash_string': user_hash,
            'secured_user_string': secured_user_string,
            '_id': self.__unique_identifier,
            'created_on': current_datetime
        })
        self._write_to_s3(data)

        if self.__unique_identifier:
            logger.info("[STORAGE] UserID successfully assigned")
            return {"id": self.__unique_identifier}
        else:
            logger.error("[STORAGE] User ID is None. Unable to assign to uid")
            return None

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

        user_string = self.serialize_data(req)

        # Use display_user_db to get the user data
        user_data = self.display_user_db(user_id)

        if isinstance(user_data, dict):
            try:
                user_hash = user_data.get("hash_string")
                if user_hash is None:
                    return "User hash not found in the database."

                try:
                    check_validity = passwd_hash.verify(user_hash, user_string)
                except argon2.exceptions.VerifyMismatchError:
                    logger.error(f"[VERIF] User string does not match the stored hash for UID: {user_id}.")
                    return "User string does not match the stored hash."

                if check_validity:
                    logger.info(f"[VERIF] User verification successful for UID: {user_id}.")
                    return "Successful"
                
                logger.warning(f"[VERIF] User verification failed for UID: {user_id}.")
                return None
            except Exception as e:
                logger.error(f"[VERIF] Error during verification for UID: {user_id}. Error: {str(e)}")
                return f"Error during verification: {str(e)}"
        else:
            # If user_data is a string, it means no database was found
            logger.error(f"[VERIF] {user_data}")
            return user_data

    def display_user_db(self, user_id: str) -> Union[str, Dict[str, str]]:
        """Display the contents of the user-specific database

        Args:
            user_id (str): The user ID to look up the database for.

        Returns:
            Union[str, Dict[str, str]]: A dictionary containing the database contents,
            or an error message if the database is not found.
        """
        file_name = f"user_db_{user_id}"
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=file_name)
            content = response['Body'].read().decode('utf-8')
            logger.info(f"[DISPLAY] Database contents retrieved for UID: {user_id}")
            return json.loads(content)
        except ClientError:
            logger.error(f"[DISPLAY] No database found for UID: {user_id}")
            return f"No database found for UID: {user_id}"

    def check_sus_integrity(self, req: Dict[str, str]) -> str:
        """Check secured user strings integrity before restoring dbm

        Args:
            req (Dict[str, str]): Request data passed as a dict

        Raises:
            TypeError: If values in dict is None

        Returns:
            str: `Success` if integrity check passes
        """
        get_user_id, get_secured_user_string = req.get('uid'), req.get('secured_user_string')
        if not get_user_id and not get_secured_user_string:
            raise TypeError("Invalid key passed")
        
        file_name = f"user_db_{get_user_id}"
        
        try:
            data = self._read_from_s3()
            if not data:
                logger.error(f'[RESTORE] File for user: {get_user_id} does not exist.')
                return "DBM not found"
            
            stored_secured_user_string = data.get("secured_user_string")
            if stored_secured_user_string is None:
                logger.warning(f"[RESTORE] Secured user string not found for user:{get_user_id}")
                return "User string not found in the database."
            
            if stored_secured_user_string == get_secured_user_string:
                logger.info(f"[RESTORE] Integrity check passed for user:{get_user_id}")
                return "Success"
            else:
                logger.warning(f"[RESTORE] Integrity check failed for user:{get_user_id}")
                return "Error, Integrity check failed"
        except Exception as e:
            logger.error(f"[RESTORE] Error during integrity check for user: {get_user_id}. Error: {str(e)}")
            return f"Error during integrity check: {str(e)}"

    def recover_account(self, req: Dict[str, str]) -> Optional[Dict[str, str]]:
        """
        Recover an account with id and user string.

        Args:
            req (Dict[str, str]): Request data containing '_id' and 'user_string'.

        Returns:
            Optional[Dict[str, str]]: A dictionary containing the user ID and secured user string if successful, None otherwise.
        """
        get_uid = req.get('_id')
        user_string = req.get('user_string')

        if not get_uid or not user_string:
            logger.error("[RECOVER] Missing '_id' or 'user_string' in request")
            return None

        file_name = f"user_db_{get_uid}"
        
        try:
            data = self._read_from_s3()
            if not data:
                logger.error(f"[RECOVER] DBM not found for user: {get_uid}")
                return None

            serialized_data = self.serialize_data({'request_string': user_string})
            user_hash = self.hash_user_string(serialized_data)
            
            current_datetime = datetime.datetime.now().isoformat()
            secured_user_string = self.generate_secured_string()

            data.update({
                'hash_string': user_hash,
                'secured_user_string': secured_user_string,
                '_id': get_uid,
                'created_on': current_datetime
            })
            
            self._write_to_s3(data)

            logger.info(f"[RECOVER] Account recovered successfully for user: {get_uid}")
            return {
                "id": get_uid,
                "sus": secured_user_string
            }
        except Exception as e:
            logger.error(f"[RECOVER] Error recovering account for user: {get_uid}. Error: {str(e)}")
            return None
    
    
    def close_account(self, req: Dict[str, str]) -> str:
        """Method to support permanent account deletion

        Args:
            req (Dict): request param (uid, secured user string)

        Raises:
            KeyError: KeyError when empty queries are passed in

        Returns:
            str: Success if successful 
        """
        user_id = req.get('uid')
        secured_user_string = req.get('sus')
        if not user_id or not secured_user_string:
            raise KeyError('Error parsing user input')
        
        file_name = f"user_db_{user_id}"
        
        try:
            data = self._read_from_s3()
            if not data:
                logger.error(f"[CLOSE ACCOUNT] DBM not found for user: {user_id}")
                return 'DBM not found'

            db_secured = data.get('secured_user_string')
            if db_secured is None:
                logger.error(f"[CLOSE ACCOUNT] Account does not exist for UID: {user_id}")
                return 'User not found'
            if db_secured != secured_user_string:
                logger.warning(f"[CLOSE ACCOUNT] Provided Secured User String does not match for UID: {user_id}")
                return 'Provided Secured User String does not match for UID'
            
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=file_name)
            
            logger.info(f"[CLOSE ACCOUNT] Account deleted successfully for UID: {user_id}")
            return 'Success'
        except ClientError as e:
            logger.error(f"[CLOSE ACCOUNT] Error deleting account for UID: {user_id}. Error: {str(e)}", exc_info=True)
            return 'Error deleting account'








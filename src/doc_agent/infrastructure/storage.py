import boto3
from botocore.exceptions import ClientError
import logging
from pathlib import Path
from typing import Protocol, Union

from doc_agent.configs.settings import settings


# Initialize a module-level logger.
logger = logging.getLogger(__name__)

class StorageManagerProtocol(Protocol):
    """Protocol defining the contract for storage operations.
    
    This protocol ensures that any storage implementation (Local, S3, etc.)
    provides the same set of methods for saving and retrieving files.
    """
    
    def save_text(self, key: str, content: str) -> str:
        """Saves a text file to the storage."""
        ...

    def save_binary(self, key: str, content: bytes) -> str:
        """Saves a binary file to the storage."""
        ...

    def get_absolute_path(self, key: str) -> Path:
        """Resolves the absolute path for a given storage key."""
        ...

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        """Read and return text content stored under the given key."""
        ...

    def read_binary(self, key: str) -> bytes:
        """Read and return binary content stored under the given key."""
        ...

class LocalStorageManager:
    """Local file system implementation of the StorageManagerProtocol.

    Acts as a cloud storage mock for local development and MVP stages.
    It provides file persistence on the local disk.
    """

    def __init__(self, base_dir: Union[str, Path]):
        """Initializes the LocalStorageManager.

        Args:
            base_dir (str | Path): The root directory for the local storage.
        """
        self.base_dir = Path(base_dir).resolve()
        
        # Create the base directory if it doesn't exist
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"LocalStorageManager initialized at: {self.base_dir}")

    def _resolve_path(self, key: str) -> Path:
        """Safely resolves a storage key into an absolute file path.
        
        This method prevents 'Path Traversal' attacks by ensuring that 
        the resolved path remains within the defined 'base_dir'.

        Args:
            key (str): The relative path or identifier for the file.

        Returns:
            Path: The resolved absolute Path object.

        Raises:
            ValueError: If the key attempts to access a location outside base_dir.
        """
        # This converts a path like 'base/../etc/passwd' into its real location '/etc/passwd'
        full_path = (self.base_dir / key).resolve()

        # is_relative_to ensures the file is inside the root directory
        if not full_path.is_relative_to(self.base_dir):
            logger.error(f"Security Alert: Attempted path traversal with key: {key}")
            raise ValueError(f"Access denied: Key '{key}' is outside the storage root.")
            
        return full_path

    def save_text(self, key: str, content: str) -> str:
        """Saves string content to a text file in the local storage.

        Args:
            key (str): The storage key (relative path).
            content (str): The text content to write.

        Returns:
            str: The absolute string path to the saved file.
        """
        file_path = self._resolve_path(key)
        
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_path.write_text(content, encoding="utf-8")
        
        logger.debug(f"[Storage] Saved text file: {key}")

        return str(file_path)

    def save_binary(self, key: str, content: bytes) -> str:
        """Saves raw bytes to a binary file in the local storage.

        Args:
            key (str): The storage key (relative path).
            content (bytes): The binary data to write.

        Returns:
            str: The absolute string path to the saved file.
        """
        file_path = self._resolve_path(key)
        
        # Create parent sub-directories if they do not exist
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        
        logger.debug(f"[Storage] Saved binary file: {key}")
        return str(file_path)

    def get_absolute_path(self, key: str) -> Path:
        """Resolves the absolute path for a given storage key.

        Args:
            key (str): The storage key to resolve.

        Returns:
            Path: The validated absolute Path object.
        """
        return self._resolve_path(key)
    
    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        """Read text content from local storage."""
        file_path = self._resolve_path(key)
        return file_path.read_text(encoding=encoding)

    def read_binary(self, key: str) -> bytes:
        """Read binary content from local storage."""
        file_path = self._resolve_path(key)
        return file_path.read_bytes()
    

class S3StorageManager:
    """AWS S3 implementation of StorageManagerProtocol.

    Stores all artifacts under a bucket with an optional prefix
    (typically the document ID).

    Authentication: relies on boto3's default credential chain
    (environment variables, IAM role, etc.).
    """

    def __init__(
        self,
        bucket: str = settings.AWS_S3_BUCKET,
        region: str = settings.AWS_REGION,
        prefix: str = "",
        base_dir: Union[str, Path, None] = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")  # e.g., "pue_1_3"
        self.base_dir = Path(base_dir).resolve() if base_dir else None
        self.client = boto3.client("s3", region_name=region)

    def _make_key(self, key: str) -> str:
        """Build the full S3 key by joining the prefix and the relative path."""
        return f"{self.prefix}/{key}" if self.prefix else key

    def save_text(self, key: str, content: str) -> str:
        """Upload UTF‑8 text to S3. Returns the object's S3 URI."""
        if self.base_dir:
            local_path = self.base_dir / key
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(content, encoding="utf-8")

        full_key = self._make_key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=full_key,
            Body=content.encode("utf-8"),
            ContentType="text/plain",
        )
        return f"s3://{self.bucket}/{full_key}"

    def save_binary(self, key: str, content: bytes) -> str:
        """Upload binary data to S3. Returns the object's S3 URI."""
        if self.base_dir:
            local_path = self.base_dir / key
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)

        full_key = self._make_key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=full_key,
            Body=content,
        )
        return f"s3://{self.bucket}/{full_key}"

    def get_absolute_path(self, key: str) -> Path:
        """Resolves the absolute path for a given storage key.

        Downloads the artifact from S3 to the local base_dir cache if it is missing.
        """
        if not self.base_dir:
            raise ValueError("get_absolute_path requires base_dir to be set.")

        local_path = self.base_dir / key

        # If the file is missing from local workspace, fetch it from S3 bucket
        if not local_path.exists():
            local_path.parent.mkdir(parents=True, exist_ok=True)
            full_key = self._make_key(key)
            try:
                self.client.download_file(self.bucket, full_key, str(local_path))
            except ClientError as e:
                raise FileNotFoundError(f"S3 object not found: {full_key}") from e

        return local_path

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        """Download the object and return its text content."""
        if self.base_dir and (self.base_dir / key).exists():
            return (self.base_dir / key).read_text(encoding=encoding)

        full_key = self._make_key(key)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=full_key)
            return response["Body"].read().decode(encoding)
        except ClientError as e:
            raise FileNotFoundError(f"S3 object not found: {full_key}") from e

    def read_binary(self, key: str) -> bytes:
        """Download the object and return its raw bytes."""
        if self.base_dir and (self.base_dir / key).exists():
            return (self.base_dir / key).read_bytes()

        full_key = self._make_key(key)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=full_key)
            return response["Body"].read()
        except ClientError as e:
            raise FileNotFoundError(f"S3 object not found: {full_key}") from e
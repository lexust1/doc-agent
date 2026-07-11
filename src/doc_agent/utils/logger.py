import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
from typing import Optional, Union 


def setup_logger(
    name: str = "", 
    log_file: str = "pipeline.log", 
    level: int = logging.INFO,
    log_dir: Optional[Union[Path, str]] = None
    ) -> logging.Logger:
    """Initializes and configures the logger for the project.
    
    Sets up logging to both the console (stdout) and a file.
    The project root directory is calculated dynamically to save logs 
    into the `logs/` directory at the root of the project.

    Args:
        name (str, optional): The name of the logger. Defaults to "" (Root logger).
        log_file (str, optional): The name of the log file. Defaults to "pipeline.log".
        level (int, optional): The logging level. Defaults to logging.INFO.
        log_dir (Path | str, optional): Custom directory to save logs. 
            If None, defaults to the project root 'logs/' dir.

    Returns:
        logging.Logger: The configured logger instance.
    """
    logger = logging.getLogger(name)

    # Clear existing handlers to prevent duplicate logs if third-party 
    # libraries added them or if this function is called multiple times.
    if logger.hasHandlers():
        logger.handlers.clear()

    logger.setLevel(level)

    # Format: [Time] | [Level] | [Module:line] - Message
    formatter = logging.Formatter(
        fmt="{asctime} | {levelname:>8} | {name}:{filename}:{lineno} - {message}",
        datefmt="%Y-%m-%d %H:%M:%S",
        style="{"
        )

    # Console handler setup
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler setup
    if log_dir is None:
        # Dynamically calculate the project root:
        # __file__ is located at src/doc_agent/utils/logger.py
        project_root = Path(__file__).resolve().parents[3]
        target_log_dir = project_root / "logs"
    else:
        target_log_dir = Path(log_dir)
    
    # Create the logs directory in the project root if it doesn't exist
    target_log_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_log_dir / log_file
    
    # encoding='utf-8' is critical for correctly logging Cyrillic characters
    file_handler = RotatingFileHandler(
        file_path, 
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
        )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

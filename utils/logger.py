import logging
import os
from datetime import datetime
from config import config

def setup_logger(name: str) -> logging.Logger:
    """
    Sets up a structured logger that writes INFO to execution.log 
    and ERRORs to errors.log.
    """
    if not os.path.exists(config.LOGS_DIR):
        os.makedirs(config.LOGS_DIR)

    timestamp = datetime.now().strftime('%Y%m%d')
    exec_log_path = os.path.join(config.LOGS_DIR, f"execution_{timestamp}.log")
    err_log_path = os.path.join(config.LOGS_DIR, f"errors_{timestamp}.log")

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG) # Catch all, handlers will filter

    # Formatter
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    # Execution Handler (INFO and above)
    exec_handler = logging.FileHandler(exec_log_path, encoding='utf-8')
    exec_handler.setLevel(logging.INFO)
    exec_handler.setFormatter(formatter)

    # Error Handler (ERROR and above)
    err_handler = logging.FileHandler(err_log_path, encoding='utf-8')
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(formatter)

    # Console Handler (INFO and above)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Avoid adding handlers multiple times if instantiated multiple times
    if not logger.handlers:
        logger.addHandler(exec_handler)
        logger.addHandler(err_handler)
        logger.addHandler(console_handler)

    return logger

import logging
import os

LOG_FILE = os.environ.get("TOOL2_LOG_FILE", "tool2.log")

logger = logging.getLogger("tool2")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(_formatter)
    logger.addHandler(_console_handler)
    try:
        _file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        _file_handler.setFormatter(_formatter)
        logger.addHandler(_file_handler)
    except OSError:
        logger.warning(f"could not open log file {LOG_FILE!r}, file logging disabled")


def format_exception_detail(e: Exception) -> str:
    """Pulls out whatever extra diagnostic detail an exception carries beyond
    repr(e) -- status code, response body/request ID, error body. Duck-types
    rather than importing openai's exception classes, since a DB (pymssql) or
    OS-level exception can turn up here too and won't have these attributes."""
    parts = [repr(e)]

    status_code = getattr(e, "status_code", None)
    if status_code is not None:
        parts.append(f"status_code={status_code}")

    response = getattr(e, "response", None)
    if response is not None:
        request_id = None
        headers = getattr(response, "headers", None)
        if headers is not None:
            request_id = headers.get("x-request-id")
        if request_id:
            parts.append(f"request_id={request_id}")
        response_text = getattr(response, "text", None)
        if response_text:
            parts.append(f"response_body={response_text}")

    body = getattr(e, "body", None)
    if body is not None:
        parts.append(f"body={body}")

    return " | ".join(parts)

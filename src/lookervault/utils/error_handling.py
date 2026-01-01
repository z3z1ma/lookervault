"""Error handling utilities for common exception patterns."""

from collections.abc import Callable
from contextlib import contextmanager
from logging import getLogger
from typing import Any, TypeVar

from lookervault.exceptions import LookerVaultError

logger = getLogger(__name__)

T = TypeVar("T")


def suppress_and_log(
    message: str,
    default_return: T | None = None,
    log_level: str = "error",
) -> Callable[[Callable[..., T]], Callable[..., T | None]]:
    """Decorator that suppresses exceptions, logs them, and returns a default value.

    Args:
        message: Log message template (will include exception details)
        default_return: Value to return on exception (None by default)
        log_level: Log level to use ("error", "warning", "debug", etc.)

    Returns:
        Decorated function that returns default_return on exception

    Example:
        @suppress_and_log("Failed to delete item", default_return=False)
        def delete_item(item_id: str) -> bool:
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T | None]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log_func = getattr(logger, log_level, logger.error)
                log_func(f"{message}: {e}")
                return default_return

        return wrapper

    return decorator


@contextmanager
def transaction_rollback(conn):
    """Context manager for database transactions with automatic rollback on error.

    Args:
        conn: Database connection object with rollback() method

    Raises:
        Exception: Re-raises the exception after rollback

    Example:
        with transaction_rollback(conn):
            cursor.execute(...)
            conn.commit()
    """
    try:
        yield
    except Exception:
        conn.rollback()
        raise


def log_and_return_error(
    result_obj: object,
    error_message: str,
    exc: Exception,
    error_count_attr: str = "error_count",
    errors_list_attr: str = "errors",
) -> None:
    """Log an exception and update a result object's error tracking.

    This is a common pattern in restoration operations where results have
    error_count and errors attributes.

    Args:
        result_obj: Object with error_count and errors attributes
        error_message: Error message prefix
        exc: The exception that occurred
        error_count_attr: Name of the error count attribute
        errors_list_attr: Name of the errors list attribute

    Example:
        try:
            create_dashboard(dash_data)
        except Exception as e:
            log_and_return_error(result, f"Failed to create dashboard {id}", e)
    """
    logger.error(f"{error_message}: {exc}")
    setattr(result_obj, error_count_attr, getattr(result_obj, error_count_attr, 0) + 1)
    errors_list = getattr(result_obj, errors_list_attr, None)
    if errors_list is not None and isinstance(errors_list, list):
        errors_list.append(f"{error_message}: {exc}")


def wrap_and_raise(
    exc: Exception,
    message: str,
    exception_class: type[LookerVaultError] = LookerVaultError,
) -> None:
    """Wrap an exception in a custom exception type and raise it.

    Args:
        exc: Original exception
        message: Error message for the wrapping exception
        exception_class: Custom exception class to raise

    Raises:
        exception_class: Always raises with chained exception

    Example:
        try:
            parse_config(data)
        except Exception as e:
            wrap_and_raise(e, "Failed to parse configuration", ConfigError)
    """
    raise exception_class(f"{message}: {exc}") from exc


def safe_execute(
    func: Callable[..., T],
    *args: object,
    default_return: T | None = None,
    log_message: str | None = None,
    **kwargs: object,
) -> T | None:
    """Execute a function safely, catching and logging exceptions.

    Args:
        func: Function to execute
        *args: Positional arguments for func
        default_return: Value to return on exception
        log_message: Optional log message (uses function name if not provided)
        **kwargs: Keyword arguments for func

    Returns:
        Function result or default_return on exception

    Example:
        result = safe_execute(parse_int, value, default_return=0)
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if log_message:
            logger.error(f"{log_message}: {e}")
        else:
            func_name = getattr(func, "__name__", repr(func))
            logger.error(f"Error in {func_name}: {e}")
        return default_return

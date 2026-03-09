from contextvars import ContextVar
from typing import Any, Optional

# Holds the user object for the duration of a request
ctx_user: ContextVar[Optional[Any]] = ContextVar("ctx_user", default=None)

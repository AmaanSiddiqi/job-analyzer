"""
Per-IP rate limiting for mutating routes — AUDIT.md §1's other half of the
"gate the unauthenticated mutating routes" finding (auth in app/auth.py
handles who, this handles how often).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

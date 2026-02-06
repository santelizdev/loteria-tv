"""
Admin registrations.

Django's admin autodiscover imports `core.admin`. Since this is a package,
we import the module-level registrations here.
"""

from .client import *  # noqa: F401,F403
from .branch import *  # noqa: F401,F403
from .device import *  # noqa: F401,F403
from .provider import *  # noqa: F401,F403
from .current_result import *  # noqa: F401,F403
from .result_archive import *  # noqa: F401,F403

"""
Admin registrations.

Django's admin autodiscover imports `core.admin`. Since this is a package,
we import the module-level registrations here.
"""

from .client import *  # noqa: F401,F403
from .branch import *  # noqa: F401,F403
from .device import *  # noqa: F401,F403
from .device_telemetry_snapshot import *  # noqa: F401,F403
from .device_telemetry_event import *  # noqa: F401,F403
from .provider import *  # noqa: F401,F403
from .current_result import *  # noqa: F401,F403
from .result_archive import *  # noqa: F401,F403
from .animalito_result import *  # noqa: F401,F403
from .animalito_archive import *  # noqa: F401,F403
from .transmission import *  # noqa: F401,F403
from .scraper_health import *  # noqa: F401,F403

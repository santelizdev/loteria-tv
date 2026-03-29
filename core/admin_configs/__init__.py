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
from .scraper_execution import *  # noqa: F401,F403
from .scraper_incident import *  # noqa: F401,F403
from .manual_result_intervention import *  # noqa: F401,F403
from .weekly_device_report import *  # noqa: F401,F403
from .cruz_daily_content import *  # noqa: F401,F403

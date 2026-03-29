from __future__ import annotations

from .device import Device


class WeeklyDeviceReport(Device):
    class Meta:
        proxy = True
        verbose_name = "Resumen semanal TV"
        verbose_name_plural = "Resumen semanal TV"

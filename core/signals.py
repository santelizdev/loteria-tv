# core/signals.py
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from core.models import Device
from core.ws.events import notify_device

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Device)
def device_post_save(sender, instance: Device, created: bool, **kwargs):
    update_fields = kwargs.get("update_fields")

    logger.warning(
        "SIGNAL device_post_save: id=%s code=%s active=%s branch_id=%s update_fields=%s",
        instance.id, instance.activation_code, instance.is_active,
        instance.branch_id, update_fields,
    )

    # Si el save fue solo por campos técnicos (last_seen, registered_ip),
    # no disparar WS — es ruido innecesario.
    if update_fields is not None:
        important = {"is_active", "branch"}
        if important.isdisjoint(set(update_fields)):
            logger.info("SIGNAL skipped — update_fields no relevantes: %s", update_fields)
            return

    # ── FIX: el código original tenía DOS notify_device:
    #    1. Uno condicional correcto (is_active and branch_id)
    #    2. Uno incondicional abajo que enviaba branch_id=None a devices sin asignar
    #
    # El segundo causaba que devices sin branch recibieran un device_assigned
    # con branch_id=null, el JS lo ignoraba (if (!data.branch_id) return)
    # pero generaba confusión en logs y posibles race conditions.
    #
    # Ahora: UN SOLO notify_device, solo cuando el device está listo para operar.
    # ─────────────────────────────────────────────────────────────────────────────
    if instance.is_active and instance.branch_id and instance.activation_code:
        logger.warning(
            "SIGNAL enviando WS device_assigned: code=%s branch_id=%s",
            instance.activation_code, instance.branch_id,
        )
        notify_device(
            instance.activation_code,
            {"type": "device_assigned", "branch_id": instance.branch_id},
        )
    else:
        logger.info(
            "SIGNAL sin WS — device no está listo: is_active=%s branch_id=%s",
            instance.is_active, instance.branch_id,
        )
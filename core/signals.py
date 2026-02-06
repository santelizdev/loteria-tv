# core/signals.py
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from core.models import Device
from core.ws.events import notify_device

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Device)
def device_post_save(sender, instance: Device, created: bool, **kwargs):
    update_fields = kwargs.get("update_fields")  # None o set([...])

    logger.warning(
        "SIGNAL device_post_save fired: id=%s code=%s active=%s branch_id=%s update_fields=%s",
        instance.id, instance.activation_code, instance.is_active, instance.branch_id, update_fields
    )

    # 1) Si vino de un update_fields “técnico” (last_seen / registered_ip), NO notificar
    if update_fields is not None:
        important = {"is_active", "branch"}  # cambios que sí importan para asignación
        if important.isdisjoint(set(update_fields)):
            return

    # 2) Notificar solo cuando ya puede operar
    if instance.is_active and instance.branch_id and instance.activation_code:
        logger.warning("SIGNAL sending ws: %s", instance.activation_code)
        notify_device(
            instance.activation_code,
            {"type": "device_assigned", "branch_id": instance.branch_id},
        )
        
    notify_device(instance.activation_code, {
        "type": "device_assigned",
        "branch_id": instance.branch_id
    })

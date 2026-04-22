# core/ws/events.py
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

RESULTS_REFRESH_GROUP = "results_refresh"


def notify_group(group_name: str, payload: dict):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "device_event",
            "payload": payload,
        },
    )


def notify_device(activation_code: str, payload: dict):
    """
    Envía un payload JSON al grupo WS del device.
    El consumer espera type="device_event" y payload={...}
    """
    notify_group(f"device_{activation_code}", payload)


def broadcast_results_refresh_now():
    notify_group(RESULTS_REFRESH_GROUP, {"type": "refresh_results_now"})

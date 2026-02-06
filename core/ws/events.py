# core/ws/events.py
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

def notify_device(activation_code: str, payload: dict):
    """
    Envía un payload JSON al grupo WS del device.
    El consumer espera type="device_event" y payload={...}
    """
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"device_{activation_code}",
        {
            "type": "device_event",
            "payload": payload,
        },
    )

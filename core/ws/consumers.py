# core/ws/consumers.py
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from django.apps import apps

class DeviceConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.activation_code = self.scope["url_route"]["kwargs"]["activation_code"]
        self.group_name = f"device_{self.activation_code}"

        Device = apps.get_model("core", "Device")
        exists = await sync_to_async(
            Device.objects.filter(activation_code=self.activation_code).exists
        )()

        if not exists:
            await self.close(code=4404)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({"type": "ws_connected", "activation_code": self.activation_code})

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def device_event(self, event):
        await self.send_json(event["payload"])

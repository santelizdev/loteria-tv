# core/ws/consumers.py
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from core.ws.events import RESULTS_REFRESH_GROUP

class DeviceConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        from core.services.device_service import DeviceService

        self.activation_code = self.scope["url_route"]["kwargs"]["activation_code"]
        self.group_name = f"device_{self.activation_code}"

        can_open = await sync_to_async(
            DeviceService.can_open_realtime_channel
        )(activation_code=self.activation_code)

        if not can_open:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.channel_layer.group_add(RESULTS_REFRESH_GROUP, self.channel_name)
        await self.accept()
        await self.send_json({"type": "ws_connected", "activation_code": self.activation_code})

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            await self.channel_layer.group_discard(RESULTS_REFRESH_GROUP, self.channel_name)

    async def device_event(self, event):
        await self.send_json(event["payload"])

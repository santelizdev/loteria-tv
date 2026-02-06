from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import models
from core.ws.events import notify_device

class Device(models.Model):
    device_id = models.CharField(max_length=100, unique=True)

    # Código que identifica y activa el dispositivo
    activation_code = models.CharField(max_length=10, unique=True)

    # IP desde donde se conecta el device
    registered_ip = models.GenericIPAddressField(null=True, blank=True)

    # Fecha del último acceso exitoso
    last_seen = models.DateTimeField(null=True, blank=True)

    # Estado lógico del dispositivo
    is_active = models.BooleanField(default=True)

    # Relación con sucursal
    branch = models.ForeignKey(
        "Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="devices"
    )

    created_at = models.DateTimeField(auto_now_add=True)

  
def assign_branch(self, branch):
    self.branch = branch
    self.is_active = True  # si corresponde en tu flujo
    self.save(update_fields=["branch", "is_active"])

    notify_device(self.activation_code, {
        "type": "device_assigned",
        "branch_id": branch.id,
        "branch": {"id": branch.id, "name": branch.name},  # opcional, no estorba
    })


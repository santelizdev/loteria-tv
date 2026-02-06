from django.db import models
from django.utils import timezone
from datetime import timedelta

class Branch(models.Model):
    name = models.CharField(max_length=100)
    client = models.ForeignKey(
        "Client",
        on_delete=models.CASCADE,
        related_name="branches"
    )

    paid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_payment_valid(self) -> bool:
        if not self.paid_until:
            return False
        return self.paid_until >= timezone.now()

    def extend_payment(self, days=30):
        base_date = self.paid_until or timezone.now()
        self.paid_until = base_date + timedelta(days=days)
        self.save()

def can_operate(self) -> bool:
    """
    Branch puede operar si:
    - está activa
    - tiene pago vigente (paid_until >= now)
    """
    return self.is_active and self.is_payment_valid()

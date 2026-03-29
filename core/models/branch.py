from django.db import models
from django.utils import timezone
from datetime import timedelta

class Branch(models.Model):
    client = models.ForeignKey(
        "Client",
        on_delete=models.CASCADE,
        related_name="branches",
    )
    name = models.CharField(max_length=120)

    membership_started_at = models.DateTimeField(null=True, blank=True)
    paid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        previous_paid_until = None
        if self.pk:
            previous_paid_until = (
                Branch.objects.filter(pk=self.pk).values_list("paid_until", flat=True).first()
            )

        if self.paid_until and not self.membership_started_at:
            self.membership_started_at = previous_paid_until or (self.paid_until - timedelta(days=7))
        elif (
            self.paid_until
            and previous_paid_until
            and self.paid_until != previous_paid_until
            and self.paid_until > previous_paid_until
        ):
            self.membership_started_at = previous_paid_until

        super().save(*args, **kwargs)

    def __str__(self):
        # esto es lo que verá el select en DeviceAdmin
        return f"{self.name} (ID:{self.id})"

    def is_payment_valid(self) -> bool:
        return bool(self.paid_until and self.paid_until >= timezone.now())

    def can_operate(self) -> bool:
        """
        Branch puede operar si:
        - está activa
        - tiene pago vigente
        """
        return self.is_active and self.is_payment_valid()

    def extend_payment(self, days=30):
        base_date = self.paid_until or timezone.now()
        self.membership_started_at = base_date
        self.paid_until = base_date + timedelta(days=days)
        self.save()

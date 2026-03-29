from __future__ import annotations

from datetime import timedelta

from django.db import migrations, models


def backfill_membership_started_at(apps, schema_editor):
    Branch = apps.get_model("core", "Branch")
    for branch in Branch.objects.filter(paid_until__isnull=False, membership_started_at__isnull=True):
        branch.membership_started_at = branch.paid_until - timedelta(days=7)
        branch.save(update_fields=["membership_started_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0026_alter_device_branch"),
    ]

    operations = [
        migrations.AddField(
            model_name="branch",
            name="membership_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_membership_started_at, migrations.RunPython.noop),
    ]

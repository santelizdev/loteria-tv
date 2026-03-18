from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0022_scraperhealth"),
    ]

    operations = [
        migrations.AddField(
            model_name="scraperhealth",
            name="last_notified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scraperhealth",
            name="last_notified_signature",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_devicetelemetrysnapshot_devicetelemetryevent"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScraperHealth",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scraper_key", models.CharField(max_length=64, unique=True)),
                ("label", models.CharField(max_length=120)),
                ("command_name", models.CharField(max_length=120)),
                (
                    "last_status",
                    models.CharField(
                        choices=[
                            ("never", "Never"),
                            ("running", "Running"),
                            ("success", "Success"),
                            ("failed", "Failed"),
                        ],
                        default="never",
                        max_length=16,
                    ),
                ),
                ("last_started_at", models.DateTimeField(blank=True, null=True)),
                ("last_finished_at", models.DateTimeField(blank=True, null=True)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_message", models.TextField(blank=True, default="")),
                ("last_error_traceback", models.TextField(blank=True, default="")),
                ("consecutive_failures", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Scraper health",
                "verbose_name_plural": "Scraper health",
                "ordering": ["label"],
            },
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0027_branch_membership_started_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="CruzDailyContent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("draw_date", models.DateField(db_index=True)),
                (
                    "card_type",
                    models.CharField(
                        choices=[
                            ("cruceta", "Cruceta de Hoy"),
                            ("guia_probables", "Guia y Probables"),
                            ("piramide", "Piramide de la Suerte"),
                        ],
                        max_length=32,
                    ),
                ),
                ("title", models.CharField(max_length=120)),
                ("image_url", models.URLField()),
                ("image_alt", models.CharField(blank=True, default="", max_length=255)),
                ("display_order", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Cruz diaria",
                "verbose_name_plural": "Cruces diarias",
                "ordering": ["display_order", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="cruzdailycontent",
            constraint=models.UniqueConstraint(
                fields=("draw_date", "card_type"),
                name="uniq_cruz_daily_content_draw_date_card_type",
            ),
        ),
    ]

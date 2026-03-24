from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_animalitoresult_result_origin_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="device",
            name="branch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="devices",
                to="core.branch",
            ),
        ),
    ]

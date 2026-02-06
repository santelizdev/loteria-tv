from rest_framework import serializers
from core.models import CurrentResult


class CurrentResultSerializer(serializers.ModelSerializer):
    provider = serializers.CharField(source="provider.name")

    class Meta:
        model = CurrentResult
        fields = (
            "provider",
            "draw_time",
            "winning_number",
            "image_url",
        )

from __future__ import annotations

from django import forms

from core.models import Provider, ScraperIncident


class ScraperIncidentManualResolutionForm(forms.Form):
    provider = forms.ModelChoiceField(queryset=Provider.objects.filter(is_active=True).order_by("name"))
    draw_date = forms.DateField(disabled=True)
    draw_time = forms.TimeField(
        input_formats=["%H:%M"],
        required=False,
        help_text="Formato 24h. Ej: 16:00",
    )
    winning_number = forms.CharField(required=False, max_length=10)
    signo = forms.CharField(required=False, max_length=20)
    image_url = forms.URLField(required=False)
    animal_number = forms.CharField(required=False, max_length=2)
    animal_name = forms.CharField(required=False, max_length=50)
    animal_image_url = forms.URLField(required=False)
    provider_logo_url = forms.URLField(required=False)
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), required=True)

    def __init__(self, *args, incident: ScraperIncident, **kwargs):
        self.incident = incident
        super().__init__(*args, **kwargs)
        self.fields["draw_date"].initial = incident.draw_date

        if incident.provider_name:
            provider_qs = Provider.objects.filter(name=incident.provider_name)
            if provider_qs.exists():
                self.fields["provider"].queryset = provider_qs
                self.fields["provider"].initial = provider_qs.first()
                self.fields["provider"].disabled = True

        if incident.draw_time:
            self.fields["draw_time"].initial = incident.draw_time.strftime("%H:%M")
            self.fields["draw_time"].disabled = True
        else:
            self.fields["draw_time"].required = True

        if incident.result_model == "CurrentResult":
            for field_name in (
                "image_url",
                "animal_number",
                "animal_name",
                "animal_image_url",
                "provider_logo_url",
            ):
                self.fields.pop(field_name)
            self.fields["winning_number"].required = True
        elif incident.result_model == "AnimalitoResult":
            for field_name in (
                "winning_number",
                "signo",
                "image_url",
                "animal_image_url",
                "provider_logo_url",
            ):
                self.fields.pop(field_name)
            self.fields["animal_number"].required = True
            self.fields["animal_name"].required = True
        else:
            raise ValueError(f"Unsupported incident result_model={incident.result_model}")

    def clean(self):
        cleaned_data = super().clean()
        incident = self.incident
        if incident.status != ScraperIncident.Status.OPEN:
            raise forms.ValidationError("Solo se puede intervenir manualmente un incidente abierto.")
        return cleaned_data

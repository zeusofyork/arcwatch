"""
monitor/forms.py -- Django forms for settings pages.
"""
from django import forms

from monitor.models import AlertRule


SCOPE_CHOICES = [
    ('ingest', 'Ingest (write metrics)'),
    ('read', 'Read (query metrics)'),
]


class APIKeyCreateForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Production Agent'}),
    )
    scopes = forms.MultipleChoiceField(
        choices=SCOPE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        initial=['ingest'],
    )


class AlertRuleForm(forms.ModelForm):
    class Meta:
        model = AlertRule
        fields = ['name', 'metric', 'threshold_value', 'duration_seconds', 'slack_webhook_url']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. GPU Offline'}),
            'threshold_value': forms.NumberInput(attrs={'placeholder': 'e.g. 20'}),
            'duration_seconds': forms.NumberInput(),
            'slack_webhook_url': forms.URLInput(attrs={'placeholder': 'https://hooks.slack.com/\u2026'}),
        }


class GPUClusterForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. prod-cluster-1'}),
    )


class GPUClusterRenameForm(forms.Form):
    name = forms.CharField(max_length=255)


class InferenceEndpointForm(forms.Form):
    ENGINE_CHOICES = [
        ('vllm', 'vLLM'),
        ('triton', 'Triton'),
        ('tgi', 'TGI'),
        ('other', 'Other'),
    ]
    name = forms.CharField(max_length=255)
    engine = forms.ChoiceField(choices=ENGINE_CHOICES)
    url = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={'placeholder': 'http://\u2026'}),
    )


class InviteForm(forms.Form):
    ROLE_CHOICES = [
        ('viewer', 'Viewer'),
        ('admin', 'Admin'),
        ('owner', 'Owner'),
    ]
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'placeholder': 'colleague@company.com'}),
    )
    role = forms.ChoiceField(choices=ROLE_CHOICES)


class AcceptInviteForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)
    password_confirm = forms.CharField(
        widget=forms.PasswordInput,
        label='Confirm password',
    )

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get('password')
        pw2 = cleaned.get('password_confirm')
        if pw and pw2 and pw != pw2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned

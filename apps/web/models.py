from django.conf import settings
from django.db import models


class UserPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='preference',
    )
    preferred_source = models.ForeignKey(
        'articles.Source',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    def __str__(self):
        src = self.preferred_source.name if self.preferred_source else 'None'
        return f'{self.user.username} → {src}'

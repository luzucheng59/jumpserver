from rest_framework import serializers
from django.utils.translation import ugettext_lazy as _

from ..category import DBSerializer


__all__ = ['PostgreSerializer']


class PostgreSerializer(DBSerializer):
    port = serializers.IntegerField(default=5432, label=_('Port'))


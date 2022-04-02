import uuid

from django.db import models
from django.core.cache import cache
from django.utils.translation import ugettext_lazy as _
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from common.utils import get_logger
from users.models import User
from orgs.utils import tmp_to_root_org
from .status import Status
from .. import const
from ..const import ComponentStatusChoices as StatusChoice
from .session import Session


logger = get_logger(__file__)


class TerminalStatusMixin:
    ALIVE_KEY = 'TERMINAL_ALIVE_{}'
    id: str

    @property
    def latest_status(self):
        return Status.get_terminal_latest_status(self)

    @property
    def latest_status_display(self):
        return self.latest_status.label

    @property
    def latest_stat(self):
        return Status.get_terminal_latest_stat(self)

    @property
    def is_normal(self):
        return self.latest_status == StatusChoice.normal

    @property
    def is_high(self):
        return self.latest_status == StatusChoice.high

    @property
    def is_critical(self):
        return self.latest_status == StatusChoice.critical

    @property
    def is_alive(self):
        key = self.ALIVE_KEY.format(self.id)
        # return self.latest_status != StatusChoice.offline
        return cache.get(key, False)

    def set_alive(self, ttl=120):
        key = self.ALIVE_KEY.format(self.id)
        cache.set(key, True, ttl)


class StorageMixin:
    command_storage: str
    replay_storage: str

    def get_command_storage(self):
        from .storage import CommandStorage
        storage = CommandStorage.objects.filter(name=self.command_storage).first()
        return storage

    def get_command_storage_config(self):
        s = self.get_command_storage()
        if s:
            config = s.config
        else:
            config = settings.DEFAULT_TERMINAL_COMMAND_STORAGE
        return config

    def get_command_storage_setting(self):
        config = self.get_command_storage_config()
        return {"TERMINAL_COMMAND_STORAGE": config}

    def get_replay_storage(self):
        from .storage import ReplayStorage
        storage = ReplayStorage.objects.filter(name=self.replay_storage).first()
        return storage

    def get_replay_storage_config(self):
        s = self.get_replay_storage()
        if s:
            config = s.config
        else:
            config = settings.DEFAULT_TERMINAL_REPLAY_STORAGE
        return config

    def get_replay_storage_setting(self):
        config = self.get_replay_storage_config()
        return {"TERMINAL_REPLAY_STORAGE": config}


class BaseTerminalQuerySet(models.QuerySet):
    def undeleted(self):
        return self.filter(is_deleted=False)

    def active(self):
        return self.undeleted().filter(user__is_active=True)

    def alive(self):
        ids = [i.id for i in self.active() if i.is_alive]
        return self.filter(id__in=ids)


class TerminalManager(models.Manager):

    def active(self):
        return self.get_queryset().active()

    def alive(self):
        return self.get_queryset().alive()


class Protocol(models.Model):
    name = models.CharField(
        max_length=64, choices=const.ProtocolName.choices, null=False, blank=False, verbose_name=_('Name')
    )
    port = models.IntegerField(
        null=False, blank=False, verbose_name=_('Port'),
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
    )
    builtin = models.BooleanField(default=False, verbose_name=_('Builtin'))

    class Meta:
        verbose_name = _('Protocol')
        ordering = ('name', )
        unique_together = ('name', 'port')

    def __str__(self):
        builtin = ' [built-in]' if self.builtin else ''
        return f'{self.name}/{self.port}{builtin}'

    @classmethod
    def get_default_protocols_data(cls, ttype):
        assert ttype in const.terminal_type_protocols_mapper, (
            'No support terminal type: {}'.format(ttype)
        )
        support_protocols = const.terminal_type_protocols_mapper[ttype]
        protocols_data = [
            {'name': p.name, 'port': p.default_port, 'builtin': True}
            for p in support_protocols
        ]
        return protocols_data

    @classmethod
    def get_default_protocols(cls, ttype):
        data = cls.get_default_protocols_data(ttype)
        return cls.get_or_create_protocols(data)

    @classmethod
    def get_initial_data(cls):
        data = [
            {'name': p.name, 'port': p.default_port, 'builtin': True}
            for p in const.ProtocolName
        ]
        return data

    @classmethod
    def initial_to_db(cls):
        data = cls.get_initial_data()
        return cls.get_or_create_protocols(data)

    @classmethod
    def get_or_create_protocols(cls, data):
        protocols = []
        for d in data:
            name = d.get('name')
            port = d.get('port')
            if not all([name, port]):
                continue
            protocol, created = cls.objects.get_or_create(**{
                'name': name, 'port': port, 'builtin': True
            })
            protocols.append(protocol)
        return protocols


class Terminal(StorageMixin, TerminalStatusMixin, models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    type = models.CharField(
        choices=const.TerminalTypeChoices.choices, default=const.TerminalTypeChoices.koko.value,
        max_length=64, verbose_name=_('type')
    )
    remote_addr = models.CharField(max_length=128, blank=True, verbose_name=_('Remote Address'))
    ssh_port = models.IntegerField(verbose_name=_('SSH Port'), default=2222)
    http_port = models.IntegerField(verbose_name=_('HTTP Port'), default=5000)
    command_storage = models.CharField(max_length=128, verbose_name=_("Command storage"), default='default')
    replay_storage = models.CharField(max_length=128, verbose_name=_("Replay storage"), default='default')
    user = models.OneToOneField(User, related_name='terminal', verbose_name='Application User', null=True, on_delete=models.CASCADE)
    protocols = models.ManyToManyField('terminal.Protocol', related_name='terminals', verbose_name=_('Protocol'))
    is_accepted = models.BooleanField(default=False, verbose_name='Is Accepted')
    is_deleted = models.BooleanField(default=False)
    date_created = models.DateTimeField(auto_now_add=True)
    comment = models.TextField(blank=True, verbose_name=_('Comment'))
    domains = models.ManyToManyField('assets.Domain', related_name='terminals', blank=True, verbose_name=_("Domain"))

    objects = TerminalManager.from_queryset(BaseTerminalQuerySet)()

    @property
    def is_active(self):
        if self.user and self.user.is_active:
            return True
        return False

    @is_active.setter
    def is_active(self, active):
        if self.user:
            self.user.is_active = active
            self.user.save()

    def get_online_sessions(self):
        with tmp_to_root_org():
            return Session.objects.filter(terminal=self, is_finished=False)

    def get_online_session_count(self):
        return self.get_online_sessions().count()

    @staticmethod
    def get_login_title_setting():
        from settings.utils import get_login_title
        return {'TERMINAL_HEADER_TITLE': get_login_title()}

    @property
    def config(self):
        configs = {}
        for k in dir(settings):
            if not k.startswith('TERMINAL'):
                continue
            configs[k] = getattr(settings, k)
        configs.update(self.get_command_storage_setting())
        configs.update(self.get_replay_storage_setting())
        configs.update(self.get_login_title_setting())
        configs.update({
            'SECURITY_MAX_IDLE_TIME': settings.SECURITY_MAX_IDLE_TIME,
            'SECURITY_SESSION_SHARE': settings.SECURITY_SESSION_SHARE
        })
        return configs

    def reset_protocols_to_default(self):
        default_protocols = Protocol.get_default_protocols(self.type)
        self.protocols.set(default_protocols)

    @property
    def service_account(self):
        return self.user

    def delete(self, using=None, keep_parents=False):
        if self.user:
            self.user.delete()
        self.user = None
        self.is_deleted = True
        self.save()

    def __str__(self):
        status = "Active"
        if not self.is_accepted:
            status = "NotAccept"
        elif self.is_deleted:
            status = "Deleted"
        elif not self.is_active:
            status = "Disable"
        elif not self.is_alive:
            status = 'Offline'
        return '%s: %s' % (self.name, status)

    class Meta:
        ordering = ('is_accepted',)
        db_table = "terminal"
        verbose_name = _("Terminal")
        permissions = (
            ('view_terminalconfig', _('Can view terminal config')),
        )

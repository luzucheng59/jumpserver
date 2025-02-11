# Generated by Django 4.1.10 on 2023-07-25 06:58

from django.db import migrations


def migrate_platforms_sftp_protocol(apps, schema_editor):
    platform_protocol_cls = apps.get_model('assets', 'PlatformProtocol')
    platform_cls = apps.get_model('assets', 'Platform')
    ssh_protocols = platform_protocol_cls.objects \
        .filter(name='ssh', setting__sftp_enabled=True) \
        .exclude(name__in=('Gateway', 'RemoteAppHost')) \
        .filter(platform__type='linux')
    platforms_has_sftp = platform_cls.objects.filter(protocols__name='sftp')

    new_protocols = []
    print("\nPlatform add sftp protocol: ")
    for protocol in ssh_protocols:
        protocol_setting = protocol.setting or {}
        if protocol.platform in platforms_has_sftp:
            continue

        kwargs = {
            'name': 'sftp',
            'port': protocol.port,
            'primary': False,
            'required': False,
            'default': True,
            'public': True,
            'setting': {
                'sftp_home': protocol_setting.get('sftp_home', '/tmp'),
            },
            'platform': protocol.platform,
        }
        new_protocol = platform_protocol_cls(**kwargs)
        new_protocols.append(new_protocol)
        print(" - {}".format(protocol.platform.name))

    new_protocols_dict = {(protocol.name, protocol.platform): protocol for protocol in new_protocols}
    new_protocols = list(new_protocols_dict.values())
    platform_protocol_cls.objects.bulk_create(new_protocols, ignore_conflicts=True)


def migrate_assets_sftp_protocol(apps, schema_editor):
    asset_cls = apps.get_model('assets', 'Asset')
    platform_cls = apps.get_model('assets', 'Platform')
    protocol_cls = apps.get_model('assets', 'Protocol')
    sftp_platforms = list(platform_cls.objects.filter(protocols__name='sftp').values_list('id'))

    count = 0
    print("\nAsset add sftp protocol: ")
    asset_ids = asset_cls.objects\
        .filter(platform__in=sftp_platforms)\
        .exclude(protocols__name='sftp')\
        .distinct()\
        .values_list('id', flat=True)
    while True:
        _asset_ids = asset_ids[count:count + 1000]
        if not _asset_ids:
            break
        count += 1000

        new_protocols = []
        ssh_protocols = protocol_cls.objects.filter(name='ssh', asset_id__in=_asset_ids).distinct()
        ssh_protocols_map = {protocol.asset_id: protocol for protocol in ssh_protocols}
        for asset_id, protocol in ssh_protocols_map.items():
            new_protocols.append(protocol_cls(name='sftp', port=protocol.port, asset_id=asset_id))
        protocol_cls.objects.bulk_create(new_protocols, ignore_conflicts=True)
        print(" - Add {}".format(len(new_protocols)))


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0120_auto_20230630_1613'),
    ]

    operations = [
        migrations.RunPython(migrate_platforms_sftp_protocol),
        migrations.RunPython(migrate_assets_sftp_protocol),
    ]

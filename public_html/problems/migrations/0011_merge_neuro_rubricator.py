"""Свести ветки 0009_neurosolvequota и 0010_seed_rubricator."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0009_neurosolvequota'),
        ('problems', '0010_seed_rubricator'),
    ]

    operations = []

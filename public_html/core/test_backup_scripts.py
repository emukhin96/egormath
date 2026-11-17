"""Скрипты копии в Selectel (deploy/VPS.md, «Копия в Selectel»): подпись S3 и синтаксис.

Сами скрипты гоняются на сервере и Mac (Docker, gpg, GNU find); здесь — то, что ломается
незаметно до первой ночи: подпись AWS SigV4 клиента и синтаксис bash.
"""
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = [
    REPO / 'deploy/vps/backup-offsite.sh',
    REPO / 'deploy/vps/backup.sh',
    REPO / 'deploy/vps/deploy.sh',
    REPO / 'tools/backup-mac.sh',
]


class BackupScriptsTests(SimpleTestCase):
    def test_s3_signature_matches_aws_examples(self):
        run = subprocess.run(
            [sys.executable, str(REPO / 'deploy/vps/backup_s3.py'), 'selftest'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(run.returncode, 0, run.stderr or run.stdout)
        self.assertIn('selftest: ok', run.stdout)

    def test_bash_syntax(self):
        for script in SCRIPTS:
            with self.subTest(script=script.name):
                run = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)

    def test_public_key_only(self):
        """В репозитории — только публичный ключ: приватный у владельца."""
        key = (REPO / 'deploy/vps/backup-pubkey.asc').read_text()
        self.assertIn('BEGIN PGP PUBLIC KEY BLOCK', key)
        self.assertNotIn('PRIVATE KEY', key)

    def test_cron_line_matches_script(self):
        cron = (REPO / 'deploy/vps/crontab.example').read_text()
        self.assertIn('/opt/egormath/deploy/vps/backup-offsite.sh daily', cron)

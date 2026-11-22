import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app as application


class FakeSupabase:
    def __init__(self):
        self.inserted_rows = []

    def from_(self, table_name):
        self.table_name = table_name
        return self

    def insert(self, rows):
        self.inserted_rows.extend(rows)
        return self

    def execute(self):
        return SimpleNamespace(error=None)


class ContactMessageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.originals = {
            'supabase': application.supabase,
            'columns': application.SUPABASE_COLUMNS,
            'table': application.SUPABASE_TABLE,
            'rate_limit_db': application.LOGIN_RATE_LIMIT_DB,
            'resend_api_key': application.RESEND_API_KEY,
            'mail_username': application.MAIL_USERNAME,
            'mail_password': application.MAIL_PASSWORD
        }
        self.database = FakeSupabase()
        application.supabase = self.database
        application.SUPABASE_COLUMNS = ['username', 'email', 'content', 'created_at']
        application.SUPABASE_TABLE = 'messages'
        application.LOGIN_RATE_LIMIT_DB = Path(self.temp_dir.name) / 'rate-limits.sqlite3'
        application.RESEND_API_KEY = ''
        application.MAIL_USERNAME = ''
        application.MAIL_PASSWORD = ''
        self.client = application.app.test_client()

    def tearDown(self):
        application.supabase = self.originals['supabase']
        application.SUPABASE_COLUMNS = self.originals['columns']
        application.SUPABASE_TABLE = self.originals['table']
        application.LOGIN_RATE_LIMIT_DB = self.originals['rate_limit_db']
        application.RESEND_API_KEY = self.originals['resend_api_key']
        application.MAIL_USERNAME = self.originals['mail_username']
        application.MAIL_PASSWORD = self.originals['mail_password']
        self.temp_dir.cleanup()

    def payload(self, **overrides):
        data = {
            'name': 'Amina Test',
            'email': 'amina@example.com',
            'phone': '+387 61 000 000',
            'topic': 'collaboration',
            'organization': 'Omladinski centar',
            'collaboration_kind': 'education',
            'activity_date': '2027-03-15',
            'message': 'Želimo organizovati radionicu.',
            'consent': True,
            'website': ''
        }
        data.update(overrides)
        return data

    def test_collaboration_request_is_saved_with_context_and_safe_email(self):
        application.RESEND_API_KEY = 'test-key'
        with patch.object(application.resend.Emails, 'send', return_value={'id': 'test'}) as send_email:
            response = self.client.post(
                '/send-message',
                json=self.payload(message='<script>alert(1)</script>')
            )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json['success'])
        self.assertEqual(len(self.database.inserted_rows), 1)
        saved = self.database.inserted_rows[0]
        self.assertEqual(saved['username'], 'Amina Test')
        self.assertIn('Saradnja i partnerstvo', saved['content'])
        self.assertIn('Omladinski centar', saved['content'])
        self.assertIn('Edukacija i radionice', saved['content'])
        email_html = send_email.call_args.args[0]['html']
        self.assertIn('&lt;script&gt;', email_html)
        self.assertNotIn('<script>', email_html)

    def test_missing_consent_and_honeypot_are_rejected(self):
        no_consent = self.client.post('/send-message', json=self.payload(consent=False))
        self.assertEqual(no_consent.status_code, 400)
        self.assertEqual(self.database.inserted_rows, [])

        honeypot = self.client.post('/send-message', json=self.payload(website='spam'))
        self.assertEqual(honeypot.status_code, 400)
        self.assertEqual(self.database.inserted_rows, [])

    def test_general_question_does_not_require_collaboration_fields(self):
        data = self.payload(
            topic='general',
            organization='',
            collaboration_kind='',
            activity_date=''
        )
        with patch.object(application, 'send_contact_notification', return_value=(True, None)):
            response = self.client.post('/send-message', json=data)

        self.assertEqual(response.status_code, 201)
        saved = self.database.inserted_rows[0]['content']
        self.assertIn('Opći upit', saved)
        self.assertNotIn('Oblast saradnje', saved)

    def test_contact_submission_rate_limit_returns_retry_after(self):
        with patch.object(application, 'send_contact_notification', return_value=(True, None)):
            for _ in range(application.CONTACT_RATE_LIMIT):
                response = self.client.post('/send-message', json=self.payload())
                self.assertEqual(response.status_code, 201)

            response = self.client.post('/send-message', json=self.payload())

        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers['Retry-After']), 0)
        self.assertEqual(len(self.database.inserted_rows), application.CONTACT_RATE_LIMIT)


if __name__ == '__main__':
    unittest.main()

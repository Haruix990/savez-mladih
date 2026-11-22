import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import app as application


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows
        self.auth = SimpleNamespace(
            get_user=lambda token: SimpleNamespace(
                user=SimpleNamespace(email=application.SUPABASE_ADMIN_EMAIL)
            )
        )

    def from_(self, table_name):
        self.table_name = table_name
        return self

    def select(self, columns):
        return self

    def order(self, column, desc=False):
        return self

    def limit(self, count):
        return self

    def execute(self):
        return SimpleNamespace(error=None, data=self.rows)


class AdminContentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.originals = {
            'supabase': application.supabase,
            'table': application.SUPABASE_TABLE,
            'service_role_key': application.SUPABASE_SERVICE_ROLE_KEY,
            'admin_email': application.SUPABASE_ADMIN_EMAIL,
            'contact_inbox_db': application.CONTACT_INBOX_DB,
            'events_file': application.EVENTS_FILE
        }
        self.rows = [{
            'username': 'Amina Test',
            'email': 'amina@example.com',
            'content': 'Vrsta upita: Saradnja i partnerstvo\n\nPoruka:\nRadionica za mlade.',
            'created_at': '2026-11-20T12:00:00+00:00'
        }]
        application.SUPABASE_ADMIN_EMAIL = 'admin@example.com'
        self.database = FakeSupabase(self.rows)
        application.supabase = self.database
        application.SUPABASE_TABLE = 'messages'
        application.SUPABASE_SERVICE_ROLE_KEY = 'test-service-role-key'
        application.CONTACT_INBOX_DB = Path(self.temp_dir.name) / 'contact-inbox.sqlite3'
        application.EVENTS_FILE = Path(self.temp_dir.name) / 'events.json'
        self.client = application.app.test_client()

    def tearDown(self):
        application.supabase = self.originals['supabase']
        application.SUPABASE_TABLE = self.originals['table']
        application.SUPABASE_SERVICE_ROLE_KEY = self.originals['service_role_key']
        application.SUPABASE_ADMIN_EMAIL = self.originals['admin_email']
        application.CONTACT_INBOX_DB = self.originals['contact_inbox_db']
        application.EVENTS_FILE = self.originals['events_file']
        self.temp_dir.cleanup()

    def authenticate_session(self):
        with self.client.session_transaction() as session:
            session['is_admin'] = True

    def test_contact_inbox_requires_admin_and_persists_status_and_tag(self):
        unauthorized = self.client.get('/api/admin/messages')
        self.assertEqual(unauthorized.status_code, 401)

        self.authenticate_session()
        response = self.client.get('/api/admin/messages')
        self.assertEqual(response.status_code, 200)
        message = response.json['messages'][0]
        self.assertEqual(message['name'], 'Amina Test')
        self.assertEqual(message['tag'], 'collaboration')
        self.assertEqual(message['status'], 'new')

        updated = self.client.patch(
            f"/api/admin/messages/{message['id']}",
            json={'status': 'responded', 'tag': 'general'}
        )
        self.assertEqual(updated.status_code, 200)
        reloaded = self.client.get('/api/admin/messages')
        self.assertEqual(reloaded.json['messages'][0]['status'], 'responded')
        self.assertEqual(reloaded.json['messages'][0]['tag'], 'general')

    def test_supabase_admin_bearer_token_is_verified_and_email_restricted(self):
        authorized = self.client.get(
            '/api/admin/messages',
            headers={'Authorization': 'Bearer valid-test-token'}
        )
        self.assertEqual(authorized.status_code, 200)

        self.database.auth.get_user = lambda token: SimpleNamespace(
            user=SimpleNamespace(email='someone-else@example.com')
        )
        forbidden = self.client.get(
            '/api/admin/messages',
            headers={'Authorization': 'Bearer other-user-token'}
        )
        self.assertEqual(forbidden.status_code, 401)

    def test_event_calendar_hides_drafts_and_supports_admin_crud(self):
        unauthorized = self.client.post(
            '/api/admin/events',
            json={'title': 'Javna aktivnost', 'date': '2026-12-10', 'status': 'published'}
        )
        self.assertEqual(unauthorized.status_code, 401)

        self.authenticate_session()
        created = self.client.post('/api/admin/events', json={
            'title': 'Radionica za mlade',
            'date': '2026-12-10',
            'time': '16:30',
            'location': 'Stari Grad',
            'description': 'Edukativna radionica.',
            'status': 'published'
        })
        self.assertEqual(created.status_code, 201)
        event_id = created.json['event']['id']

        draft = self.client.post('/api/admin/events', json={
            'title': 'Interni nacrt',
            'date': '2026-12-12',
            'status': 'draft'
        })
        self.assertEqual(draft.status_code, 201)

        public_calendar = self.client.get('/api/events')
        self.assertEqual(public_calendar.status_code, 200)
        self.assertEqual([item['title'] for item in public_calendar.json['events']], ['Radionica za mlade'])

        invalid_update = self.client.patch(
            f'/api/admin/events/{event_id}',
            json={'title': 'Neispravan datum', 'date': 'sutra', 'status': 'published'}
        )
        self.assertEqual(invalid_update.status_code, 400)

        updated = self.client.patch(f'/api/admin/events/{event_id}', json={
            'title': 'Radionica promijenjena',
            'date': '2026-12-11',
            'time': '',
            'location': 'Sarajevo',
            'description': 'Novi termin.',
            'status': 'published'
        })
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json['event']['date'], '2026-12-11')

        deleted = self.client.delete(f'/api/admin/events/{event_id}')
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get('/api/events').json['events'], [])


if __name__ == '__main__':
    unittest.main()

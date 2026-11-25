import tempfile
import unittest
from pathlib import Path

import app as application


class EventCalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_events_file = application.EVENTS_FILE
        application.EVENTS_FILE = Path(self.temp_dir.name) / 'events.json'
        application.app.secret_key = 'event-test-secret'
        self.client = application.app.test_client()

    def tearDown(self):
        application.EVENTS_FILE = self.original_events_file
        self.temp_dir.cleanup()

    def admin_session(self):
        with self.client.session_transaction() as session:
            session['is_admin'] = True

    def test_event_crud_persists_and_public_api_filters_drafts(self):
        self.admin_session()

        create = self.client.post('/api/admin/events', json={
            'title': 'Radionica',
            'date': '2027-03-15',
            'time': '18:30',
            'location': 'Kulturni centar',
            'description': 'Detalji radionice',
            'status': 'published',
        })
        self.assertEqual(create.status_code, 201)
        event = create.get_json()['event']

        public = self.client.get('/api/events')
        self.assertEqual(public.status_code, 200)
        self.assertEqual(len(public.get_json()['events']), 1)
        self.assertEqual(public.get_json()['events'][0]['title'], 'Radionica')

        update = self.client.patch(f"/api/admin/events/{event['id']}", json={
            'title': 'Ažurirana radionica',
            'date': '2027-03-16',
            'time': '19:00',
            'location': 'Nova lokacija',
            'description': 'Novi opis',
            'status': 'draft',
        })
        self.assertEqual(update.status_code, 200)

        public = self.client.get('/api/events')
        self.assertEqual(public.get_json()['events'], [])

        delete = self.client.delete(f"/api/admin/events/{event['id']}")
        self.assertEqual(delete.status_code, 200)

        admin_list = self.client.get('/api/admin/events')
        self.assertEqual(admin_list.status_code, 200)
        self.assertEqual(admin_list.get_json()['events'], [])

    def test_event_validation_rejects_invalid_date(self):
        self.admin_session()
        response = self.client.post('/api/admin/events', json={
            'title': 'Neispravan događaj',
            'date': 'not-a-date',
            'time': '',
            'location': '',
            'description': '',
            'status': 'published',
        })
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()

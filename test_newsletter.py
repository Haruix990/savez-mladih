import unittest

import app as application


class FakeSupabaseResult:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error


class FakeSupabaseQuery:
    def __init__(self):
        self.data = []

    def from_(self, _table):
        return self

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def is_(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def delete(self, *_args, **_kwargs):
        return self

    def insert(self, *_args, **_kwargs):
        self.data = [{'id': '00000000-0000-0000-0000-000000000001'}]
        return self

    def upsert(self, *_args, **_kwargs):
        self.data = [{'id': '00000000-0000-0000-0000-000000000001'}]
        return self

    def execute(self):
        return FakeSupabaseResult(self.data)


class NewsletterRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = application.app.test_client()
        self.original_supabase = application.supabase
        self.original_service_role = application.SUPABASE_SERVICE_ROLE_KEY
        self.original_rate_limit = application.newsletter_rate_limit_retry_after
        self.original_send_resend = application.send_resend

        application.supabase = FakeSupabaseQuery()
        application.SUPABASE_SERVICE_ROLE_KEY = 'test-service-role'
        application.newsletter_rate_limit_retry_after = lambda: 0
        application.send_resend = lambda *_args, **_kwargs: (
            False,
            None,
            'Testirana Resend greska',
        )

    def tearDown(self):
        application.supabase = self.original_supabase
        application.SUPABASE_SERVICE_ROLE_KEY = self.original_service_role
        application.newsletter_rate_limit_retry_after = self.original_rate_limit
        application.send_resend = self.original_send_resend

    def test_valid_submission_reports_resend_failure_instead_of_name_error(self):
        response = self.client.post('/api/subscribe', data={
            'email': 'test@example.com',
            'name': 'Test Ime',
            'consent': '1',
        })
        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.get_json()['ok'])
        self.assertIn('potvrda', response.get_json()['error'].lower())

    def test_invalid_email_is_rejected(self):
        response = self.client.post('/api/subscribe', data={
            'email': 'nije-email',
            'name': 'Test Ime',
            'consent': '1',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('e-mail', response.get_json()['error'])


if __name__ == '__main__':
    unittest.main()

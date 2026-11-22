import tempfile
import unittest
from pathlib import Path

import app as application
from werkzeug.security import generate_password_hash


class AdminSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_password = application.ADMIN_PASSWORD
        self.original_password_hash = application.ADMIN_PASSWORD_HASH
        self.original_secret_key = application.app.secret_key
        self.original_rate_limit_db = application.LOGIN_RATE_LIMIT_DB

        application.ADMIN_PASSWORD = 'test-admin-password'
        application.ADMIN_PASSWORD_HASH = ''
        application.app.secret_key = 'test-session-secret'
        application.LOGIN_RATE_LIMIT_DB = Path(self.temp_dir.name) / 'login-attempts.sqlite3'
        self.client = application.app.test_client()

    def tearDown(self):
        application.ADMIN_PASSWORD = self.original_password
        application.ADMIN_PASSWORD_HASH = self.original_password_hash
        application.app.secret_key = self.original_secret_key
        application.LOGIN_RATE_LIMIT_DB = self.original_rate_limit_db
        self.temp_dir.cleanup()

    def test_login_sets_protected_session_and_logout_clears_it(self):
        response = self.client.post(
            '/api/login',
            data={'password': 'test-admin-password'}
        )

        self.assertEqual(response.status_code, 200)
        cookie = response.headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Lax', cookie)
        self.assertTrue(self.client.get('/api/me').json['is_admin'])

        self.client.post('/api/logout')
        self.assertFalse(self.client.get('/api/me').json['is_admin'])

    def test_login_attempts_are_rate_limited(self):
        for _ in range(application.LOGIN_RATE_LIMIT):
            response = self.client.post('/api/login', data={'password': 'wrong'})
            self.assertEqual(response.status_code, 401)

        response = self.client.post('/api/login', data={'password': 'wrong'})
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers['Retry-After']), 0)

    def test_password_hash_is_supported_and_query_password_is_rejected(self):
        application.ADMIN_PASSWORD_HASH = generate_password_hash('hashed-admin-password')
        response = self.client.post(
            '/api/login',
            data={'password': 'hashed-admin-password'}
        )
        self.assertEqual(response.status_code, 200)

        self.client.post('/api/logout')
        response = self.client.get('/api/members?password=hashed-admin-password')
        self.assertEqual(response.status_code, 401)

        response = self.client.get(
            '/api/members/not-a-real-member',
            headers={'X-Admin-Password': 'hashed-admin-password'}
        )
        self.assertEqual(response.status_code, 404)

    def test_cors_does_not_reflect_untrusted_origins(self):
        response = self.client.get(
            '/api/me',
            headers={'Origin': 'https://untrusted.example'}
        )
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)


if __name__ == '__main__':
    unittest.main()

import os
import resend

RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
MY_EMAIL = os.environ.get('MY_EMAIL', 'harunkapo@gmail.com')

print('RESEND_API_KEY present:', bool(RESEND_API_KEY))
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

try:
    r = resend.Emails.send({
        'from': 'Kontakt Forma <onboarding@resend.dev>',
        'to': MY_EMAIL,
        'subject': 'Testni email iz test_resend.py',
        'html': '<p>Ovo je testni email poslan iz test_resend.py</p>'
    })
    print('Send returned:', r)
except Exception as e:
    print('Send failed:', e)

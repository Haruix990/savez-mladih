from app import app
client = app.test_client()
resp = client.post('/contact', data={
    'name': 'Test Korisnik',
    'email': 'test@example.com',
    'message': 'Test poruka iz provjere'
})
print('status:', resp.status_code)
print(resp.get_data(as_text=True))

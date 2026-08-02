import requests
url='http://127.0.0.1:8000/send-message'
payload={'name':'Test Korisnik','email':'test@example.com','message':'Ovo je test poruka'}
res = requests.post(url, json=payload)
print('STATUS', res.status_code)
try:
    print(res.json())
except Exception:
    print(res.text)

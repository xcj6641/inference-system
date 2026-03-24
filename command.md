### Create python virtual environment:

```
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn
pip freeze > requirements.txt
```

run the server:
uvicorn app.main:app --reload --no-access-log
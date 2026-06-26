### Create python virtual environment:

```
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn
pip freeze > requirements.txt #会保存所有系统软件的版本信息，不仅仅是这个项目用的
```

run the server:
uvicorn app.main:app --reload --no-access-log

run test:
python test_scheduler.py
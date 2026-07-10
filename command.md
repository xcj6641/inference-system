# Create python virtual environment:

```
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn
pip freeze > requirements.txt #会保存所有系统软件的版本信息，不仅仅是这个项目用的
```

run the server:
uvicorn app.main:app --reload --no-access-log
MAX_KV_CAPACITY=128 uvicorn app.main:app --reload
ENGINE_BACKEND=fake uvicorn app.main:app --reload --port 8000

terminate the server:
pkill -f uvicorn

run test:
python test_scheduler.py

# pytest
### ignore directory:
config file: pytest.ini

[pytest]
norecursedirs = DaysSummary

### set test directory:
config file: pytest.ini

[pytest]
testpaths = tests

### see what was tested:
python -m pytest -v

# AWS
ssh -i testbox.pem ubuntu@174.129.74.88

curl http://174.129.74.88:8001/v1/models

# call aws llm
curl -X POST http://174.129.74.88:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-0.5B-Instruct",
    "messages": [
      {"role": "user", "content": "What is the temperature now?"}
    ],
    "max_tokens": 16,
    "temperature": 0
  }'


## launch llm:
source vllm-env/bin/activate
vllm serve Qwen/Qwen2.5-0.5B-Instruct \
  --host 0.0.0.0 \
  --port 8001

# call local
curl -N -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Say hello in one short sentence.",
    "max_new_tokens": 16
  }'
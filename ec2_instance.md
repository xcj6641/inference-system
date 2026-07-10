Yes. The **working stack** is:

```text
EC2 instance: g5.xlarge / A10G
OS: Ubuntu 24.04.4 LTS
Kernel: 6.17.0-1017-aws

NVIDIA Driver: 595.71.05
Driver-reported CUDA: 13.2

Python: 3.12 venv

PyTorch: CUDA 12.1 build
vLLM: 0.6.6.post1
transformers: 4.46.3
tokenizers: 0.20.3

Model: Qwen/Qwen2.5-0.5B-Instruct
vLLM port: 8001
```

The key fixes were:

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install "vllm==0.6.6.post1"
pip uninstall -y transformers tokenizers
pip install "transformers==4.46.3" "tokenizers==0.20.3"
```

The broken stack was:

```text
PyTorch 2.11.0+cu130
vLLM 0.24.0
FlashInfer 0.6.12
nvcc 12.0
```

Main lesson:

```text
Do not mix latest vLLM + CUDA 13 PyTorch + CUDA 12 nvcc.
Use a pinned stable stack.
```

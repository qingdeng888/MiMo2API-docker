# MiMo2API

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-teal)](https://fastapi.tiangolo.com/)

Convert **Xiaomi MiMo AI Studio** web chat into an **OpenAI-compatible API** with multimodal support (text + images + files), function calling, Anthropic Messages API, and multi-account load balancing.

本项目所修改代码均为ai完成，不含任何一句人工代码，望周知！

> 📖 [中文版本](README.md)

Based on [mimo2api](https://github.com/Water008/MiMo2API).

> **💡 Need pure chat or TTS?** Use the [`no-tools` branch](https://github.com/Fly143/MiMo2API/tree/no-tools) — no tool prompt injection, cleaner context, with TTS support.

## Features

- **OpenAI Compatible** — `/v1/chat/completions`, `/v1/models`, `/v1/responses`
- **Multilingual Admin** — Chinese/English UI with one-click toggle
- **Anthropic Messages API** — `/v1/messages` with Claude model name aliases
- **Vision & Multimodal** — Image understanding + file upload
- **Function Calling** — Tool calling via DSML format
- **TTS Voice** — Text-to-speech synthesis (MiMo native)
- **Multi-Account** — Load balancing with auto-failover
- **CORS Enabled** — Cross-origin support for web clients
- **Session Auto-Renewal** — Fingerprint-based conversation continuity

## Quick Start

```bash
git clone https://github.com/Fly143/MiMo2API.git
cd MiMo2API
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Open: **http://localhost:8080/admin**

## Configuration

Access the admin panel at http://localhost:8080/admin:

1. **Cookie Import** — Paste serviceToken, userId, xiaomichatbot_ph from browser
2. **cURL Import** — Copy chat request from DevTools → Copy as cURL
3. **Multi-Account** — Add multiple accounts for load balancing

## API Usage

### Chat Completions
```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-any" \
  -d '{"model":"mimo-default","messages":[{"role":"user","content":"Hello!"}]}'
```

### Anthropic Messages
```bash
curl http://localhost:8080/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: any-value" \
  -d '{"model":"claude-sonnet-4-6","max_tokens":1024,"messages":[{"role":"user","content":"Hello!"}]}'
```

## no-tools Branch

```bash
git clone -b no-tools https://github.com/Fly143/MiMo2API.git
```

Removes tool calling logic for cleaner chat output. TTS synthesis is fully preserved.

## Credits & License

MIT License. Based on [Water008/MiMo2API](https://github.com/Water008/MiMo2API).

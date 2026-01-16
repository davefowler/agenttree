#!/bin/bash
uv run uvicorn agenttree.web.app:app --host 0.0.0.0 --port 8080 --reload

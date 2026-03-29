#!/bin/bash
# UserPromptSubmit hook — proactive memory injection
# Fires before each model response. Injects relevant memories based on prompt content.
# Fast path: FTS5 only (no embedding call). Must complete quickly to avoid perceived lag.

if ! command -v innie &>/dev/null; then
    exit 0
fi

exec innie handle prompt-submit 2>/dev/null

"""OCR + DeepSeek or local Qwen-VL agent.

DeepSeek text mode:

    set DEEPSEEK_API_KEY=sk-...
    osprey run examples/ai_agent.py --config examples/ai_agent.json

Local Qwen-VL through Ollama (install Ollama first):

    set OSPREY_AI_PROVIDER=qwen-local
    set OSPREY_AI_MODEL=7b
    osprey run examples/ai_agent.py --config examples/ai_agent.json

3B is the "usable" tier; 7B is the more precise tier.
"""

import os

from osprey.ai.agent import OcrAgentTask, VisionAgentTask
from osprey.ai.vision import LOCAL_MODELS, QwenVisionClient


def create_task():
    provider = os.environ.get("OSPREY_AI_PROVIDER", "deepseek").strip().lower()
    if provider in ("qwen", "qwen-local", "qwen_vl", "local"):
        tier = os.environ.get("OSPREY_AI_MODEL", "7b").strip().lower()
        model = LOCAL_MODELS.get(tier, tier)
        return VisionAgentTask(
            vision=QwenVisionClient(model=model, profile=tier))
    return OcrAgentTask()

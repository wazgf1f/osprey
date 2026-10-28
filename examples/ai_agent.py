"""OCR + DeepSeek agent.

Install the optional OCR dependency and set a key:

    pip install -e ".[ai]"
    set DEEPSEEK_API_KEY=sk-...

Then run the plan with the engine:

    osprey run examples/ai_agent.py --config examples/ai_agent.json
    osprey run examples/ai_agent.py --config examples/ai_agent.json --live
"""

from osprey.ai.agent import OcrAgentTask


def create_task() -> OcrAgentTask:
    return OcrAgentTask()

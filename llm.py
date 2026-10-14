import subprocess
import tempfile

DEFAULT_MODEL = "openai-codex/gpt-6-luna"
CLAUDE_ALIASES = {"haiku", "sonnet", "opus", "fable"}
PI_FLAGS = ["--no-tools", "--no-session", "-nc", "-ns", "-np", "-ne", "-na"]


def command(prompt, model):
    if model.startswith("claude:"):
        return ["claude", "-p", prompt, "--model", model.removeprefix("claude:")]
    if model.startswith("pi:"):
        model = model.removeprefix("pi:")
    elif "/" not in model and (model.startswith("claude-") or model in CLAUDE_ALIASES):
        return ["claude", "-p", prompt, "--model", model]
    return ["pi", "-p", "--model", model, *PI_FLAGS, "--", prompt]


def run(prompt, model, input_text="", timeout=900):
    with tempfile.TemporaryDirectory() as cwd:
        return subprocess.run(command(prompt, model), input=input_text, capture_output=True,
                              text=True, timeout=timeout, cwd=cwd)

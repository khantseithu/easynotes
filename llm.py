import subprocess
import tempfile

import transcript

DEFAULT_MODEL = "openai-codex/gpt-6-luna"
BURMESE_MODEL = "openai-codex/gpt-6.1-sol"
CLAUDE_ALIASES = {"haiku", "sonnet", "opus", "fable"}
PI_FLAGS = ["--no-tools", "--no-session", "-nc", "-ns", "-np", "-ne", "-na"]


def model_for_language(language, model=None):
    if model:
        return model
    return BURMESE_MODEL if language in ("my", "Burmese") else DEFAULT_MODEL


def command(prompt, model):
    if model.startswith("claude:"):
        return ["claude", "-p", prompt, "--model", model.removeprefix("claude:")]
    if model.startswith("pi:"):
        model = model.removeprefix("pi:")
    elif "/" not in model and (model.startswith("claude-") or model in CLAUDE_ALIASES):
        return ["claude", "-p", prompt, "--model", model]
    return ["pi", "-p", "--model", model, *PI_FLAGS, "--", prompt]


def run(prompt, model, input_text="", timeout=900):
    model = model or DEFAULT_MODEL
    with tempfile.TemporaryDirectory() as cwd:
        return subprocess.run(command(prompt, model), input=input_text, capture_output=True,
                              text=True, timeout=timeout, cwd=cwd)


def run_burmese(prompt, model, source, input_text="", timeout=900):
    model = model_for_language("my", model)
    output = run(prompt, model, input_text, timeout)
    if output.returncode != 0 or transcript.valid_burmese_output(output.stdout, source):
        return output

    repair_prompt = prompt + """

Repair the draft in the final input block. Follow the original task and return only the corrected result. Write all explanations and prose in Burmese. Keep standard English section headings, and retain Latin text only for names, technical terms, code, and verbatim source text. Remove unrelated foreign-script text and all drafting or self-review remarks. Preserve source facts and required structure.
"""
    repair_input = input_text + "\n\n## Draft to repair\n" + output.stdout
    repaired = run(repair_prompt, model, repair_input, timeout)
    if repaired.returncode != 0:
        raise RuntimeError("Burmese output repair failed")
    issues = transcript.burmese_output_issues(repaired.stdout, source)
    if issues:
        raise RuntimeError("Burmese output failed validation after one repair: " + ", ".join(issues))
    return repaired

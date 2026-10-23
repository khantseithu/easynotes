import json
import subprocess
import tempfile

import transcript

DEFAULT_MODEL = "gemini-3.8-flash"
BURMESE_MODEL = "gemini-3.8-flash-high"
CLAUDE_ALIASES = {"haiku", "sonnet", "opus", "fable"}
PI_FLAGS = ["--no-tools", "--no-session", "-nc", "-ns", "-np", "-ne", "-na"]
AGY_FLAGS = ["--input-format", "stream-json", "--output-format", "stream-json", "--disable-slash-commands", "-p="]
AGY_NOTE = ("Answer from this message alone. Do not use any tools, commands, files, or web pages. "
            "Everything the instructions call stdin is included at the end of this message, after the line \"--- stdin ---\". "
            "Reply with only the requested output.")


def model_for_language(language, model=None):
    if model:
        return model
    return BURMESE_MODEL if language in ("my", "Burmese") else DEFAULT_MODEL


def agy_model(model):
    if model.startswith("agy:"):
        return model.removeprefix("agy:")
    if "/" not in model and model.startswith("gemini-"):
        return model
    return None


def agy_result(out):
    events = [json.loads(line) for line in out.stdout.splitlines() if line.startswith("{")]
    results = [e["result"] for e in events if e.get("event") == "result"]
    result = results[-1] if results else {}
    ok = out.returncode == 0 and result.get("status") == "SUCCESS"
    error = result.get("error") or out.stderr
    return subprocess.CompletedProcess(out.args, 0 if ok else out.returncode or 1,
                                       result.get("response", "") if ok else "", "" if ok else error)


def command(prompt, model):
    if agy_model(model):
        return ["agy", "--model", agy_model(model), *AGY_FLAGS]
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
        if agy_model(model):
            content = AGY_NOTE + "\n\n" + prompt + ("\n\n--- stdin ---\n" + input_text if input_text else "")
            message = json.dumps({"event": "user", "message": {"content": content}})
            return agy_result(subprocess.run(command(prompt, model), input=message, capture_output=True,
                                             text=True, timeout=timeout, cwd=cwd))
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

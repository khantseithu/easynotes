import re
import unicodedata


def caption_languages(original_language):
    if original_language == "my":
        return "my-orig,my,en.*,en", ("my", "en")
    return "en.*,en,my-orig,my", ("en", "my")


def order_caption_files(files, video_id, original_language):
    language_order = ("my-orig", "my", "en") if original_language == "my" else ("en", "my-orig", "my")
    priorities = {lang: i for i, lang in enumerate(language_order)}

    def priority(path):
        language = path.name[len(video_id) + 1:-len(".json3")]
        language = "en" if language.startswith(("en-", "en.")) else language
        language = "my" if language.startswith(("my-", "my.")) and language != "my-orig" else language
        return priorities.get(language, len(priorities))

    return sorted(files, key=priority)


_DRAFTING_REMARK = re.compile(
    r"\b(?:wait\s+burmese|fix\s+burmese|need\s+fix|check\s+burmese)\b",
    re.IGNORECASE,
)


def _script_runs(text):
    runs = []
    current_script = None
    current = []
    for char in text:
        category = unicodedata.category(char)
        if category.startswith("L"):
            name = unicodedata.name(char, "UNKNOWN")
            script = name.split()[0]
            if script != current_script:
                if current:
                    runs.append((current_script, "".join(current)))
                current_script, current = script, [char]
            else:
                current.append(char)
        elif category.startswith("M") and current:
            current.append(char)
        else:
            if current:
                runs.append((current_script, "".join(current)))
            current_script, current = None, []
    if current:
        runs.append((current_script, "".join(current)))
    return runs


def burmese_output_issues(output, source=""):
    source_runs = {run for script, run in _script_runs(source) if script not in {"LATIN", "MYANMAR"}}
    output_runs = [(script, run) for script, run in _script_runs(output) if script not in {"LATIN", "MYANMAR"}]
    issues = []
    if any(run not in source_runs for _, run in output_runs):
        issues.append("unsupported foreign-script text")
    if output.strip() and not any(script == "MYANMAR" for script, _ in _script_runs(output)):
        issues.append("missing Burmese text")
    if _DRAFTING_REMARK.search(output):
        issues.append("drafting remark")
    return issues


def valid_burmese_output(output, source=""):
    return not burmese_output_issues(output, source)

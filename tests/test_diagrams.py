import unittest

import ytnotes

NOTE = """## TL;DR
Users bring users.

## Key ideas
### The loop [1:20]
- Content brings visitors.

```mermaid
flowchart LR
  accTitle: The growth loop
  A[Users] -->|"at [1:20]"| B[Content]
  B --> A
```
"""


class DiagramTests(unittest.TestCase):
    def test_every_note_prompt_asks_for_mermaid_diagrams(self):
        for language in ("en", "my"):
            prompt = ytnotes.notes_prompt(language).format(
                title="T", channel="C", duration="1h")
            self.assertIn('tagged "mermaid"', prompt)
        self.assertIn("Never put a diagram in the TL;DR section", ytnotes.notes_prompt("en"))

    def test_diagrams_are_not_read_aloud(self):
        script = ytnotes.speakable({"title": "Growth", "channel": "C"}, NOTE)
        self.assertIn("Content brings visitors.", script)
        self.assertNotIn("flowchart", script)
        self.assertNotIn("accTitle", script)

    def test_timestamps_inside_diagrams_are_left_alone(self):
        md = ytnotes.link_stamps(NOTE, "abcdefghijk")
        self.assertIn("### The loop [1:20](https://youtu.be/abcdefghijk?t=80)", md)
        self.assertIn('|"at [1:20]"|', md)

    def test_tldr_stays_free_of_diagrams(self):
        self.assertEqual(ytnotes.tldr(NOTE), "Users bring users.")


if __name__ == "__main__":
    unittest.main()

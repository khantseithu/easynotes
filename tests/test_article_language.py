import unittest

import ytnotes


class ArticleLanguageTests(unittest.TestCase):
    def test_article_urls_are_supported_alongside_youtube(self):
        videos, playlists, articles, topic = ytnotes.parse_input(
            "https://example.com/story https://youtu.be/abcdefghijk"
        )
        self.assertEqual(videos, ["abcdefghijk"])
        self.assertEqual(playlists, [])
        self.assertEqual(articles, ["https://example.com/story"])
        self.assertEqual(topic, "")

    def test_burmese_article_text_selects_burmese_notes(self):
        self.assertEqual(ytnotes.article_language("မြန်မာစာ ဖတ်ရှုရန် အကြောင်းအရာ"), "my")

    def test_english_article_text_keeps_english_notes(self):
        self.assertEqual(ytnotes.article_language("An article about product design."), "en")


if __name__ == "__main__":
    unittest.main()

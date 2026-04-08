from django.test import SimpleTestCase

from bs4 import BeautifulSoup

from core.management.commands.scrape_lotoven_animalitos import Command


class LotovenAnimalitosParserTestCase(SimpleTestCase):
    def setUp(self):
        self.command = Command()

    def test_extract_media_url_prefers_lazy_loaded_attributes(self):
        soup = BeautifulSoup(
            '<img src="/static/placeholder.gif" data-src="/dist/animals_img/Cochino_36.webp" />',
            "html.parser",
        )

        image = soup.select_one("img")
        self.assertEqual(
            self.command._extract_media_url(image),
            "https://lotoven.com/dist/animals_img/Cochino_36.webp",
        )

    def test_extract_media_url_uses_first_srcset_candidate(self):
        soup = BeautifulSoup(
            '<img srcset="/dist/animals_img/Cochino_36.webp 1x, /dist/animals_img/Cochino_36@2x.webp 2x" />',
            "html.parser",
        )

        image = soup.select_one("img")
        self.assertEqual(
            self.command._extract_media_url(image),
            "https://lotoven.com/dist/animals_img/Cochino_36.webp",
        )

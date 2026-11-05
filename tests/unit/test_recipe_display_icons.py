import unittest
from recipe_search.presentation.recipe_display_image import (
    choose_fallback_category,
    choose_display_image,
    enrich_recipe_for_display,
    LABELS,
)


class RecipeDisplayIconTests(unittest.TestCase):
    def test_name_precedes_tags_and_ingredients(self):
        self.assertEqual(
            choose_fallback_category(
                dict(name="Chicken stir-fry", keywords=["soup"], ingredients=["rice"])
            ),
            "stirfry",
        )
        self.assertEqual(
            choose_fallback_category(
                dict(name="Fruit Salad", recipecategory=["dessert"], ingredients=["chicken"])
            ),
            "salad",
        )
        self.assertEqual(
            choose_fallback_category(
                dict(name="Lemon chicken", keywords=["salad"], ingredients=["rice"])
            ),
            "salad",
        )

    def test_specific_form_precedes_broad_dessert_at_same_tier(self):
        for field in ("name", "keywords", "recipecategory"):
            value = "dessert fruit salad" if field == "name" else ["dessert", "fruit salad"]
            self.assertEqual(choose_fallback_category({field: value}), "salad")

    def test_word_boundaries_and_no_main_ingredient_category(self):
        for name in (
            "Chicken surprise",
            "Price drop",
            "Ricepaper rolls",
            "Macadamia bites",
            "Pieplant compote",
            "Wrapped chicken",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    choose_fallback_category(dict(name=name, ingredients=["chicken"])), "default"
                )

    def test_forms_and_plural_variants(self):
        cases = {
            "Wok vegetables": "stirfry",
            "Stirfried chicken": "stirfry",
            "Beef stew": "soup",
            "Noodles with sesame": "pasta",
            "Breakfast eggs": "breakfast",
            "Banana smoothie": "drink",
            "Chicken burger": "sandwich",
            "Brownies": "dessert",
            "Vegetable risotto": "rice",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(choose_fallback_category({"name": name}), expected)

    def test_empty_fields_and_last_resort_ingredients(self):
        self.assertEqual(
            choose_fallback_category(
                dict(name=None, keywords=None, recipecategory=None, ingredients=["spaghetti"])
            ),
            "pasta",
        )
        self.assertEqual(
            choose_fallback_category(
                dict(name="Unknown", keywords="chicken", recipecategory="soups")
            ),
            "soup",
        )

    def test_original_image_is_retained_and_source_unmodified(self):
        recipe = dict(
            name="Fruit salad",
            image_urls=[" https://example.test/salad.jpg "],
            ingredients=["banana"],
        )
        result = enrich_recipe_for_display(recipe)
        self.assertEqual(result["image_source"], "original")
        self.assertTrue(result["has_original_image"])
        self.assertEqual(result["display_image_url"], "https://example.test/salad.jpg")
        self.assertNotIn("fallback_category", recipe)
        self.assertEqual(result["fallback_label"], "Salad")

    def test_all_fallbacks_are_local_symbolic_assets(self):
        folder = (
            __import__("recipe_search.settings", fromlist=["PACKAGE_ROOT"]).PACKAGE_ROOT
            / "web/recipe-icons"
        )
        for category in LABELS:
            asset = folder / (category + ".svg")
            self.assertTrue(asset.is_file())
            self.assertIn("category icon", asset.read_text())
        image, source = choose_display_image(dict(name="Chicken soup", image_urls=[]))
        self.assertEqual(image, "/assets/recipe-icons/soup.svg")
        self.assertEqual(source, "fallback:soup:1")

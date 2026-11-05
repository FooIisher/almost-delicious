import unittest
from recipe_search.matching.tag_normalization import normalize_tags, classify_tags
from recipe_search.ingest.ingest_recipes import (
    transform_recipe_record,
    build_searchable_text,
    build_embedding_text,
)


class TagTests(unittest.TestCase):
    def test_separators_html_and_shared_prefix(self):
        self.assertEqual(
            normalize_tags(["Cookie &amp; Brownie", "Chicken Thigh & Leg", "Breakfast | Brunch"]),
            ["cookie", "brownie", "chicken thigh", "chicken leg", "breakfast", "brunch"],
        )

    def test_phrases_and_unknown_slashes_preserved(self):
        self.assertEqual(
            normalize_tags(["Mac & Cheese", "Sweet & Sour", "Holiday/Event", "Low Sodium"]),
            ["mac and cheese", "sweet and sour", "holiday/event", "low sodium"],
        )

    def test_empty_dedup_and_idempotence(self):
        result = normalize_tags(
            [None, float("nan"), "null", " Breakfast ", "BREAKFAST", "Lunch/Snacks", "& |"]
        )
        self.assertEqual(result, ["breakfast", "lunch", "snack"])
        self.assertEqual(normalize_tags(result), result)

    def test_ambiguous_groups_are_not_hard_facets(self):
        r = classify_tags(["Lunch/Snacks", "Cookie & Brownie", "Weeknight"], "One Dish Meal")
        self.assertEqual(r["meal_types"], [])
        self.assertEqual(r["dish_types"], [])
        self.assertEqual(r["meal_type_candidates"], ["lunch", "snack", "dinner"])
        self.assertTrue(all(e["filter_policy"] == "boost_only" for e in r["tag_mapping_evidence"]))

    def test_specific_mapping_and_no_false_parent(self):
        r = classify_tags(["Clear Soup", "Cantonese"], "Salad Dressings")
        self.assertIn("soup", r["dish_types"])
        self.assertNotIn("salad", r["dish_types"])
        self.assertEqual(r["cuisines"], ["chinese"])
        self.assertNotIn("chinese", classify_tags(["Asian"], None)["cuisines"])
        self.assertEqual(
            classify_tags(["Breakfast | Brunch"], None)["meal_types"], ["breakfast", "brunch"]
        )

    def test_ingestion_updates_only_structured_tags(self):
        r = transform_recipe_record(
            {
                "recipeid": 1,
                "name": "Mac & Cheese",
                "recipecategory": "Lunch/Snacks",
                "keywords": 'c("Cookie & Brownie", "Weeknight")',
                "recipeingredientparts": '"salt & pepper"',
            }
        )
        self.assertEqual(r["name"], "Mac & Cheese")
        self.assertEqual(r["ingredients"], ["salt & pepper"])
        self.assertEqual(r["keywords"], ["cookie", "brownie", "weeknight"])
        self.assertEqual(r["recipecategory"], ["lunch", "snack"])
        self.assertNotIn("meal_types", r)
        self.assertIn("Lunch/Snacks", r["embedding_text"])
        self.assertIn("Cookie & Brownie", r["searchable_text"])
        self.assertIn("category: lunch, snack", build_embedding_text(r))
        self.assertNotIn("['lunch'", build_searchable_text(r))


if __name__ == "__main__":
    unittest.main()

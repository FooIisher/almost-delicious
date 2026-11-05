import unittest
from recipe_search.ranking.recommendation_dedup import dedupe_ranked
from recipe_search.ingest.recipe_text import clean_text
from recipe_search.presentation.recipe_display_image import enrich_recipe_for_display
from recipe_search.llm.content_generation import qualified_prefix


class DedupTests(unittest.TestCase):
    def recipe(self, id, name="Campbell’s Chicken Broccoli Rice Casserole", ingredients=None):
        return dict(
            recipe_id=id,
            name=name,
            ingredients=ingredients
            if ingredients is not None
            else ["chicken", "broccoli", "rice", "cream", "salt", "pepper", "cheese"],
        )

    def test_two_signal_duplicate_keeps_highest_rank(self):
        rows = [
            self.recipe("high"),
            self.recipe("low", "Campbell’s Chicken Broccoli Rice Casserole II"),
        ]
        kept, removed = dedupe_ranked(rows)
        self.assertEqual([r["recipe_id"] for r in kept], ["high"])
        self.assertEqual(removed[0]["kept_recipe_id"], "high")

    def test_shared_name_without_ingredient_support_is_retained(self):
        kept, removed = dedupe_ranked(
            [
                self.recipe("a"),
                self.recipe("b", ingredients=["beef", "carrots", "potatoes"]),
                self.recipe("c", ingredients=[]),
            ]
        )
        self.assertEqual(len(kept), 3)
        self.assertFalse(removed)

    def test_ingredient_overlap_alone_is_insufficient(self):
        self.assertEqual(
            len(
                dedupe_ranked([self.recipe("a"), self.recipe("b", "Asian chicken rice skillet")])[0]
            ),
            2,
        )

    def test_encoding_equivalents_compare_equal(self):
        rows = [self.recipe("a", "Chicken &amp; Rice"), self.recipe("b", "Chicken & Rice")]
        self.assertEqual(len(dedupe_ranked(rows)[0]), 1)

    def test_prefix_counts_distinct_qualified_recipes(self):
        rows = [self.recipe("1"), self.recipe("2"), self.recipe("3", "Another dish")]
        prior = {r["recipe_id"]: dict(status="pass", checks=[]) for r in rows}
        self.assertEqual(qualified_prefix(rows, prior, 2)["frontier_rank"], 3)


class DisplayTextTests(unittest.TestCase):
    def test_entities_and_mojibake(self):
        self.assertEqual(clean_text("Quick &amp; Easy Chicken"), "Quick & Easy Chicken")
        self.assertEqual(clean_text("it doesnï¿½t harden"), "it doesn't harden")
        self.assertEqual(clean_text("CrÃ¨me brÃ»lÃ©e"), "Crème brûlée")
        self.assertEqual(clean_text("5 < 6; 中文"), "5 < 6; 中文")

    def test_display_copy_preserves_source_and_nontext_fields(self):
        source = dict(
            name="Chicken &amp; Rice",
            instructions=["it doesnï¿½t harden"],
            ingredients=["salt"],
            recipeid="unchanged",
        )
        result = enrich_recipe_for_display(source)
        self.assertEqual(result["instructions"], ["it doesn't harden"])
        self.assertEqual(result["name"], "Chicken & Rice")
        self.assertEqual(source["instructions"], ["it doesnï¿½t harden"])
        self.assertEqual(result["recipeid"], "unchanged")

    def test_unknown_lost_characters_are_not_invented(self):
        self.assertIn("\ufffd", clean_text("cook until ï¿½"))


from unittest.mock import patch
import recipe_search.llm.content_generation as service
from tests.unit import test_content_generation as legacy


class GenerationDedupIntegrationTests(unittest.TestCase):
    setUp = legacy.ContentGenerationTests.setUp
    provider = legacy.ContentGenerationTests.provider

    def test_model_receives_five_unique_choices_not_versions(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["recipe_ids"] = [str(i) for i in range(1, 8)]
        self.es.mget.return_value["docs"] = self.es.mget.return_value["docs"][:7]
        for doc in self.es.mget.return_value["docs"][:3]:
            doc["_source"]["name"] = "Campbell’s Creamy Chicken Broccoli Rice"
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider):
            checked = self.client.post("/content/eligibility/deepseek-flash", json=self.request)
            self.assertEqual(checked.status_code, 200, checked.text)
            self.assertEqual(checked.json()["qualified_recipe_ids"], ["1", "4", "5", "6", "7"])
            generated = self.client.post(
                "/content/generate/deepseek-flash",
                json={"eligibility_id": checked.json()["eligibility_id"]},
            )
        self.assertEqual(generated.status_code, 200, generated.text)
        self.assertEqual(
            [r["recipe_id"] for r in self.inputs[-1]["recipes"]], ["1", "4", "5", "6", "7"]
        )
        self.assertEqual(len(generated.json()["recommendations"]), 5)
        self.assertEqual(len(generated.json()["summary_deduplication"]["removed"]), 2)

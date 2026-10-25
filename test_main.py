import os
import unittest
from main import DEFAULT_PROMPT, local_plan, validate_story

class StoryTests(unittest.TestCase):
    def test_prompt_influences_story(self):
        prompt = "A friendly cloud learns to water a garden"
        story = local_plan(prompt)
        self.assertIn("cloud", story["title"].lower())
        self.assertIn("cloud", story["scenes"][0]["text"].lower())
        self.assertEqual(len(story["scenes"]), 5)

    def test_default_prompt_produces_valid_story(self):
        self.assertEqual(len(local_plan(DEFAULT_PROMPT)["scenes"]), 5)

    def test_invalid_scene_count_rejected(self):
        with self.assertRaises(ValueError):
            validate_story({"title":"x","description":"x","lesson":"x","scenes":[]})

if __name__ == "__main__":
    unittest.main()

import unittest

from app_config import (
    child_id_matches,
    load_env_lines,
    parse_child_id,
    parse_timezone_offset,
    validate_config,
)


class AppConfigTests(unittest.TestCase):
    def test_load_env_lines_ignores_comments_and_splits_once(self):
        values = load_env_lines(
            [
                "# comment\n",
                "WIFI_SSID = Family Wi-Fi\n",
                "TOKEN=a=b=c\n",
                "\n",
            ]
        )
        self.assertEqual(
            values, {"WIFI_SSID": "Family Wi-Fi", "TOKEN": "a=b=c"}
        )

    def test_child_id_must_be_positive_integer(self):
        self.assertEqual(parse_child_id("12"), 12)
        for raw in ("", None, "abc", "0", "-1"):
            self.assertIsNone(parse_child_id(raw), raw)

    def test_timezone_offset_is_bounded(self):
        self.assertEqual(parse_timezone_offset("-300"), -300)
        self.assertEqual(parse_timezone_offset("840"), 840)
        for raw in ("", None, "abc", "-721", "841"):
            self.assertIsNone(parse_timezone_offset(raw), raw)

    def test_local_config_rejects_url_credentials_and_unsafe_slug(self):
        parents = {
            "parent_1": {"name": "Mom", "api_token": "token", "tag": "mom"},
        }
        errors = validate_config(
            "ssid",
            "http://user:pass@baby-buddy",
            "child/other",
            1,
            0,
            parents,
        )
        self.assertIn("BABY_BUDDY_BASE_URL must not contain credentials", errors)
        self.assertIn("CHILD_SLUG is required and must be a single path segment", errors)

    def test_validate_config_reports_missing_or_invalid_values(self):
        parents = {
            "parent_1": {"name": "Mom", "api_token": "", "tag": "mom"},
            "parent_2": {"name": "Dad", "api_token": "secret", "tag": ""},
        }
        errors = validate_config("", "ftp://server", "", None, None, parents)
        self.assertIn("WIFI_SSID is required", errors)
        self.assertIn(
            "BABY_BUDDY_BASE_URL must use http:// or https://", errors
        )
        self.assertIn("CHILD_SLUG is required and must be a single path segment", errors)
        self.assertIn("CHILD_ID must be a positive integer", errors)
        self.assertIn("TIMEZONE_OFFSET_MINUTES must be from -720 to 840", errors)
        self.assertIn("Mom token is required", errors)
        self.assertIn("Dad tag is required", errors)
        self.assertNotIn("secret", " ".join(errors))

    def test_child_slug_and_id_must_match(self):
        self.assertTrue(child_id_matches({"id": 7}, 7))
        self.assertTrue(child_id_matches({"id": "7"}, 7))
        self.assertFalse(child_id_matches({"id": 8}, 7))
        self.assertFalse(child_id_matches({}, 7))


if __name__ == "__main__":
    unittest.main()

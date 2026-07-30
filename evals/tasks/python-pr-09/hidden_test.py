import unittest

from pilot_service.auth import authorize


class InjectedAuthorizationTest(unittest.TestCase):
    def test_internal_request_still_checks_actor(self) -> None:
        with self.assertRaises(PermissionError):
            authorize("viewer", "delete", internal_request=True)


if __name__ == "__main__":
    unittest.main()

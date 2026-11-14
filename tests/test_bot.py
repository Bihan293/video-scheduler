import unittest

from app.bot import build_dispatcher


class BotTests(unittest.TestCase):
    def test_dispatcher_has_handlers(self):
        dispatcher = build_dispatcher()
        self.assertIsNotNone(dispatcher.message)
        self.assertIsNotNone(dispatcher.callback_query)


if __name__ == "__main__":
    unittest.main()

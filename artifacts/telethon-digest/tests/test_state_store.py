import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import state_store


class StateStoreTests(unittest.TestCase):
    def test_bulk_set_cursors_is_monotonic(self) -> None:
        original_path = state_store.STATE_PATH
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                state_store.STATE_PATH = Path(tmpdir) / "state.json"

                state_store.bulk_set_cursors({1: 10})
                state_store.bulk_set_cursors({1: 7, 2: 5})

                self.assertEqual(state_store.get_cursor(1), 10)
                self.assertEqual(state_store.get_cursor(2), 5)
            finally:
                state_store.STATE_PATH = original_path


if __name__ == "__main__":
    unittest.main()

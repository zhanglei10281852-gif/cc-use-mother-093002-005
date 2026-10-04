import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from support import generate_all, make_service  # noqa: E402
from teacher_practicum import ArrangementStatus, Party  # noqa: E402


class ConfirmationFlowTests(unittest.TestCase):
    def setUp(self):
        self.service = make_service()
        self.arrangements = generate_all(self.service)
        self.arr = self.arrangements[0]

    def test_three_party_confirmation_completes_arrangement(self):
        self.assertEqual(self.arr.status, ArrangementStatus.PENDING)
        self.assertEqual(
            set(self.arr.pending_parties()), {Party.SCHOOL, Party.MENTOR, Party.COLLEGE}
        )
        self.service.confirm(self.arr.arrangement_id, Party.SCHOOL)
        self.assertEqual(self.arr.pending_parties(), [Party.MENTOR, Party.COLLEGE])
        self.service.confirm(self.arr.arrangement_id, Party.MENTOR)
        self.assertEqual(self.arr.status, ArrangementStatus.PENDING)
        self.service.confirm(self.arr.arrangement_id, Party.COLLEGE)
        self.assertEqual(self.arr.status, ArrangementStatus.CONFIRMED)
        self.assertEqual(self.arr.pending_parties(), [])

    def test_duplicate_confirmation_is_rejected(self):
        self.service.confirm(self.arr.arrangement_id, Party.SCHOOL)
        with self.assertRaises(ValueError):
            self.service.confirm(self.arr.arrangement_id, Party.SCHOOL)

    def test_rejection_cancels_arrangement(self):
        self.service.confirm(self.arr.arrangement_id, Party.SCHOOL)
        self.service.reject(self.arr.arrangement_id, Party.MENTOR, note="带教时间冲突")
        self.assertEqual(self.arr.status, ArrangementStatus.CANCELLED)
        with self.assertRaises(ValueError):
            self.service.confirm(self.arr.arrangement_id, Party.COLLEGE)

    def test_start_requires_full_confirmation(self):
        with self.assertRaises(ValueError):
            self.service.start(self.arr.arrangement_id)
        for party in Party:
            self.service.confirm(self.arr.arrangement_id, party)
        self.service.start(self.arr.arrangement_id)
        self.assertEqual(self.arr.status, ArrangementStatus.STARTED)


if __name__ == "__main__":
    unittest.main()

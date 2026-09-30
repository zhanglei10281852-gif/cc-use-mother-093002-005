import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from teacher_practicum.contracts import PracticumSiteVersion, TraineeProfile

entity = PracticumSiteVersion("E-DEMO", "跨国中文教师实践安排", 1)
record = TraineeProfile("R-DEMO", entity.entity_id, "已登记")
print(json.dumps({"entity": entity.display_name, "revision": entity.revision, "record_state": record.category}, ensure_ascii=False))

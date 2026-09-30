"""Current format admission must reject noncanonical metadata before writes."""
from contextlib import closing
from pathlib import Path

import pytest

from strixnova.delivery_activity import DeliveryActivityAuthority
from strixnova.runtime_upgrade import RuntimeUpgrade, RuntimeUpgradeError
from tests.support.history_records import ITEM_ID, write_history, history_connection
from tests.unit.test_delivery_activity import _plan


@pytest.mark.parametrize("database_kind", ["authority", "delivery_activities"])
@pytest.mark.parametrize("malformed_format", ["01", " 1", "+1"])
def test_precheck_rejects_noncanonical_format_without_changing_project_content(
    tmp_path: Path, database_kind: str, malformed_format: str,
) -> None:
    write_history(tmp_path)
    activity = DeliveryActivityAuthority(tmp_path)
    activity.plan(_plan(), work_item_id=ITEM_ID, work_item_version=3, engineering_plan_id="PLAN-CURRENT")
    filename = "authority.sqlite3" if database_kind == "authority" else "delivery-activities.sqlite3"
    database = tmp_path / ".strixnova" / filename
    with closing(history_connection(database)) as connection, connection:
        connection.execute("UPDATE metadata SET value=? WHERE key='schema_version'", (malformed_format,))
    def project_content():
        # Read-only SQLite may create empty WAL and shared-memory coordination
        # files. They are not business writes or maintained project content.
        return {path.relative_to(tmp_path).as_posix(): path.read_bytes()
                for path in tmp_path.rglob("*") if path.is_file()
                and not path.name.endswith((".sqlite3-wal", ".sqlite3-shm"))}
    before = project_content()
    with pytest.raises(RuntimeUpgradeError) as rejected:
        RuntimeUpgrade(tmp_path).check()
    assert rejected.value.code == "upgrade_source_invalid"
    assert project_content() == before
    assert all(path.stat().st_size == 0 for path in tmp_path.rglob("*.sqlite3-wal"))

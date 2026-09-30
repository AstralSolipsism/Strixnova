BEGIN TRANSACTION;
CREATE TABLE event_annotations (
            event_sequence INTEGER PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            record_json TEXT NOT NULL,
            FOREIGN KEY(event_sequence) REFERENCES events(sequence) ON DELETE RESTRICT,
            FOREIGN KEY(work_item_id) REFERENCES work_items(work_item_id) ON DELETE RESTRICT
        );
CREATE TABLE events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                work_item_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                UNIQUE (work_item_id, version),
                FOREIGN KEY (work_item_id)
                    REFERENCES work_items(work_item_id)
                    ON DELETE RESTRICT
            );
INSERT INTO "events" VALUES(1,'WI-20260928-0B0DBFA5',1,'work_item_created','{"raw_request":"Create one isolated first-use fixture item.","title":"first-intake"}','2026-09-28T15:55:32.408269Z');
INSERT INTO "events" VALUES(2,'WI-20260928-BDB37DF1',1,'work_item_created','{"raw_request":"Create one isolated first-use fixture item.","title":"second-intake"}','2026-09-28T15:55:32.869787Z');
CREATE TABLE evidence_outputs (
            work_item_id TEXT NOT NULL,
            receipt_id TEXT NOT NULL,
            stream TEXT NOT NULL CHECK(stream IN ('stdout','stderr','cases')),
            relative_path TEXT,
            sha256 TEXT,
            size_bytes INTEGER,
            observation_kind TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            availability TEXT NOT NULL,
            PRIMARY KEY(work_item_id,receipt_id,stream),
            FOREIGN KEY(work_item_id) REFERENCES work_items(work_item_id) ON DELETE RESTRICT
        );
CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
INSERT INTO "metadata" VALUES('schema_version','1');
CREATE TABLE work_items (
                work_item_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                version INTEGER NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
INSERT INTO "work_items" VALUES('WI-20260928-0B0DBFA5','first-intake','discussion',1,'{"actual_result":null,"actual_result_confirmation":null,"authority_adoption":null,"blockers":[],"cancellation":null,"direction":null,"direction_confirmation":null,"direction_item_history":{"active_ids":[],"retired_ids":[]},"engineering":{"assessment":null,"plan":null,"plan_confirmation":null},"git":{},"implementation_slice_completions":[],"pending_effect":null,"project_authority_decisions":[],"project_authority_presentations":[],"project_authority_reviews":[],"project_id":null,"raw_request":"Create one isolated first-use fixture item.","repository_deliveries":[],"verifications":[]}','2026-09-28T15:55:32.408269Z','2026-09-28T15:55:32.408269Z');
INSERT INTO "work_items" VALUES('WI-20260928-BDB37DF1','second-intake','discussion',1,'{"actual_result":null,"actual_result_confirmation":null,"authority_adoption":null,"blockers":[],"cancellation":null,"direction":null,"direction_confirmation":null,"direction_item_history":{"active_ids":[],"retired_ids":[]},"engineering":{"assessment":null,"plan":null,"plan_confirmation":null},"git":{},"implementation_slice_completions":[],"pending_effect":null,"project_authority_decisions":[],"project_authority_presentations":[],"project_authority_reviews":[],"project_id":null,"raw_request":"Create one isolated first-use fixture item.","repository_deliveries":[],"verifications":[]}','2026-09-28T15:55:32.869787Z','2026-09-28T15:55:32.869787Z');
CREATE INDEX events_by_work_item
                ON events(work_item_id, sequence)
            ;
CREATE INDEX annotations_by_item ON event_annotations(work_item_id,event_sequence);
CREATE TRIGGER "strixnova_writer_guard__event_annotations__insert" BEFORE INSERT ON "event_annotations" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__event_annotations__update" BEFORE UPDATE ON "event_annotations" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__event_annotations__delete" BEFORE DELETE ON "event_annotations" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__events__insert" BEFORE INSERT ON "events" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__events__update" BEFORE UPDATE ON "events" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__events__delete" BEFORE DELETE ON "events" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__evidence_outputs__insert" BEFORE INSERT ON "evidence_outputs" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__evidence_outputs__update" BEFORE UPDATE ON "evidence_outputs" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__evidence_outputs__delete" BEFORE DELETE ON "evidence_outputs" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__metadata__insert" BEFORE INSERT ON "metadata" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__metadata__update" BEFORE UPDATE ON "metadata" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__metadata__delete" BEFORE DELETE ON "metadata" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__work_items__insert" BEFORE INSERT ON "work_items" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__work_items__update" BEFORE UPDATE ON "work_items" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
CREATE TRIGGER "strixnova_writer_guard__work_items__delete" BEFORE DELETE ON "work_items" WHEN strixnova_write_contract() <> 1 BEGIN SELECT RAISE(ABORT, 'strixnova_write_contract_required'); END;
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('events',2);
COMMIT;

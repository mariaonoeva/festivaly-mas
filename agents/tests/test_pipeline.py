import json
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import closing
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import extraktor
import pipeline
import scout
from adam_agents import db


class PipelineTests(unittest.TestCase):
    def test_scout_to_web_using_html_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dataset = root / "festivals.json"
            original = pipeline.read_dataset(pipeline.ROOT / "data/festivals.json")
            dataset.write_text(json.dumps(original), encoding="utf-8")
            state = root / "state"
            year = date.today().year + 1
            url = "https://festival-fixture.cz/"
            event = {
                "@type": "MusicEvent",
                "name": "Integration Fixture Festival",
                "startDate": f"{year}-07-10",
                "endDate": f"{year}-07-11",
                "eventStatus": "https://schema.org/EventScheduled",
                "genre": "rock",
                "maximumAttendeeCapacity": 1200,
                "performer": [{"name": "Fixture Band"}],
                "location": {
                    "address": {"addressCountry": "CZ", "addressLocality": "Brno"},
                    "geo": {"latitude": 49.1951, "longitude": 16.6068},
                },
            }
            html = '<script type="application/ld+json">' + json.dumps(event) + '</script>'
            args = Namespace(dataset=dataset, state=state, seed_baseline=False, candidates=None, url=[], scout=True,
                             refresh=False, country="Czech Republic", genre="rock", year=year, limit=5)
            previous_cache = extraktor.GEO_CACHE
            try:
                with patch.object(scout, "search_new_festivals", return_value=[SimpleNamespace(url=url)]), \
                     patch.object(extraktor, "smi_stahnout", return_value=True), \
                     patch.object(extraktor, "http_get", return_value=(200, "text/html", html)):
                    pipeline.run(args)
                    first_export = dataset.read_bytes()
                    pipeline.run(args)
                    self.assertEqual(dataset.read_bytes(), first_export)
                    self.assertEqual(dataset.stat().st_mode & 0o777, 0o644)

                    with closing(db.connect(state / "validator.sqlite")) as validator:
                        record = validator.execute("SELECT id FROM festivals").fetchone()
                        db.enqueue_task(validator, type="extract", priority=1, assigned_to="extractor",
                            created_by="freshness", payload={"entity":"festival", "id":record["id"], "url":url})
                        validator.commit()

                    args.scout = False
                    args.refresh = True
                    with patch.dict(os.environ, {"EXA_API_KEY": ""}):
                        pipeline.run(args)

                exported = pipeline.read_dataset(dataset)["festivals"]
                self.assertEqual(exported[:-1], original["festivals"])
                new = exported[-1]
                self.assertEqual(new["name"], "Integration Fixture Festival")
                self.assertEqual(new["date_from"], f"{year}-07-10")
                self.assertEqual(new["lineup"][0]["artists"][0]["name"], "Fixture Band")
                self.assertEqual(new["capacity_cat"], "<5k")
                with closing(db.connect(state / "validator.sqlite")) as validator:
                    self.assertEqual(validator.execute("SELECT status FROM tasks WHERE type='extract'").fetchone()[0], "done")
            finally:
                extraktor.GEO_CACHE = previous_cache

    def test_unapproved_candidate_and_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dataset = root / "festivals.json"
            original = pipeline.read_dataset(pipeline.ROOT / "data/festivals.json")
            dataset.write_text(json.dumps(original), encoding="utf-8")
            invalid = {**original["festivals"][0], "id":"bad-fixture", "name":"Bad Fixture",
                       "website":"", "source_url":"", "city":"Brno"}
            candidate = root / "candidate.json"
            candidate.write_text(json.dumps({"count": 1, "festivals": [invalid]}), encoding="utf-8")
            initial = dataset.read_bytes()
            pipeline.run(Namespace(dataset=dataset, state=root/"state", seed_baseline=False, candidates=candidate))
            self.assertEqual(dataset.read_bytes(), initial)

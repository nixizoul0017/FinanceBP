import copy
import sys
import unittest
from unittest.mock import patch
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etl.checks import verify_reference
from etl.common import read_json
from etl.sources import CONTRACT, load_facts, normalize_mapped, validate_facts, validate_profile
from etl.validation import Catalog, SCHEMAS, parse_row, process_rows


def fixture_catalog():
    catalog = Catalog()
    for table in SCHEMAS:
        rows = read_json(ROOT / f"data/sample/stage3/{table}.json")
        _, rejected, _ = process_rows(table, rows, catalog)
        if rejected:
            raise AssertionError(rejected)
    return catalog


class Stage5FinanceQuality(unittest.TestCase):
    def test_sql_baseline_exact_decimal(self):
        facts = load_facts(ROOT / "configs/sample_files.json")
        result = verify_reference(facts, ROOT / "tests/fixtures/sample_sql_reference.json")
        self.assertTrue(result["passed"])
        self.assertIsInstance(result["company"]["net_revenue"], Decimal)

    def test_missing_money_and_excess_precision_not_zeroed(self):
        row = read_json(ROOT / "data/sample/stage3/order_items.json")[0]
        for value in [None, "", "NaN", "Infinity", "-1", "1.001"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_row("order_items", {**row, "unit_cost_snapshot": value})

    def test_bad_date_and_unknown_reference_rejected(self):
        catalog = fixture_catalog()
        order = read_json(ROOT / "data/sample/stage3/orders.json")[0]
        rows = [{**order, "order_id": "NEW1", "order_date": "2026-02-30"}, {**order, "order_id": "NEW2", "customer_id": "UNKNOWN"}]
        accepted, rejected, skipped = process_rows("orders", rows, catalog)
        self.assertEqual((len(accepted), len(rejected), skipped), (0, 2, 0))
        item = read_json(ROOT / "data/sample/stage3/order_items.json")[0]
        self.assertEqual(process_rows("order_items", [{**item, "order_item_id": "NEW3", "product_id": "UNKNOWN"}], catalog)[1][0]["reason"], "unknown_product")

    def test_same_id_identical_skip_conflict_reject(self):
        catalog = fixture_catalog()
        row = read_json(ROOT / "data/sample/stage3/products.json")[0]
        accepted, rejected, skipped = process_rows("products", [row, {**row, "product_name": "改写历史"}], catalog)
        self.assertEqual((len(accepted), len(rejected), skipped), (0, 1, 1))
        self.assertEqual(rejected[0]["reason"], "business_id_conflict")

    def test_secondary_key_does_not_duplicate_invoice(self):
        catalog = fixture_catalog()
        row = read_json(ROOT / "data/sample/stage3/expenses.json")[0]
        result = process_rows("expenses", [{**row, "expense_id": "OTHER_ID"}], catalog)
        self.assertEqual(result[1][0]["reason"], "business_unique_key_conflict")

    def test_cumulative_refund_limit_across_events(self):
        catalog = fixture_catalog()
        full = next(row for row in catalog.rows["returns"].values() if row["returned_quantity"] == 5)
        row = {**full, "return_id": "EXTRA", "returned_quantity": 1, "recoverable_quantity": 1, "refund_amount": Decimal("110"), "cogs_reversal_amount": Decimal("70")}
        self.assertEqual(process_rows("returns", [row], catalog)[1][0]["reason"], "cumulative_return_exceeds_quantity")

    def test_refund_date_cost_and_status(self):
        catalog = fixture_catalog()
        row = next(iter(catalog.rows["returns"].values()))
        for change, reason in [({"refund_date": date(2026,1,1)}, "refund_before_sale"), ({"cogs_reversal_amount": Decimal("0.01")}, "cost_reversal_mismatch")]:
            _, rejected, _ = process_rows("returns", [{**row, "return_id": "BAD", **change}], catalog)
            self.assertEqual(rejected[0]["reason"], reason)
        unconfirmed = next(item for item in catalog.rows["order_items"].values() if catalog.rows["orders"][(item["order_id"],)]["order_status"] != "completed")
        _, rejected, _ = process_rows("returns", [{**row, "return_id": "BAD2", "order_item_id": unconfirmed["order_item_id"]}], catalog)
        self.assertEqual(rejected[0]["reason"], "refund_on_unconfirmed_order")

    def test_crossmonth_event_not_backdated(self):
        facts = load_facts(ROOT / "configs/sample_files.json")
        from etl.checks import monthly_company
        october = monthly_company(facts).query("month == @month", local_dict={"month": date(2026,10,1)}).iloc[0]
        self.assertEqual((october.net_revenue, october.net_cost, october.gross_margin), (Decimal("-110"), Decimal("-70"), Decimal("-40")))

    def test_missing_cost_does_not_claim_margin(self):
        facts = load_facts(ROOT / "configs/sample_files.json")
        records = {name: frame.to_dict("records") for name, frame in facts.tables.items()}
        for row in records["sales"]:
            row.pop("cogs_amount")
        normalized = normalize_mapped(records, "XCYX_SAMPLE")
        validate_facts(normalized)
        self.assertTrue(all(row["cogs_amount"] is None for row in normalized["sales"]))
        profile = read_json(ROOT / "configs/sample_files.json")
        profile["adapter"] = "mapped_facts_v1"
        with patch("etl.sources.read_source_tables", return_value=(records, [])):
            loaded = load_facts(profile)
        self.assertFalse(loaded.metadata["capabilities"]["margin"])
        self.assertFalse(loaded.metadata["capabilities"]["company_profit"])

    def test_missing_budget_disables_budget_capability(self):
        facts = load_facts(ROOT / "configs/sample_files.json")
        records = {name: frame.to_dict("records") for name, frame in facts.tables.items()}
        records["sales_budget"] = []
        records["expense_budget"] = []
        profile = read_json(ROOT / "configs/sample_files.json")
        profile["adapter"] = "mapped_facts_v1"
        with patch("etl.sources.read_source_tables", return_value=(records, [])):
            loaded = load_facts(profile)
        self.assertTrue(loaded.metadata["capabilities"]["margin"])
        self.assertFalse(loaded.metadata["capabilities"]["budget"])

    def test_data_update_changes_cache_identity(self):
        profile = read_json(ROOT / "configs/sample_files.json")
        first = load_facts(profile)
        records = {name: frame.to_dict("records") for name, frame in first.tables.items()}
        profile["adapter"] = "mapped_facts_v1"
        with patch("etl.sources.read_source_tables", return_value=(records, [])):
            before = load_facts(profile)
        records["sales"][0]["sales_amount_before_refund"] += Decimal("1")
        with patch("etl.sources.read_source_tables", return_value=(records, [])):
            after = load_facts(profile)
        self.assertNotEqual(before.metadata["source_fingerprint"], after.metadata["source_fingerprint"])

    def test_net_of_refund_semantics_block_double_subtraction(self):
        profile = read_json(ROOT / "configs/sample_files.json")
        profile["semantics"]["sales_basis"] = "already_net_of_refunds"
        with self.assertRaisesRegex(ValueError, "unsupported_semantics:sales_basis"):
            validate_profile(profile)

    def test_entity_key_keeps_identical_ids_separate(self):
        facts = load_facts(ROOT / "configs/sample_files.json")
        records = {name: frame.to_dict("records") for name, frame in facts.tables.items()}
        other = copy.deepcopy(records)
        for rows in other.values():
            for row in rows:
                row["entity_id"] = "OTHER"
        validate_facts({name: records[name]+other[name] for name in CONTRACT})


if __name__ == "__main__":
    unittest.main()

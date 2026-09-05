from demand_intelligence_api import assess_inventory


def test_critical_when_out_of_stock():
    result = assess_inventory(0, 100, 20)
    assert result["status"] == "CRITICAL"
    assert result["reorder_candidate"] is True
    assert result["recommended_reorder_quantity"] == 100


def test_reorder_due_at_reorder_point():
    result = assess_inventory(20, 100, 20)
    assert result["status"] == "CRITICAL"  # six days of cover is more urgent than the static point
    assert result["recommended_reorder_quantity"] == 80


def test_watch_with_less_than_month_cover():
    result = assess_inventory(75, 100, 20)
    assert result["status"] == "WATCH"
    assert result["reorder_candidate"] is False


def test_healthy_inventory_does_not_create_reorder_candidate():
    result = assess_inventory(150, 100, 20)
    assert result["status"] == "HEALTHY"
    assert result["recommended_reorder_quantity"] == 0

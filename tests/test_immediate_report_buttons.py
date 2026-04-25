from adami_kernel.nexus.report_wizard_i18n import immediate_report_run_buttons


def test_immediate_report_run_buttons_callbacks():
    rows = immediate_report_run_buttons()
    assert len(rows) == 3
    datas = [r["callback_data"] for r in rows]
    assert datas == ["report:now:daily", "report:now:weekly", "report:now:monthly"]
    assert all(r.get("text") for r in rows)

from adami_kernel.i18n.ui_static import is_entry_menu_command


def test_is_entry_menu_command_basic():
    assert is_entry_menu_command("/menu")
    assert is_entry_menu_command("  /menu  ")
    assert is_entry_menu_command("/menu@SomeBot")
    assert is_entry_menu_command("menu")
    assert is_entry_menu_command("MENU")


def test_is_entry_menu_command_negative():
    assert not is_entry_menu_command("")
    assert not is_entry_menu_command("/menubar")
    assert not is_entry_menu_command("hello")

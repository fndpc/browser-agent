from browser_agent.security import DestructiveApproval, looks_destructive


def test_looks_destructive_keywords() -> None:
    assert looks_destructive("delete email")
    assert looks_destructive("Оплатить заказ")
    assert looks_destructive("Отправить письмо")
    assert not looks_destructive("open inbox")


def test_destructive_approval_single_use() -> None:
    a = DestructiveApproval()
    a.allow_next_for(seconds=30, action_hint="delete")
    assert a.consume_if_valid() is True
    # consumed
    assert a.consume_if_valid() is False


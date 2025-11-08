from bouquin.key_prompt import KeyPrompt


def test_key_prompt_roundtrip(qtbot):
    kp = KeyPrompt()
    qtbot.addWidget(kp)
    kp.show()
    kp.edit.setText("swordfish")
    assert kp.key() == "swordfish"

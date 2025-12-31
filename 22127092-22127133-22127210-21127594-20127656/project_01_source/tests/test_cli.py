import sys
import importlib


def test_raft_cilent_cli_multword(monkeypatch, capsys):
    # Ensure we import a fresh module each time
    if 'raft_cilent' in sys.modules:
        del sys.modules['raft_cilent']
    import raft_cilent

    # Monkeypatch send_command to capture argument and simulate success
    captured = {}

    def fake_send(cmd):
        captured['cmd'] = cmd
        return True

    monkeypatch.setattr(raft_cilent, 'send_command', fake_send)

    # Call the main() function explicitly to trigger the CLI handling
    try:
        raft_cilent.main(argv=['set', 'x', '42'])
    except SystemExit as e:
        assert e.code == 0

    assert captured['cmd'] == 'set x 42'


def test_raft_client_cli_failure(monkeypatch):
    # Test that non-successful send_command leads to non-zero exit
    if 'raft_client' in sys.modules:
        del sys.modules['raft_client']
    import raft_client

    def fake_send(cmd):
        return False

    monkeypatch.setattr(raft_client, 'send_command', fake_send)
    # Call the main() function explicitly to trigger CLI handling
    try:
        raft_client.main(argv=['noop'])
    except SystemExit as e:
        assert e.code == 1

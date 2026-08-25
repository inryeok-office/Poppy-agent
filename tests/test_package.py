from poppy_agent import __version__
from poppy_agent.main import main


def test_package_version_is_available() -> None:
    assert __version__ == "0.1.0"


def test_main_returns_success(capsys) -> None:
    assert main() == 0
    assert "development environment is ready" in capsys.readouterr().out

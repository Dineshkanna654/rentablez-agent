import logging
from rentablez.logger import setup_logger


def test_logger_writes_to_file(tmp_path):
    log_file = tmp_path / "agent.log"
    logger = setup_logger(str(log_file), level=logging.INFO)
    logger.info("hello world")
    for h in logger.handlers:
        h.flush()
    content = log_file.read_text()
    assert "hello world" in content


def test_logger_includes_timestamp(tmp_path):
    log_file = tmp_path / "agent.log"
    logger = setup_logger(str(log_file))
    logger.info("test")
    for h in logger.handlers:
        h.flush()
    line = log_file.read_text()
    # ISO-ish timestamp at the start (first 4 chars are the year)
    assert line[0:4].isdigit()


def test_logger_creates_directory(tmp_path):
    log_file = tmp_path / "nested" / "dir" / "agent.log"
    setup_logger(str(log_file))
    assert log_file.parent.is_dir()


def test_logger_includes_level(tmp_path):
    log_file = tmp_path / "agent.log"
    logger = setup_logger(str(log_file))
    logger.error("oh no")
    for h in logger.handlers:
        h.flush()
    assert "ERROR" in log_file.read_text()


def test_repeated_setup_replaces_handlers(tmp_path):
    """Calling setup_logger twice should NOT result in duplicated log lines."""
    log_file = tmp_path / "agent.log"
    logger = setup_logger(str(log_file))
    logger = setup_logger(str(log_file))  # second call
    logger.info("single entry")
    for h in logger.handlers:
        h.flush()
    content = log_file.read_text()
    assert content.count("single entry") == 1

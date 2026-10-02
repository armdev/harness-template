# expect: clean
import logging

log = logging.getLogger(__name__)


def f():
    log.info("ok")

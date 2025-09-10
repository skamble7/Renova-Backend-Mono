import logging, sys
def configure_logging():
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.handlers.clear(); root.setLevel(logging.INFO); root.addHandler(h)

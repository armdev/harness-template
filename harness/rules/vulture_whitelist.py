# Names vulture reports as unused that are used by a framework. One line each, with the reason.
# Syntax: the bare attribute access, e.g. `_.lifespan  # FastAPI calls it`.
_ = None
_.healthz   # route registered by decorator  # noqa: B018
_.metrics   # route registered by decorator  # noqa: B018

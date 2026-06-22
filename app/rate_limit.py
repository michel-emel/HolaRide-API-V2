from slowapi import Limiter
from slowapi.util import get_remote_address

# Keyed by IP address. NOTE: this is in-memory, which means it only
# works correctly with a SINGLE server process. If you ever run this
# behind multiple uvicorn workers or multiple machines, replace this
# with a Redis-backed limiter (slowapi supports that with one line
# changed) — otherwise each process/machine tracks its own separate
# count and the real limit becomes (your limit × number of processes).
limiter = Limiter(key_func=get_remote_address)

"""System wall clock for the private Files output-authority fence."""

import time


class SystemWallClock:
    now = staticmethod(time.time)

class Reject(Exception):
    """A public-safe gate failure; details must be numbers or fixed labels."""
    def __init__(self, stage, reason, details=None):
        self.stage, self.reason, self.details = stage, reason, details or {}
        super().__init__(stage + ":" + reason)


class BudgetStop(Exception):
    pass


class ResumeBlocked(Exception):
    pass


class ReplayMissing(Exception):
    pass

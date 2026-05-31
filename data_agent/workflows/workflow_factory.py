"""Optional Agno workflow registration stub (aq-core compatible)."""


class WorkflowFactory:
    @staticmethod
    def register(*_args, **_kwargs):
        def decorator(fn):
            return fn

        return decorator

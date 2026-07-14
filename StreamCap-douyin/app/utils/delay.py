class DelayedTaskExecutor:
    def __init__(self, app, settings, delay=3):
        self.app = app
        self.settings = settings
        self.save_timer = None
        self.delay = delay

    async def start_task_timer(self, task, delay: int | None = None):
        """Start a timer to save the configuration after a short delay."""
        if self.save_timer:
            self.save_timer.cancel()

        self.save_timer = self.app.page.run_task(task, delay or self.delay)

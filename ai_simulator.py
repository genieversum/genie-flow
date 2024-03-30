import time
from threading import Thread
from typing import Callable


class AICallSimulator(Thread):

    def __init__(self, callback: Callable, **kwargs):
        super(AICallSimulator, self).__init__(kwargs)
        self.callback = callback

    def run(self):
        time.sleep(3)
        self.callback()

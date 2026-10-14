from mvp_sim.simulator.events import *
from mvp_sim.simulator.event_handler import EventHandler
from mvp_sim.core.environment import Environment
from abc import ABC, abstractmethod

# DriverAssignEvent, PolicyWaitEvent, DriverAssignRepositionEvent
class Policy(ABC):
    """
    should only 'write' to environment via giving events to the event_handler
    should only use DriverAssignEvent, PolicyWaitEvent, DriverAssignRepositionEvent
    when giving events to the event_handler
    """
    @abstractmethod
    def tick(self, event: Event, environment: Environment, event_handler: EventHandler) -> None:
        return
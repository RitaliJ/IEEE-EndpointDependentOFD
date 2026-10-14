from mvp_sim.core.environment import Environment
from .events import *
from .event_handler import EventHandler
from mvp_sim.policies.base import Policy
from tqdm import tqdm

class SimEngine():
    environment: Environment
    event_handler: EventHandler
    policy: Policy

    def __init__(self, environment: Environment, event_handler: EventHandler, policy: Policy):
        self.environment = environment
        self.event_handler = event_handler
        self.policy = policy

    def run(self, progress: bool = True) -> Environment:
        """
        while there are events,
        get the next event (based on time stamp / event_id) ->
        handle the event ->
        tell the policy what event happened and let it react
        """
        horizon = self.environment.horizon
        bar = tqdm(total=horizon, unit="sim-min") if progress else None
        prev_time = 0.0
        update_counter = 0

        while self.event_handler.has_events():
            current_event = self.event_handler.pop_next_event()
            self.event_handler.handle_event(current_event)
            self.policy.tick(current_event, self.environment, self.event_handler)

            if bar is not None:
                update_counter += 1
                if update_counter % 100 == 0:
                    t = getattr(current_event, "time", 0.0)
                    bar.set_postfix(heap=len(self.event_handler.event_timeline), refresh=False)
                    bar.update(max(0.0, t - prev_time))
                    prev_time = t

        if bar is not None:
            bar.update(max(0.0, horizon - prev_time))
            bar.close()

        return self.environment